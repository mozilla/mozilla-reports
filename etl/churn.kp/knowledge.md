---
title: Firefox Destop Churn / Retention Cohort analysis
authors:
- mreid-moz
- Dexterp37
tags:
- churn
- retention
- cohort
- firefox desktop
- main_summary
created_at: 2016-03-28 00:00:00
updated_at: 2016-11-30 13:32:52.499763
tldr: "Compute churn / retention information for unique segments of Firefox \nusers\
  \ acquired during a specific period of time.\n"
---
# Firefox Destop Churn / Retention Cohort analysis

Compute churn / retention information for unique segments of Firefox users acquired during a specific period of time. Tracked in [Bug 1226379](https://bugzilla.mozilla.org/show_bug.cgi?id=1226379). The underlying dataset is generated via the [telemetry-batch-view](https://github.com/mozilla/telemetry-batch-view/blob/master/src/main/scala/com/mozilla/telemetry/views/MainSummaryView.scala) code, and is generated once a day.

The aggregated churn data is updated weekly.

Code is based on the previous [FHR analysis code](https://github.com/mozilla/churn-analysis).

Details and definitions are in [Bug 1198537](https://bugzilla.mozilla.org/show_bug.cgi?id=1198537). 


```python
# How many cores are we running on? 
sc.defaultParallelism
```




    320



### Read source data

Read the data from the parquet datastore on S3.


```python
from pyspark.sql import SQLContext
from pyspark.sql.types import *
import ujson as json
import requests
from datetime import datetime as _datetime, timedelta, date
import gzip
import boto3
import botocore
from boto3.s3.transfer import S3Transfer
from traceback import print_exc
from pyspark.sql.window import Window
import pyspark.sql.functions as func

bucket = "telemetry-parquet"
prefix = "main_summary/v3"
%time dataset = sqlContext.read.load("s3://{}/{}".format(bucket, prefix), "parquet")
```
    CPU times: user 4 ms, sys: 4 ms, total: 8 ms
    Wall time: 21.8 s



```python
dataset = dataset.select('client_id', 'channel', 'normalized_channel', 'country',
                         'profile_creation_date', 'subsession_start_date', 
                         'subsession_length', 'distribution_id', 'sync_configured', 
                         'sync_count_desktop', 'sync_count_mobile', 'app_version', 
                         'timestamp', 'submission_date_s3'
                        ).withColumnRenamed('app_version', 'version')
```

```python
# What do the records look like?
dataset.printSchema()
```
    root
     |-- client_id: string (nullable = true)
     |-- channel: string (nullable = true)
     |-- normalized_channel: string (nullable = true)
     |-- country: string (nullable = true)
     |-- profile_creation_date: integer (nullable = true)
     |-- subsession_start_date: string (nullable = true)
     |-- subsession_length: integer (nullable = true)
     |-- distribution_id: string (nullable = true)
     |-- sync_configured: boolean (nullable = true)
     |-- sync_count_desktop: integer (nullable = true)
     |-- sync_count_mobile: integer (nullable = true)
     |-- version: string (nullable = true)
     |-- timestamp: long (nullable = true)
     |-- submission_date_s3: string (nullable = true)
    


### Clean up the data

Define some helper functions for reorganizing the data.


```python
import re

# Bug 1289573: Support values like "mozilla86" and "mozilla86-utility-existing"
funnelcake_pattern = re.compile("^mozilla[0-9]+.*$")

def get_effective_version(d2v, channel, day):
    """ Get the effective version on the given channel on the given day."""
    if day not in d2v:
        if day < "2015-01-01":
            return "older"
        else:
            return "newer"

    effective_version = d2v[day]
    return get_channel_version(channel, effective_version)

def get_channel_version(channel, version):
    """ Given a channel and an effective release-channel version, give the
    calculated channel-specific version."""
    if channel.startswith('release'):
        return version
    numeric_version = int(version[0:version.index('.')])
    offset = 0
    if channel.startswith('beta'):
        offset = 1
    elif channel.startswith('aurora'):
        offset = 2
    elif channel.startswith('nightly'):
        offset = 3
    return "{}.0".format(numeric_version + offset)

def make_d2v(release_info):
    """ Create a map of yyyy-mm-dd date to the effective Firefox version on the
    release channel.
    """
    # Combine major and minor releases into a map of day -> version
    # Keep only the highest version available for a day range.
    observed_dates = set(release_info["major"].values())
    observed_dates |= set(release_info["minor"].values())
    # Skip old versions.
    sd = [ d for d in sorted(observed_dates) if d >= "2014-01-01" ]
    start_date_str = sd[0]
    start_date = _datetime.strptime(start_date_str, "%Y-%m-%d")
    end_date = _datetime.strptime(sd[-1], "%Y-%m-%d")
    day_count = (end_date - start_date).days + 1
    d2v = {}
    # Start with all the available version release days:
    for t in ["major", "minor"]:
        for m, d in release_info[t].iteritems():
            if d < start_date_str:
                continue
            if d not in d2v or compare_ver(m, d2v[d]) > 0:
                d2v[d] = m
    last_ver = d2v[start_date_str]
    # Fill in all the gaps:
    for dt in (start_date + timedelta(n) for n in range(day_count)):
        d = _datetime.strftime(dt, "%Y-%m-%d")
        if d in d2v:
            # Don't replace a higher version with a new release of an old
            # version (probably an ESR release)
            if compare_ver(d2v[d], last_ver) < 0:
                d2v[d] = last_ver
            else:
                last_ver = d2v[d]
        else:
            d2v[d] = last_ver
    return d2v

def fetch_json(uri):
    """ Perform an HTTP GET on the given uri, return the results as json. If
    there is an error fetching the data, raise it.
    """
    data = requests.get(uri)
    # Raise an exception if the fetch failed.
    data.raise_for_status()
    return data.json()

def compare_ver(a, b):
    """ Logically compare two Firefox version strings. Split the string into
    pieces, and compare each piece numerically.

    Returns -1, 0, or 1 depending on whether a is less than, equal to, or
    greater than b.
    """
    if a == b:
        return 0

    ap = [int(p) for p in a.split(".")]
    bp = [int(p) for p in b.split(".")]
    lap = len(ap)
    lbp = len(bp)

    # min # of pieces
    mp = lap
    if lbp < mp:
        mp = lbp

    for i in range(mp):
        if ap[i] < bp[i]:
            return -1
        if ap[i] > bp[i]:
            return 1

    if lap > lbp:
        # a has more pieces, common pieces are the same, a is greater
        return 1

    if lap < lbp:
        # a has fewer pieces, common pieces are the same, b is greater
        return -1

    # They are exactly the same.
    return 0

def get_release_info():
    """ Fetch information about Firefox release dates. Returns an object
    containing two sections:

    'major' - contains major releases (i.e. 41.0)
    'minor' - contains stability releases (i.e. 41.0.1)
    """
    major_info = fetch_json("https://product-details.mozilla.org/1.0/firefox_history_major_releases.json")
    if major_info is None:
        raise Exception("Failed to fetch major version info")
    minor_info = fetch_json("https://product-details.mozilla.org/1.0/firefox_history_stability_releases.json")
    if minor_info is None:
        raise Exception("Failed to fetch minor version info")
    return {"major": major_info, "minor": minor_info}

def daynum_to_date(daynum):
    """ Convert a number of days to a date. If it's out of range, default to a max date.
    :param daynum: A number of days since Jan 1, 1970
    """
    if daynum is None:
        return None
    if daynum < 0:
        return None
    daycount = int(daynum)
    if daycount > 1000000:
        # Some time in the 48th century, clearly bogus.
        daycount = 1000000
    return date(1970, 1, 1) + timedelta(daycount)

def sane_date(d):
    """ Check if the given date looks like a legitimate time on which activity
    could have happened.
    """
    if d is None:
        return False
    return d > date(2000, 1, 1) and d < _datetime.utcnow().date() + timedelta(2)

def is_funnelcake(distro):
    """ Check if a given distribution_id appears to be a funnelcake build."""
    if distro is None:
        return False
    return funnelcake_pattern.match(distro) is not None

top_countries = set(["US", "DE", "FR", "RU", "BR", "IN", "PL", "ID", "GB", "CN",
                  "IT", "JP", "CA", "ES", "UA", "MX", "AU", "VN", "EG", "AR",
                  "PH", "NL", "IR", "CZ", "HU", "TR", "RO", "GR", "AT", "CH"])

def top_country(country):
    global top_countries
    if(country in top_countries):
        return country
    return "ROW"

def most_recent_sunday(d):
    """ Get the date corresponding to the Sunday on or before the given date."""
    if d is None:
        return None
    weekday = d.weekday()
    if weekday == 6:
        return d
    return d - timedelta(weekday + 1)

def get_week_num(creation, today):
    if creation is None or today is None:
        return None

    diff = (today.date() - creation).days
    if diff < 0:
        # Creation date is in the future. Bad data :(
        return -1
    # The initial week is week zero.
    return int(diff / 7)

# The number of seconds in a single hour, casted to float, so we get the fractional part
# when converting.
SECONDS_IN_HOUR = float(60 * 60)

def convert(d2v, week_start, datum):
    out = {"good": False}

    pcd = daynum_to_date(datum.profile_creation_date)
    if not sane_date(pcd):
        return out

    pcd_formatted = _datetime.strftime(pcd, "%Y-%m-%d")

    out["client_id"] = datum.client_id
    channel = datum.normalized_channel
    out["is_funnelcake"] = is_funnelcake(datum.distribution_id)
    if out["is_funnelcake"]:
        channel = "{}-cck-{}".format(datum.normalized_channel, datum.distribution_id)
    out["channel"] = channel
    out["geo"] = top_country(datum.country)
    out["acquisition_period"] = most_recent_sunday(pcd)
    out["start_version"] = get_effective_version(d2v, channel, pcd_formatted)

    deviceCount = 0
    if datum.sync_count_desktop is not None:
        deviceCount += datum.sync_count_desktop
    if datum.sync_count_mobile is not None:
        deviceCount += datum.sync_count_mobile
            
    if deviceCount > 1:
        out["sync_usage"] = "multiple"
    elif deviceCount == 1:
        out["sync_usage"] = "single"
    elif datum.sync_configured is not None:
        if datum.sync_configured:
            out["sync_usage"] = "single"
        else:
            out["sync_usage"] = "no"
    # Else we don't set sync_usage at all, and use a default value later.
    
    out["current_version"] = datum.version
    
    # The usage time is in seconds, but we really need hours.
    # Because we filter out broken subsession_lengths, we could end up with clients with no
    # usage hours.
    out["usage_hours"] = (datum.usage_seconds / SECONDS_IN_HOUR) if datum.usage_seconds is not None else 0.0
    out["squared_usage_hours"] = out["usage_hours"] ** 2
    
    # Incoming subsession_start_date looks like "2016-02-22T00:00:00.0-04:00"
    client_date = None
    if datum.subsession_start_date is not None:
        try:
            client_date = _datetime.strptime(datum.subsession_start_date[0:10], "%Y-%m-%d")
        except ValueError as e1:
            # Bogus format
            pass
        except TypeError as e2:
            # String contains null bytes or other weirdness. Example:
            # TypeError: must be string without null bytes, not unicode
            pass
    if client_date is None:
        # Fall back to submission date
        client_date = _datetime.strptime(datum.submission_date_s3, "%Y%m%d")
    out["current_week"] = get_week_num(pcd, client_date)
    out["is_active"] = "yes"
    if client_date is not None:
        try:
            if _datetime.strftime(client_date, "%Y%m%d") < week_start:
                out["is_active"] = "no"
        except ValueError as e:
            pass
    out["good"] = True
    return out

def csv(f):
    return ",".join([ unicode(a) for a in f[0] ] + [ unicode(a) for a in f[1] ])

# Build the "effective version" cache:
d2v = make_d2v(get_release_info())

def get_churn_filename(week_start, week_end):
    return "churn-{}-{}.by_activity.csv.gz".format(week_start, week_end)

def get_churn_filepath():
    return "mreid/churn"

def fmt(d, date_format="%Y%m%d"):
    return _datetime.strftime(d, date_format)

def exists(s3client, bucket, s, e):
    churn_key = "{}/{}".format(get_churn_filepath(), get_churn_filename(s, e))
    try:
        s3client.head_object(Bucket=bucket, Key=churn_key)
    except botocore.exceptions.ClientError as e:
        if e.response['Error']['Code'] == "404":
            return False
        else:
            raise e
    return True
```
### Compute the aggregates

Run the aggregation code, detecting files that are missing.

The fields we want in the output are:
 - channel (appUpdateChannel)
 - geo (bucketed into top 30 countries + "rest of world")
 - is_funnelcake (contains "-cck-"?)
 - acquisition_period (cohort_week)
 - start_version (effective version on profile creation date)
 - sync_usage ("no", "single" or "multiple" devices)
 - current_version (current appVersion)
 - current_week (week)
 - is_active (were the client_ids active this week or not)
 - n_profiles (count of matching client_ids)
 - usage_hours (sum of the per-client subsession lengths, clamped in the [0, MAX_SUBSESSION_LENGTH] range)
 - sum_squared_usage_hours (the sum of squares of the usage hours)


```python
from operator import add

def get_newest_per_client(df):
    windowSpec = Window.partitionBy(df['client_id']).orderBy(df['timestamp'].desc())
    # Note: use 'rowNumber' instead of 'row_number' with Spark < v1.6
    rownum_by_timestamp = (func.row_number().over(windowSpec))
    selectable_by_client = df.select(
        df['client_id'],
        df['channel'],
        df['normalized_channel'],
        df['country'],
        df['profile_creation_date'],
        df['subsession_start_date'],
        df['submission_date'],
        df['sync_configured'],
        df['sync_count_desktop'],
        df['sync_count_mobile'],
        df['distribution_id'],
        df['version'],
        df['timestamp'],
        rownum_by_timestamp.alias('row_number')
    )
    return selectable_by_client.filter(selectable_by_client['row_number'] == 1)

DO_UPLOAD = True

world_start = '20151101'
today = _datetime.utcnow()
todays = fmt(today)
wsd = _datetime.strptime(world_start, "%Y%m%d")
week_start_date = wsd
week_end_date = week_start_date + timedelta(6)
week_start = fmt(week_start_date)
week_end = fmt(week_end_date)

client = boto3.client('s3', 'us-west-2')
transfer = S3Transfer(client)
bucket = "net-mozaws-prod-us-west-2-pipeline-analysis"

MAX_SUBSESSION_LENGTH = 60 * 60 * 48 # 48 hours in seconds.

df = dataset
# Stop at the last complete week
while week_end < todays:
    # Allow this many days for data for a given activity period to arrive.
    week_end_slop = fmt(week_end_date + timedelta(10))
    
    # If the data for this week can still be coming, don't try to compute the churn.
    # That also means we can break out of the loop.
    if week_end_slop >= todays:
        print "Skipping week of {} to {} - Data is still arriving until {}.".format(week_start, week_end, week_end_slop)
        break
    
    # Compute missing data periods.
    if exists(client, bucket, week_start, week_end):
        print "Week of {} to {} already exists".format(week_start, week_end)
    else:
        print "Starting week from {} to {} at {}".format(week_start, week_end, _datetime.utcnow())
        # the subsession_start_date field has a different form than submission_date_s3,
        # so needs to be formatted with hyphens.
        week_end_excl = fmt(week_end_date + timedelta(1), date_format="%Y-%m-%d")
        week_start_hyphenated = fmt(week_start_date, date_format="%Y-%m-%d")
        
        current_week = df.filter(df['submission_date_s3'] >= week_start).filter(df['submission_date_s3'] <= week_end_slop).filter(df['subsession_start_date'] >= week_start_hyphenated).filter(df['subsession_start_date'] < week_end_excl).drop('submission_date_s3')
        newest_per_client = get_newest_per_client(current_week)

        # Clamp broken subsession values in the [0, MAX_SUBSESSION_LENGTH] range.
        clamped_subsession = current_week.select(current_week['client_id'],
                                                 func.when(current_week['subsession_length'] > MAX_SUBSESSION_LENGTH, MAX_SUBSESSION_LENGTH)\
                                                     .otherwise(func.when(current_week['subsession_length'] < 0, 0).otherwise(current_week['subsession_length']))\
                                                     .alias('subsession_length'))
        
        # Compute the overall usage time for each client by summing the subsession lengths.
        grouped_usage_time = clamped_subsession.groupby('client_id')\
                                               .sum('subsession_length')\
                                               .withColumnRenamed('sum(subsession_length)', 'usage_seconds')

        # Append this column to the original data frame.
        newest_with_usage = newest_per_client.join(grouped_usage_time, 'client_id', 'inner')
        
        converted = newest_with_usage.map(lambda x: convert(d2v, week_start, x))

        # Don't bother to filter out non-good records - they will appear 
        # as 'unknown' in the output.
        countable = converted.map(lambda x: ((
                    x.get('channel', 'unknown'),
                    x.get('geo', 'unknown'),
                    "yes" if x.get('is_funnelcake', False) else "no",
                    _datetime.strftime(x.get('acquisition_period', date(2000, 1, 1)), "%Y-%m-%d"),
                    x.get('start_version', 'unknown'),
                    x.get('sync_usage', 'unknown'),
                    x.get('current_version', 'unknown'),
                    x.get('current_week', 'unknown'),
                    x.get('is_active', 'unknown')), (1, x.get('usage_hours', 0), x.get('squared_usage_hours', 0))))

        def reduce_func(x, y):
            return (x[0] + y[0], # Sum active users
                    x[1] + y[1], # Sum usage_hours
                    x[2] + y[2]) # Sum squared_usage_hours
        aggregated = countable.reduceByKey(reduce_func)
        churn_outfile = get_churn_filename(week_start, week_end)
        
        print "{}: collecting aggregates".format(_datetime.utcnow())
        records = aggregated.collect()
        print "{}: done collecting aggregates".format(_datetime.utcnow())
        print "{}: Writing output to {}".format(_datetime.utcnow(), churn_outfile)

        # Write the file out as gzipped csv
        with gzip.open(churn_outfile, 'wb') as fout:
            fout.write("channel,geo,is_funnelcake,acquisition_period,start_version,sync_usage,current_version,current_week,is_active,n_profiles,usage_hours,sum_squared_usage_hours\n")
            print "{}: Wrote header to {}".format(_datetime.utcnow(), churn_outfile)
            for r in records:
                try:
                    fout.write(csv(r))
                    fout.write("\n")
                except UnicodeEncodeError as e:
                    print "{}: Error writing line: {} // {}".format(_datetime.utcnow(), e, r)
            print "{}: finished writing lines".format(_datetime.utcnow())

        # Now upload it to S3:
        if DO_UPLOAD:
            churn_s3 = "{}/{}".format(get_churn_filepath(), churn_outfile)
            transfer.upload_file(churn_outfile, bucket, churn_s3,
                                 extra_args={'ACL': 'bucket-owner-full-control'})
            
            # Also upload it to the dashboard:
            # Update the dashboard file
            dash_bucket = "net-mozaws-prod-metrics-data"
            dash_s3_name = "telemetry-churn/{}".format(churn_outfile)
            transfer.upload_file(churn_outfile, dash_bucket, dash_s3_name,
                                 extra_args={'ACL': 'bucket-owner-full-control'})
        
        print "Finished week from {} to {} at {}".format(week_start, week_end, _datetime.utcnow())
    # Move forward by a week
    week_start_date += timedelta(7)
    week_end_date += timedelta(7)
    week_start = fmt(week_start_date)
    week_end = fmt(week_end_date)
```
    Week of 20151101 to 20151107 already exists
    Week of 20151108 to 20151114 already exists
    Week of 20151115 to 20151121 already exists
    Week of 20151122 to 20151128 already exists
    Starting week from 20151129 to 20151205 at 2016-02-25 17:51:10.877731
    2016-02-25 17:51:11.008565: collecting aggregates
    2016-02-25 17:56:37.385371: done collecting aggregates
    2016-02-25 17:56:37.386151: Writing output to churn-20151129-20151205.csv.gz.by_activity5
    2016-02-25 17:56:37.386378: Wrote header to churn-20151129-20151205.csv.gz.by_activity5
    2016-02-25 17:56:48.245838: finished writing lines
    Finished week from 20151129 to 20151205 at 2016-02-25 17:56:48.449721
    Starting week from 20151206 to 20151212 at 2016-02-25 17:56:48.450176
    2016-02-25 17:56:48.576869: collecting aggregates
    2016-02-25 18:02:16.869842: done collecting aggregates
    2016-02-25 18:02:16.870523: Writing output to churn-20151206-20151212.csv.gz.by_activity5
    2016-02-25 18:02:16.870742: Wrote header to churn-20151206-20151212.csv.gz.by_activity5
    2016-02-25 18:02:27.844529: finished writing lines
    Finished week from 20151206 to 20151212 at 2016-02-25 18:02:28.005866
    Starting week from 20151213 to 20151219 at 2016-02-25 18:02:28.006440
    2016-02-25 18:02:28.137427: collecting aggregates
    2016-02-25 18:07:52.782727: done collecting aggregates
    2016-02-25 18:07:52.783551: Writing output to churn-20151213-20151219.csv.gz.by_activity5
    2016-02-25 18:07:52.783779: Wrote header to churn-20151213-20151219.csv.gz.by_activity5
    2016-02-25 18:08:08.672998: finished writing lines
    Finished week from 20151213 to 20151219 at 2016-02-25 18:08:08.862909
    Starting week from 20151220 to 20151226 at 2016-02-25 18:08:08.863503
    2016-02-25 18:08:08.991054: collecting aggregates
    2016-02-25 18:13:21.106278: done collecting aggregates
    2016-02-25 18:13:21.107007: Writing output to churn-20151220-20151226.csv.gz.by_activity5
    2016-02-25 18:13:21.107237: Wrote header to churn-20151220-20151226.csv.gz.by_activity5
    2016-02-25 18:13:40.233727: finished writing lines
    Finished week from 20151220 to 20151226 at 2016-02-25 18:13:40.470278
    Starting week from 20151227 to 20160102 at 2016-02-25 18:13:40.470792
    2016-02-25 18:13:40.598394: collecting aggregates
    2016-02-25 18:18:50.421359: done collecting aggregates
    2016-02-25 18:18:50.422046: Writing output to churn-20151227-20160102.csv.gz.by_activity5
    2016-02-25 18:18:50.422273: Wrote header to churn-20151227-20160102.csv.gz.by_activity5
    2016-02-25 18:19:11.885004: finished writing lines
    Finished week from 20151227 to 20160102 at 2016-02-25 18:19:12.068829
    Starting week from 20160103 to 20160109 at 2016-02-25 18:19:12.069415
    2016-02-25 18:19:12.197376: collecting aggregates
    2016-02-25 18:24:49.537347: done collecting aggregates
    2016-02-25 18:24:49.538047: Writing output to churn-20160103-20160109.csv.gz.by_activity5
    2016-02-25 18:24:49.538270: Wrote header to churn-20160103-20160109.csv.gz.by_activity5
    2016-02-25 18:25:12.344934: finished writing lines
    Finished week from 20160103 to 20160109 at 2016-02-25 18:25:12.857178
    Starting week from 20160110 to 20160116 at 2016-02-25 18:25:12.857770
    2016-02-25 18:25:13.040382: collecting aggregates
    2016-02-25 18:31:05.980641: done collecting aggregates
    2016-02-25 18:31:05.981293: Writing output to churn-20160110-20160116.csv.gz.by_activity5
    2016-02-25 18:31:05.981511: Wrote header to churn-20160110-20160116.csv.gz.by_activity5
    2016-02-25 18:31:27.072130: finished writing lines
    Finished week from 20160110 to 20160116 at 2016-02-25 18:31:27.307505
    Starting week from 20160117 to 20160123 at 2016-02-25 18:31:27.307976
    2016-02-25 18:31:27.432604: collecting aggregates
    2016-02-25 18:37:09.561716: done collecting aggregates
    2016-02-25 18:37:09.562399: Writing output to churn-20160117-20160123.csv.gz.by_activity5
    2016-02-25 18:37:09.562628: Wrote header to churn-20160117-20160123.csv.gz.by_activity5
    2016-02-25 18:37:29.982858: finished writing lines
    Finished week from 20160117 to 20160123 at 2016-02-25 18:37:30.193391
    Week of 20160124 to 20160130 already exists
    Week of 20160131 to 20160206 already exists
    Week of 20160207 to 20160213 already exists
    Week of 20160214 to 20160220 already exists
