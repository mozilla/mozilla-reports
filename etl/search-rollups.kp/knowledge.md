---
title: Daily Search Rollups
authors:
- spenrose
tags:
- search
created_at: 2017-02-14 00:00:00
updated_at: 2017-02-16 15:27:01.107146
tldr: Group searches by key dimensions and export to CSV. This code has not been formally
  peer-reviewed.
---
```python
READ_VERSION = 3
READ_STEM = 's3://telemetry-parquet/main_summary/v{}/'.format(READ_VERSION)
READ_TAIL = 'submission_date_s3={}/'
DAY_READ_PATH = READ_STEM + READ_TAIL

WRITE_VERSION = 1
BASH_WRITE_STEM = 's3://net-mozaws-prod-us-west-2-pipeline-analysis/' \
    'spenrose/search/to_vertica/'
ROLLUP_WRITE_STEM = BASH_WRITE_STEM + 'daily/'
MANIFEST_WRITE_STEM = BASH_WRITE_STEM + 'manifests/'

PROFILE_DAY = 'profile_day'
PROFILE_COLUMN = 'concat(client_id, submission_date) as {}'.format(PROFILE_DAY)
def add_profile_day(frame):
    return frame.selectExpr(
        "*",
        PROFILE_COLUMN
    )
```

```python
import time
TEMP_TABLE_TEMPLATE = 'rollup_temp_{}'

# SELECT_ROLLUP_TEMPLATE says: gather all permutations of
# submission_date, country, search_provider, default_provider,
# locale, distribution_id and count:
# 1) How many searches fall into each permutation? -> search_count
# 2) How many profiles fall into each bucket -> profile_count
# 3) What share of total profiles does this bucket represent? -> profile_share
# The distinction between profile_count and profile_share is necessary
# because on a given submission_date a single user of a profile may switch
# default search engine (or locale or geo), or a profile may be shared by
# multiple users on a day (causing all the other fields to vary if the
# users are on widely distributed machines).
SELECT_ROLLUP_TEMPLATE = """
SELECT
  submission_date,
  search_provider,
  sum(search_count) as search_count,
  country,
  locale,
  distribution_id,
  default_provider,
  count(distinct profile_day) as profile_count,
  sum(profile_share) as profile_share
FROM
  {}
WHERE
  ((search_count > -1) OR (search_count is null))
GROUP BY
  submission_date, country, search_provider, default_provider, locale, distribution_id
"""

# SELECT_SHARE says: given a single profile_day with N permutations of
# (search_provider, country, locale, distribution_id, default_provider),
# N = an integer > 0, assign each row a profile_share of 1/N.
# Example #1: a user switches default mid-day -> she generates two
# rows, each with profile_count = 1 and profile_share = 0.5.
# Example #2: a profile is cloned to ten laptops, the users of which
# change default engines, travel across country borders, etc. ->
# they generate N rows whose profile_counts sum to 10 and whose
# profile_share sums to 1.0.
SELECT_SHARE = """
SELECT
  {}.*,
  share_table.profile_share
FROM
  {}, (
    SELECT
      profile_day,
      1.0/count(*) AS profile_share
    FROM
      {}
    GROUP BY profile_day)
  share_table
WHERE
  {}.profile_day = share_table.profile_day
"""

def roll_up_searches(frame):
    try:
        frame[PROFILE_DAY]
    except Exception:
        frame = add_profile_day(frame)
    frame.repartition("profile_day")
    nulls_frame = frame.where('search_counts is null')
    temp_table = TEMP_TABLE_TEMPLATE.format(int(time.time()))
    select_rollup = SELECT_ROLLUP_TEMPLATE.format(temp_table)
 
    exploded = frame.selectExpr(
        "submission_date",
        "profile_day",
        "country",
        "locale",
        "distribution_id",
        "default_search_engine as default_provider",
        "explode(search_counts) as search_counts")
    unwrapped = exploded.selectExpr(
        "submission_date",
        "profile_day",
        "country",
        "locale",
        "distribution_id",
        "default_provider",
        "search_counts.engine as search_provider",
        "search_counts.count as search_count")
    unwrapped_nulls = nulls_frame.selectExpr(
        "submission_date",
        "profile_day",
        "country",
        "locale",
        "distribution_id",
        "default_search_engine as default_provider",
        "'NO_SEARCHES' as search_provider",
        "0 as search_count"
    )
    unwrapped_all = unwrapped.unionAll(unwrapped_nulls)
    share_temp = 'share_temp_{}'.format(int(time.time()))
    select_share = SELECT_SHARE.format(
        share_temp, share_temp, share_temp, share_temp)
    unwrapped_all.registerTempTable(share_temp)
    shared = sqlContext.sql(select_share)
    shared.registerTempTable(temp_table)
    searches_by_period = sqlContext.sql(select_rollup)
    return searches_by_period
```

```python
import datetime as DT, subprocess, sys
BASENAME = 'daily-rollup-of-searches-submitted-{}-format-{}.csv'
def get_s3_write_path(date):
    return ROLLUP_WRITE_STEM + BASENAME.format(date, WRITE_VERSION)

def main(date=None, rerun=False):
    date = date or DT.date.today().isoformat()
    if not rerun:
        # See if the output exists already.
        cmd = "aws s3 ls {}".format(get_s3_write_path(date))
        exists = not subprocess.call(cmd, shell=True)
        if exists:
            bn = BASENAME.format(date, WRITE_VERSION)
            report(bn, "not written", ["already exists"])
            sys.exit(1)
        
    # This will throw an AnalysisException if the path doesn't exist.
    day_path = DAY_READ_PATH.format(date.replace('-', ''))
    local = []
    print "starting", date, "at:", str(DT.datetime.now())[:19]
    for i in range(100):
        print i,
        sys.stdout.flush()
        sample_path = day_path + 'sample_id={}/'.format(i)
        frame = sqlContext.read.parquet(sample_path)
        search_frame = roll_up_searches(frame)
        results = search_frame.collect()
        local.extend(results)
        search_frame.unpersist()
        frame.unpersist()
    print "finished at:", str(DT.datetime.now())[:19]
    return local
```

```python
def to_iso(eight):
    return '-'.join([eight[:4], eight[4:6], eight[6:]])

import csv, subprocess, sys

def coalesce(rows):
    d = {}
    for r in rows:
        k = (r.submission_date, r.search_provider or 'NO_SEARCHES', r.country,
             r.locale or 'xx', r.distribution_id or 'MOZILLA',
             r.default_provider or 'NO_DEFAULT')
        if k in d:
            searches, people, share = d[k]
        else:
            searches, people, share = 0, 0, 0
        d[k] = (searches + (r.search_count or 0),
                people + r.profile_count,
                share + round(r.profile_share, 2))
    return d

def dump_dict(d, basename):
    bad = []
    processed = DT.date.today().strftime('%Y-%m-%d')
    with open(basename, 'w') as f:
        writer = csv.writer(f)
        for k, v in d.iteritems():
            (submission_date, search_provider, country, locale, 
             distribution_id, default_provider) = k
            search_count, profile_count, profile_share = v
            try:
                row = (to_iso(submission_date), search_provider,
                       str(search_count), country, locale,
                       distribution_id,
                       default_provider,
                       str(profile_count), str(profile_share), processed)
                row = [s.encode("utf-8") for s in row]
                writer.writerow(row)
            except Exception:
                bad.append((k, v))
    copy = "aws s3 cp {} {}".format(basename, ROLLUP_WRITE_STEM)
    subprocess.check_call(copy, shell=True)
    return bad
```

```python
def write_manifest(date, version, *paths):
    text = '\n'.join(paths) + '\n'
    tries = version + 10
    while True:
        manifest_basename = 'daily-search-rollup-manifest-{}-v{}.txt'.format(date, version)
        path = MANIFEST_WRITE_STEM + manifest_basename
        if subprocess.call("aws s3 ls {}".format(path), shell=True):
            break
        version += 1
        if version == tries:
            raise Exception("Can't find unwritten manifest at {}".format(path))
    with open(manifest_basename, 'w') as f:
        f.write(text)
    copy = "aws s3 cp {} {}".format(manifest_basename, MANIFEST_WRITE_STEM)
    subprocess.check_call(copy, shell=True)

import smtplib
from email.message import Message

owner = 'spenrose' # XXX read from environment
owner += '@mozilla.com'
def report(date, path, bad):
    subject = "Daily search rollups for {}".format(date)
    if bad:
        subject += ": %d failures" % len(bad)
    body = 'written to {}'.format(path)
    if bad:
        body += '\nproblem rows:\n'
        for row in bad[:10]:
            body += str(row) + '\n'
    
    msg = Message()
    msg.set_payload(body)
    msg['Subject'] = subject
    msg['To'] = owner
    msg['From'] = owner
    smtp = smtplib.SMTP('localhost')
    smtp.sendmail(owner, owner, msg.as_string())
```

```python
date = (DT.date.today()-DT.timedelta(1)).isoformat()
rows = main(date)
dicty = coalesce(rows)
basename = BASENAME.format(date, WRITE_VERSION)
bad = dump_dict(dicty, basename)
path = get_s3_write_path(date)
try:
    write_manifest(DT.date.today().isoformat(), 1, path)
except Exception:
    report(date, path, ["Manifest writing failed"])
report(date, path, bad)
```

```python

```
