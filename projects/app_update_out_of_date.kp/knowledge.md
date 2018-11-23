---
title: Firefox Application Update Out Of Date dashboard
authors:
- rstrong
tags:
- firefox
- app_update
created_at: 2017-02-16 00:00:00
updated_at: 2018-11-22 17:47:07.344662
tldr: Creates the JSON data files used by the Firefox Application Update Out Of Date
  dashboard.
---
### Motivation

Generate data for the Firefox Application Update Out Of Date dashboard


```python
import datetime as dt
import re
import urllib2
import ujson as json
import boto3
from boto3.s3.transfer import S3Transfer

%pylab inline
```

```python
sc.defaultParallelism
```
Get the time when this job started.


```python
start_time = dt.datetime.now()
print "Start: " + str(start_time.strftime("%Y-%m-%d %H:%M:%S"))
```
Common settings.


```python
no_upload = None
today_str = None

# Uncomment out the following two lines and adjust |today_str| as necessary to run manually without uploading the json.
no_upload = True
# today_str = "20161226"

channel_to_process = "release"
min_version = 42
up_to_date_releases = 2
weeks_of_subsession_data = 12
min_update_ping_count = 4
min_subsession_hours = 2
min_subsession_seconds = min_subsession_hours * 60 * 60
```
Get the settings based on dates.


```python
if today_str is None:
    today_str = start_time.strftime("%Y%m%d")

assert (today_str is not None), "The date environment parameter is missing."
today = dt.datetime.strptime(today_str, "%Y%m%d").date()

# MON = 0, SAT = 5, SUN = 6 -> SUN = 0, MON = 1, SAT = 6
day_index = (today.weekday() + 1) % 7
# Filename used to save the report's JSON
report_filename = (today - datetime.timedelta(day_index)).strftime("%Y%m%d")
# Maximum report date which is the previous Saturday
max_report_date = today - datetime.timedelta(7 + day_index - 6)
# Suffix of the longitudinal datasource name to use
longitudinal_suffix = max_report_date.strftime("%Y%m%d")
# String used in the SQL queries to limit records to the maximum report date.
# Since the queries use less than this is the day after the previous Saturday.
max_report_date_sql = (max_report_date + dt.timedelta(days=1)).strftime("%Y-%m-%d")
# The Sunday prior to the last Saturday
min_report_date = max_report_date - dt.timedelta(days=6)
# String used in the SQL queries to limit records to the minimum report date
# Since the queries use greater than this is six days prior to the previous Saturday.
min_report_date_sql = min_report_date.strftime("%Y-%m-%d")
# Date used to limit records to the number of weeks specified by
# weeks_of_subsession_data prior to the maximum report date
min_subsession_date = max_report_date - dt.timedelta(weeks=weeks_of_subsession_data)
# Date used to compute the latest version from firefox_history_major_releases.json
latest_ver_date_str = (max_report_date - dt.timedelta(days=7)).strftime("%Y-%m-%d")

print "max_report_date     : " + max_report_date.strftime("%Y%m%d")
print "max_report_date_sql : " + max_report_date_sql
print "min_report_date     : " + min_report_date.strftime("%Y%m%d")
print "min_report_date_sql : " + min_report_date_sql
print "min_subsession_date : " + min_subsession_date.strftime("%Y%m%d")
print "report_filename     : " + report_filename
print "latest_ver_date_str : " + latest_ver_date_str
```
Get the latest Firefox version available based on the date.


```python
def latest_version_on_date(date, major_releases):
    latest_date = u"1900-01-01"
    latest_ver = 0
    for version, release_date in major_releases.iteritems():
        version_int = int(version.split(".")[0])
        if release_date <= date and release_date >= latest_date and version_int >= latest_ver:
            latest_date = release_date
            latest_ver = version_int

    return latest_ver

major_releases_json = urllib2.urlopen("https://product-details.mozilla.org/1.0/firefox_history_major_releases.json").read()
major_releases = json.loads(major_releases_json)
latest_version = latest_version_on_date(latest_ver_date_str, major_releases)
earliest_up_to_date_version = str(latest_version - up_to_date_releases)

print "Latest Version: " + str(latest_version)
```
Create a dictionary to store the general settings that will be written to a JSON file.


```python
report_details_dict = {"latestVersion": latest_version,
                       "upToDateReleases": up_to_date_releases,
                       "minReportDate": min_report_date.strftime("%Y-%m-%d"),
                       "maxReportDate": max_report_date.strftime("%Y-%m-%d"),
                       "weeksOfSubsessionData": weeks_of_subsession_data,
                       "minSubsessionDate": min_subsession_date.strftime("%Y-%m-%d"),
                       "minSubsessionHours": min_subsession_hours,
                       "minSubsessionSeconds": min_subsession_seconds,
                       "minUpdatePingCount": min_update_ping_count}
report_details_dict
```
Create the common SQL FROM clause.


```python
# Note: using the parquet is as fast as using 'FROM longitudinal_vYYYMMDD'
# and it allows the query to go further back in time.

#longitudinal_from_sql = ("FROM longitudinal_v{} ").format(longitudinal_suffix)
longitudinal_from_sql = ("FROM parquet.`s3://telemetry-parquet/longitudinal/v{}` ").format(longitudinal_suffix)  
longitudinal_from_sql
```
Create the common build.version SQL WHERE clause.


```python
build_version_where_sql = "(build.version[0] RLIKE '^[0-9]{2,3}\.0[\.0-9]*$' OR build.version[0] = '50.1.0')"
build_version_where_sql
```
Create the remaining common SQL WHERE clause.


```python
common_where_sql = (""
    "build.application_name[0] = 'Firefox' AND "
    "DATEDIFF(SUBSTR(subsession_start_date[0], 0, 10), '{}') >= 0 AND "
    "DATEDIFF(SUBSTR(subsession_start_date[0], 0, 10), '{}') < 0 AND "
    "settings.update.channel[0] = '{}'"
"").format(min_report_date_sql,
           max_report_date_sql,
           channel_to_process)
common_where_sql
```
Create the SQL for the summary query.


```python
summary_sql = (""
"SELECT "
    "COUNT(CASE WHEN build.version[0] >= '{}.' AND build.version[0] < '{}.' THEN 1 END) AS versionUpToDate, "
    "COUNT(CASE WHEN build.version[0] < '{}.' AND build.version[0] >= '{}.' THEN 1 END) AS versionOutOfDate, "
    "COUNT(CASE WHEN build.version[0] < '{}.' THEN 1 END) AS versionTooLow, "
    "COUNT(CASE WHEN build.version[0] > '{}.' THEN 1 END) AS versionTooHigh, "
    "COUNT(CASE WHEN NOT build.version[0] > '0' THEN 1 END) AS versionMissing "
"{} "
"WHERE "
    "{} AND "
    "{}"
"").format(str(latest_version - up_to_date_releases),
           str(latest_version + 2),
           str(latest_version - up_to_date_releases),
           str(min_version),
           str(min_version),
           str(latest_version + 2),
           longitudinal_from_sql,
           common_where_sql,
           build_version_where_sql)
summary_sql
```
Run the summary SQL query.


```python
summaryDF = sqlContext.sql(summary_sql)
```
Create a dictionary to store the results from the summary query that will be written to a JSON file.


```python
summary_dict = summaryDF.first().asDict()
summary_dict
```
Create the SQL for the out of date details query.


```python
# Only query for the columns and the records that are used to optimize
# for speed. Adding update_state_code_partial_stage and
# update_state_code_complete_stage increased the time it takes this
# notebook to run by 50 seconds when using 4 clusters.

# Creating a temporary table of the data after the filters have been
# applied and joining it with the original datasource to include
# other columns doesn't appear to speed up the process but it doesn't
# appear to slow it down either so all columns of interest are in this
# query.

out_of_date_details_sql = (""
"SELECT "
    "client_id, "
    "build.version, "
    "session_length, "
    "settings.update.enabled, "
    "subsession_start_date, "
    "subsession_length, "
    "update_check_code_notify, "
    "update_check_extended_error_notify, "
    "update_check_no_update_notify, "
    "update_not_pref_update_auto_notify, "
    "update_ping_count_notify, "
    "update_unable_to_apply_notify, "
    "update_download_code_partial, "
    "update_download_code_complete, "
    "update_state_code_partial_stage, "
    "update_state_code_complete_stage, "
    "update_state_code_unknown_stage, "
    "update_state_code_partial_startup, "
    "update_state_code_complete_startup, "
    "update_state_code_unknown_startup, "
    "update_status_error_code_complete_startup, "
    "update_status_error_code_partial_startup, "
    "update_status_error_code_unknown_startup, "
    "update_status_error_code_complete_stage, "
    "update_status_error_code_partial_stage, "
    "update_status_error_code_unknown_stage "
"{}"
"WHERE "
    "{} AND "
    "{} AND "
    "build.version[0] < '{}.' AND "
    "build.version[0] >= '{}.'"
"").format(longitudinal_from_sql,
           common_where_sql,
           build_version_where_sql,
           str(latest_version - up_to_date_releases),
           str(min_version))
out_of_date_details_sql
```
Run the out of date details SQL query.


```python
out_of_date_details_df = sqlContext.sql(out_of_date_details_sql)
```
Create the RDD used to further restrict which clients are out of date
to focus on clients that are of concern and potentially of concern.


```python
out_of_date_details_rdd = out_of_date_details_df.rdd.cache()
```
### The next several cells are to find the clients that are "out of date, potentially of concern" so they can be excluded from the "out of date, of concern" clients.

Create an RDD of out of date telemetry pings that have and don't have
a previous telemetry ping with a version that is up to date along
with a dictionary of the count of True and False.


```python
def has_out_of_date_max_version_mapper(d):
    ping = d
    index = 0
    while (index < len(ping.version)):
        if ((ping.version[index] == "50.1.0" or
             p.match(ping.version[index])) and
            ping.version[index] > earliest_up_to_date_version):
            return False, ping
        index += 1

    return True, ping

# RegEx for a valid release versions except for 50.1.0 which is handled separately.
p = re.compile('^[0-9]{2,3}\\.0[\\.0-9]*$')

has_out_of_date_max_version_rdd = out_of_date_details_rdd.map(has_out_of_date_max_version_mapper).cache()
has_out_of_date_max_version_dict = has_out_of_date_max_version_rdd.countByKey()
has_out_of_date_max_version_dict
```
Create an RDD of the telemetry pings that have a previous telemetry ping
with a version that is up to date.


```python
has_out_of_date_max_version_true_rdd = has_out_of_date_max_version_rdd.filter(lambda p: p[0] == True).values().cache()
```
Create an RDD of out of date telemetry pings that have and have not
sent an update telemtry ping for any version of Firefox along with a
dictionary of the count of True and False.


```python
def has_update_ping_mapper(d):
    ping = d
    if (ping.update_ping_count_notify is not None and
        (ping.update_check_code_notify is not None or
         ping.update_check_no_update_notify is not None)):
        return True, ping

    return False, ping

has_update_ping_rdd = has_out_of_date_max_version_true_rdd.map(has_update_ping_mapper).cache()
has_update_ping_dict = has_update_ping_rdd.countByKey()
has_update_ping_dict
```
Create an RDD of the telemetry pings that have an update telemtry
ping for any version of Firefox.


```python
has_update_ping_true_rdd = has_update_ping_rdd.filter(lambda p: p[0] == True).values().cache()
```
Create an RDD of out of date telemetry pings that have and have not
ran this version of Firefox for more than the amount of seconds as
specified by min_subsession_seconds along with a dictionary of the
count of True and False.


```python
def has_min_subsession_length_mapper(d):
    ping = d
    seconds = 0
    index = 0
    current_version = ping.version[0]
    while (seconds < min_subsession_seconds and
           index < len(ping.subsession_start_date) and
           index < len(ping.version) and
           ping.version[index] == current_version):
        try:
            date = dt.datetime.strptime(ping.subsession_start_date[index][:10],
                                        "%Y-%m-%d").date()
            if date < min_subsession_date:
                return False, ping

            seconds += ping.subsession_length[index]
            index += 1
        except: # catch *all* exceptions
            index += 1

    if seconds >= min_subsession_seconds:
        return True, ping

    return False, ping

has_min_subsession_length_rdd = has_update_ping_true_rdd.map(has_min_subsession_length_mapper).cache()
has_min_subsession_length_dict = has_min_subsession_length_rdd.countByKey()
has_min_subsession_length_dict
```
Create an RDD of the telemetry pings that have ran this version of
Firefox for more than the amount of seconds as specified by
min_subsession_seconds.


```python
has_min_subsession_length_true_rdd = has_min_subsession_length_rdd.filter(lambda p: p[0] == True).values().cache()
```
Create an RDD of out of date telemetry pings that have and have not
sent the minimum number of update pings as specified by
min_update_ping_count for this version of Firefox along with a
dictionary of the count of True and False.


```python
def has_min_update_ping_count_mapper(d):
    ping = d
    index = 0
    update_ping_count_total = 0
    current_version = ping.version[0]
    while (update_ping_count_total < min_update_ping_count and
           index < len(ping.update_ping_count_notify) and
           index < len(ping.version) and
           ping.version[index] == current_version):

        pingCount = ping.update_ping_count_notify[index]
        # Is this an update ping or just a placeholder for the telemetry ping?
        if pingCount > 0:
            try:
                date = dt.datetime.strptime(ping.subsession_start_date[index][:10],
                                            "%Y-%m-%d").date()
                if date < min_subsession_date:
                    return False, ping

            except: # catch *all* exceptions
                index += 1
                continue

            # Is there also a valid update check code or no update telemetry ping?
            if (ping.update_check_code_notify is not None and
                len(ping.update_check_code_notify) > index):
                for code_value in ping.update_check_code_notify[index]:
                    if code_value > 0:
                        update_ping_count_total += pingCount
                        index += 1
                        continue

            if (ping.update_check_no_update_notify is not None and
                len(ping.update_check_no_update_notify) > index and
                ping.update_check_no_update_notify[index] > 0):
                update_ping_count_total += pingCount

        index += 1

    if update_ping_count_total < min_update_ping_count:
        return False, ping

    return True, ping

has_min_update_ping_count_rdd = has_min_subsession_length_true_rdd.map(has_min_update_ping_count_mapper).cache()
has_min_update_ping_count_dict = has_min_update_ping_count_rdd.countByKey()
has_min_update_ping_count_dict
```
Create an RDD of the telemetry pings that have sent the minimum
number of update pings as specified by min_update_ping_count.


```python
has_min_update_ping_count_true_rdd = has_min_update_ping_count_rdd.filter(lambda p: p[0] == True).values().cache()
```
Create an RDD of out of date telemetry pings that are supported and
are not supported based on whether they have not received or have
received the unsupported update xml for the last update check along
with a dictionary of the count of True and False.


```python
def is_supported_mapper(d):
    ping = d
    index = 0
    update_ping_count_total = 0
    current_version = ping.version[0]
    while (update_ping_count_total < min_update_ping_count and
           index < len(ping.update_ping_count_notify) and
           index < len(ping.version) and
           ping.version[index] == current_version):
        pingCount = ping.update_ping_count_notify[index]
        # Is this an update ping or just a placeholder for the telemetry ping?
        if pingCount > 0:
            # Is there also a valid update check code or no update telemetry ping?
            if (ping.update_check_code_notify is not None and
                len(ping.update_check_code_notify) > index and
                ping.update_check_code_notify[index][28] > 0):
                return False, ping

        index += 1
        
    return True, ping

is_supported_rdd = has_min_update_ping_count_true_rdd.map(is_supported_mapper).cache()
is_supported_dict = is_supported_rdd.countByKey()
is_supported_dict
```
Create an RDD of the telemetry pings that are supported based on
whether they have not received or have received the unsupported
update xml for the last update check.


```python
is_supported_true_rdd = is_supported_rdd.filter(lambda p: p[0] == True).values().cache()
```
Create an RDD of out of date telemetry pings that have and don't have
the ability to apply an update along with a dictionary of the count 
of True and False.


```python
def is_able_to_apply_mapper(d):
    ping = d
    index = 0
    current_version = ping.version[0]
    while (index < len(ping.update_ping_count_notify) and
           index < len(ping.version) and
           ping.version[index] == current_version):
        if ping.update_ping_count_notify[index] > 0:
            # Only check the last value for update_unable_to_apply_notify
            # to determine if the client is unable to apply.
            if (ping.update_unable_to_apply_notify is not None and
                ping.update_unable_to_apply_notify[index] > 0):
                return False, ping

            return True, ping

        index += 1

    raise ValueError("Missing update unable to apply value!")

is_able_to_apply_rdd = is_supported_true_rdd.map(is_able_to_apply_mapper).cache()
is_able_to_apply_dict = is_able_to_apply_rdd.countByKey()
is_able_to_apply_dict
```
Create an RDD of the telemetry pings that have the ability to apply
an update.


```python
is_able_to_apply_true_rdd = is_able_to_apply_rdd.filter(lambda p: p[0] == True).values().cache()
```
Create an RDD of out of date telemetry pings that have and don't have
application update enabled via policy along with a dictionary of the
count of True and False.


```python
def has_update_enabled_mapper(d):
    ping = d
    index = 0
    current_version = ping.version[0]
    while (index < len(ping.update_ping_count_notify) and
           index < len(ping.version) and
           ping.version[index] == current_version):
        if ping.update_ping_count_notify[index] > 0:
            # If there is an update ping and settings.update.enabled has a value
            # for the same telemetry submission then use the value of
            # settings.update.enabled to determine whether app update is enabled.
            # This isn't 100% accurate because the update ping and the value for
            # settings.update.enabled are gathered at different times but it is
            # accurate enough for this report.
            if (ping.enabled is not None and
                ping.enabled[index] is False):
                return False, ping

            return True, ping

        index += 1

    raise ValueError("Missing update enabled value!")

has_update_enabled_rdd = is_able_to_apply_true_rdd.map(has_update_enabled_mapper).cache()
has_update_enabled_dict = has_update_enabled_rdd.countByKey()
has_update_enabled_dict
```
### The next several cells categorize the clients that are "out of date, of concern".

Create a reference to the dictionary which will be written to the
JSON that populates the web page data. This way the reference in the
web page never changes. A reference is all that is needed since the
dictionary is not modified.


```python
of_concern_dict = has_update_enabled_dict
```
Create an RDD of the telemetry pings that have the
application.update.enabled preference set to True.

This RDD is created from the last "out of date, potentially of concern"
RDD and it is named of_concern_true_rdd to simplify the addition of new code
without having to modify consumers of the RDD.


```python
of_concern_true_rdd = has_update_enabled_rdd.filter(lambda p: p[0] == True).values().cache()
```
Create an RDD of out of date, of concern telemetry ping client
versions along with a dictionary of the count of each version.


```python
def by_version_mapper(d):
    ping = d
    return ping.version[0], ping

of_concern_by_version_rdd = of_concern_true_rdd.map(by_version_mapper)
of_concern_by_version_dict = of_concern_by_version_rdd.countByKey()
of_concern_by_version_dict
```
Create an RDD of out of date, of concern telemetry ping update check
codes along with a dictionary of the count of each update check code.


```python
def check_code_notify_mapper(d):
    ping = d
    index = 0
    current_version = ping.version[0]
    while (index < len(ping.update_ping_count_notify) and
           index < len(ping.version) and
           ping.version[index] == current_version):
        if (ping.update_ping_count_notify[index] > 0 and
            ping.update_check_code_notify is not None):
            code_index = 0
            for code_value in ping.update_check_code_notify[index]:
                if code_value > 0:
                    return code_index, ping
                code_index += 1

            if (ping.update_check_no_update_notify is not None and
                ping.update_check_no_update_notify[index] > 0):
                return 0, ping

        index += 1

    return -1, ping

check_code_notify_of_concern_rdd = of_concern_true_rdd.map(check_code_notify_mapper)
check_code_notify_of_concern_dict = check_code_notify_of_concern_rdd.countByKey()
check_code_notify_of_concern_dict
```
Create an RDD of out of date, of concern telemetry pings that had a
general failure for the update check. The general failure codes are:
* CHK_GENERAL_ERROR_PROMPT: 22
* CHK_GENERAL_ERROR_SILENT: 23


```python
check_code_notify_general_error_of_concern_rdd = \
    check_code_notify_of_concern_rdd.filter(lambda p: p[0] == 22 or p[0] == 23).values().cache()
```
Create an RDD of out of date, of concern telemetry ping update check
extended error values for the clients that had a general failure for
the update check along with a dictionary of the count of the error
values.


```python
def check_ex_error_notify_mapper(d):
    ping = d
    current_version = ping.version[0]
    for index, version in enumerate(ping.version):
        if (ping.update_ping_count_notify[index] > 0 and
            ping.update_check_extended_error_notify is not None):
            for key_name in ping.update_check_extended_error_notify:
                if ping.update_check_extended_error_notify[key_name][index] > 0:
                    if version == current_version:
                        key_name = key_name[17:]
                        if len(key_name) == 4:
                            key_name = key_name[1:]
                        return int(key_name), ping
                    return -1, ping

    return -2, ping

check_ex_error_notify_of_concern_rdd = check_code_notify_general_error_of_concern_rdd.map(check_ex_error_notify_mapper)
check_ex_error_notify_of_concern_dict = check_ex_error_notify_of_concern_rdd.countByKey()
check_ex_error_notify_of_concern_dict
```
Create an RDD of out of date, of concern telemetry ping update
download codes along with a dictionary of the count of the codes.


```python
def download_code_mapper(d):
    ping = d
    current_version = ping.version[0]
    for index, version in enumerate(ping.version):
        if ping.update_download_code_partial is not None:
            code_index = 0
            for code_value in ping.update_download_code_partial[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

        if ping.update_download_code_complete is not None:
            code_index = 0
            for code_value in ping.update_download_code_complete[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

    return -2, ping

download_code_of_concern_rdd = of_concern_true_rdd.map(download_code_mapper)
download_code_of_concern_dict = download_code_of_concern_rdd.countByKey()
download_code_of_concern_dict
```
Create an RDD of out of date, of concern telemetry ping staged update
state codes along with a dictionary of the count of the codes.


```python
def state_code_stage_mapper(d):
    ping = d
    current_version = ping.version[0]
    for index, version in enumerate(ping.version):
        if ping.update_state_code_partial_stage is not None:
            code_index = 0
            for code_value in ping.update_state_code_partial_stage[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

        if ping.update_state_code_complete_stage is not None:
            code_index = 0
            for code_value in ping.update_state_code_complete_stage[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

        if ping.update_state_code_unknown_stage is not None:
            code_index = 0
            for code_value in ping.update_state_code_unknown_stage[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

    return -2, ping

state_code_stage_of_concern_rdd = of_concern_true_rdd.map(state_code_stage_mapper).cache()
state_code_stage_of_concern_dict = state_code_stage_of_concern_rdd.countByKey()
state_code_stage_of_concern_dict
```
Create an RDD of out of date, of concern telemetry pings that failed
to stage an update.
* STATE_FAILED: 12


```python
state_code_stage_failed_of_concern_rdd = \
    state_code_stage_of_concern_rdd.filter(lambda p: p[0] == 12).values().cache()
```
Create an RDD of out of date, of concern telemetry ping staged update
state failure codes along with a dictionary of the count of the codes.


```python
def state_failure_code_stage_mapper(d):
    ping = d
    current_version = ping.version[0]
    for index, version in enumerate(ping.version):
        if ping.update_status_error_code_partial_stage is not None:
            code_index = 0
            for code_value in ping.update_status_error_code_partial_stage[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

        if ping.update_status_error_code_complete_stage is not None:
            code_index = 0
            for code_value in ping.update_status_error_code_complete_stage[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

        if ping.update_status_error_code_unknown_stage is not None:
            code_index = 0
            for code_value in ping.update_status_error_code_unknown_stage[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

    return -2, ping

state_failure_code_stage_of_concern_rdd = state_code_stage_failed_of_concern_rdd.map(state_failure_code_stage_mapper)
state_failure_code_stage_of_concern_dict = state_failure_code_stage_of_concern_rdd.countByKey()
state_failure_code_stage_of_concern_dict
```
Create an RDD of out of date, of concern telemetry ping startup
update state codes along with a dictionary of the count of the codes.


```python
def state_code_startup_mapper(d):
    ping = d
    current_version = ping.version[0]
    for index, version in enumerate(ping.version):
        if ping.update_state_code_partial_startup is not None:
            code_index = 0
            for code_value in ping.update_state_code_partial_startup[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

        if ping.update_state_code_complete_startup is not None:
            code_index = 0
            for code_value in ping.update_state_code_complete_startup[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

        if ping.update_state_code_unknown_startup is not None:
            code_index = 0
            for code_value in ping.update_state_code_unknown_startup[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

    return -2, ping

state_code_startup_of_concern_rdd = of_concern_true_rdd.map(state_code_startup_mapper).cache()
state_code_startup_of_concern_dict = state_code_startup_of_concern_rdd.countByKey()
state_code_startup_of_concern_dict
```
Create an RDD of the telemetry pings that have ping startup update state code equal to 12.


```python
state_code_startup_failed_of_concern_rdd = \
    state_code_startup_of_concern_rdd.filter(lambda p: p[0] == 12).values().cache()
```
Create an RDD of out of date, of concern telemetry ping startup
update state failure codes along with a dictionary of the count of the
codes.


```python
def state_failure_code_startup_mapper(d):
    ping = d
    current_version = ping.version[0]
    for index, version in enumerate(ping.version):
        if ping.update_status_error_code_partial_startup is not None:
            code_index = 0
            for code_value in ping.update_status_error_code_partial_startup[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

        if ping.update_status_error_code_complete_startup is not None:
            code_index = 0
            for code_value in ping.update_status_error_code_complete_startup[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

        if ping.update_status_error_code_unknown_startup is not None:
            code_index = 0
            for code_value in ping.update_status_error_code_unknown_startup[index]:
                if code_value > 0:
                    if version == current_version:
                        return code_index, ping
                    return -1, ping
                code_index += 1

    return -2, ping

state_failure_code_startup_of_concern_rdd = state_code_startup_failed_of_concern_rdd.map(state_failure_code_startup_mapper)
state_failure_code_startup_of_concern_dict = state_failure_code_startup_of_concern_rdd.countByKey()
state_failure_code_startup_of_concern_dict
```
Create an RDD of out of date, of concern telemetry pings that have
and have not received only no updates available during the update
check for their current version of Firefox along with a dictionary
of the count of values.


```python
def has_only_no_update_found_mapper(d):
    ping = d
    if ping.update_check_no_update_notify is None:
        return False, ping

    current_version = ping.version[0]
    for index, version in enumerate(ping.version):
        if current_version != version:
            return True, ping

        if ping.update_ping_count_notify[index] > 0:
            # If there is an update ping and update_check_no_update_notify
            # has a value equal to 0 then the update check returned a
            # value other than no update found. This could be improved by
            # checking the check value for error conditions and ignoring
            # those codes and ignoring the check below for those cases.
            if (ping.update_check_no_update_notify[index] == 0):
                return False, ping

    return True, ping

has_only_no_update_found_rdd = of_concern_true_rdd.map(has_only_no_update_found_mapper).cache()
has_only_no_update_found_dict = has_only_no_update_found_rdd.countByKey()
has_only_no_update_found_dict
```
Create an RDD of the telemetry pings that have not received only no updates
available during the update check for their current version of Firefox.


```python
has_only_no_update_found_false_rdd = has_only_no_update_found_rdd.filter(lambda p: p[0] == False).values().cache()
```
Create an RDD of out of date, of concern telemetry pings that have and
don't have any update download pings for their current version of
Firefox along with a dictionary of the count of the values.


```python
def has_no_download_code_mapper(d):
    ping = d
    current_version = ping.version[0]
    for index, version in enumerate(ping.version):
        if current_version != version:
            return True, ping

        if ping.update_download_code_partial is not None:
            for code_value in ping.update_download_code_partial[index]:
                if code_value > 0:
                    return False, ping

        if ping.update_download_code_complete is not None:
            for code_value in ping.update_download_code_complete[index]:
                if code_value > 0:
                    return False, ping

    return True, ping

has_no_download_code_rdd = has_only_no_update_found_false_rdd.map(has_no_download_code_mapper).cache()
has_no_download_code_dict = has_no_download_code_rdd.countByKey()
has_no_download_code_dict
```
Create an RDD of the telemetry pings that don't have any update
download pings for their current version of Firefox.


```python
has_no_download_code_false_rdd = has_no_download_code_rdd.filter(lambda p: p[0] == False).values().cache()
```
Create an RDD of out of date, of concern telemetry pings that have and
don't have an update failure state for their current version of
Firefox along with a dictionary of the count of the values.


```python
def has_update_apply_failure_mapper(d):
    ping = d
    current_version = ping.version[0]
    for index, version in enumerate(ping.version):
        if current_version != version:
            return False, ping

        if (ping.update_state_code_partial_startup is not None and
            ping.update_state_code_partial_startup[index][12] > 0):
            return True, ping

        if (ping.update_state_code_complete_startup is not None and
            ping.update_state_code_complete_startup[index][12] > 0):
            return True, ping

    return False, ping

has_update_apply_failure_rdd = has_no_download_code_false_rdd.map(has_update_apply_failure_mapper)
has_update_apply_failure_dict = has_update_apply_failure_rdd.countByKey()
has_update_apply_failure_dict
```
Create a reference to the dictionary which will be written to the
JSON that populates the web page data. This way the reference in the
web page never changes. A reference is all that is needed since the
dictionary is not modified.


```python
of_concern_categorized_dict = has_update_apply_failure_dict
```
Create the JSON that will be written to a file for the report.


```python
results_dict = {"reportDetails": report_details_dict,
                "summary": summary_dict,
                "hasOutOfDateMaxVersion": has_out_of_date_max_version_dict,
                "hasUpdatePing": has_update_ping_dict,
                "hasMinSubsessionLength": has_min_subsession_length_dict,
                "hasMinUpdatePingCount": has_min_update_ping_count_dict,
                "isSupported": is_supported_dict,
                "isAbleToApply": is_able_to_apply_dict,
                "hasUpdateEnabled": has_update_enabled_dict,
                "ofConcern": of_concern_dict,
                "hasOnlyNoUpdateFound": has_only_no_update_found_dict,
                "hasNoDownloadCode": has_no_download_code_dict,
                "hasUpdateApplyFailure": has_update_apply_failure_dict,
                "ofConcernCategorized": of_concern_categorized_dict,
                "ofConcernByVersion": of_concern_by_version_dict,
                "checkCodeNotifyOfConcern": check_code_notify_of_concern_dict,
                "checkExErrorNotifyOfConcern": check_ex_error_notify_of_concern_dict,
                "downloadCodeOfConcern": download_code_of_concern_dict,
                "stateCodeStageOfConcern": state_code_stage_of_concern_dict,
                "stateFailureCodeStageOfConcern": state_failure_code_stage_of_concern_dict,
                "stateCodeStartupOfConcern": state_code_startup_of_concern_dict,
                "stateFailureCodeStartupOfConcern": state_failure_code_startup_of_concern_dict}
results_json = json.dumps(results_dict, ensure_ascii=False)
results_json
```
Save the output to be uploaded automatically once the job completes.
The file will be stored at:
* https://analysis-output.telemetry.mozilla.org/app-update/data/out-of-date/FILENAME


```python
filename = "./output/" + report_filename + ".json"
if no_upload is None:
    with open(filename, 'w') as f:
        f.write(results_json)
        
    bucket = "telemetry-public-analysis-2"
    path = "app-update/data/out-of-date/"
    timestamped_s3_key = path + report_filename + ".json"
    client = boto3.client('s3', 'us-west-2')
    transfer = S3Transfer(client)
    transfer.upload_file(filename, bucket, timestamped_s3_key, extra_args={'ContentType':'application/json'})

print "Filename: " + filename
```
Get the time when this job ended.


```python
end_time = dt.datetime.now()
print "End: " + str(end_time.strftime("%Y-%m-%d %H:%M:%S"))
```
Get the elapsed time it took to run this job.


```python
elapsed_time = end_time - start_time
print "Elapsed Seconds: " + str(int(elapsed_time.total_seconds()))
```
