---
title: Bug 1291340 - Import sync log data
authors:
- mreid-moz
tags:
- sync
- etl
created_at: 2016-11-15 00:00:00
updated_at: 2017-02-23 11:26:45.796626
tldr: Read, convert, and store sync log data to Parquet form per [bug 1291340](https://bugzilla.mozilla.org/show_bug.cgi?id=1291340).
---
## Bug 1291340 - Import sync log data

Read, convert, and store sync log data to Parquet form per [bug 1291340](https://bugzilla.mozilla.org/show_bug.cgi?id=1291340).

Conversion code is ported from the [smt repo](https://github.com/dannycoates/smt).


```python
from datetime import datetime as dt, timedelta, date
from moztelemetry.dataset import Dataset
from os import environ

# Determine run parameters
source_bucket = 'net-mozaws-prod-us-west-2-pipeline-analysis'
dest_bucket = source_bucket
dest_s3_prefix = "s3://{}/mreid".format(dest_bucket)

if "bucket" in os.environ:
    dest_bucket = environ["bucket"]
    dest_s3_prefix = "s3://{}".format(dest_bucket)

yesterday = dt.strftime(dt.utcnow() - timedelta(1), "%Y%m%d")

# Default to running for "yesterday" unless we've been given a
# specific date via the environment.
target_day = environ.get("date", yesterday)
print "Running import for {}".format(target_day)
```
### Read the source log data

The sync data on S3 is stored in framed heka format, and is read using the `Dataset` API.


```python
# Read the source data
schema = ['name', 'prefix']
target_name = 'sync-metrics'
target_prefix = 'data'
sync = Dataset(source_bucket, schema).where(name=target_name).where(prefix=target_prefix)

# The sync data on S3 does not have a proper "date" dimension, but the date is encoded 
# in the key names themselves.
# Fetch the summaries and filter the list to the target day.
summary_prefix = "{}/{}/{}".format(target_name, target_prefix, target_day)
sync_summaries = [ s for s in sync.summaries(sc) if s['key'].startswith(summary_prefix) ]
```
### Custom heka decoder

The standard heka decoder assumes (based on Telemetry data) that all fields whose names have a `.` in them contain nested json strings. This is not true for sync log messages, which have fields such as `syncstorage.storage.sql.db.execute` with simple scalar values.


```python
import ssl
from moztelemetry.heka.message_parser import unpack

# Custom decoder for sync messages since we can have scalar fields with dots in their names.
def sync_decoder(message):
    try:
        for record, total_bytes in unpack(message):
            result = {}
            result["meta"] = {
                "Timestamp": record.message.timestamp,
                "Type":      record.message.type,
                "Hostname":  record.message.hostname,
            }
            for field in record.message.fields:
                name = field.name
                value = field.value_string
                if field.value_type == 1:
                    # TODO: handle bytes in a way that doesn't cause problems with JSON
                    # value = field.value_bytes
                    continue
                elif field.value_type == 2:
                    value = field.value_integer
                elif field.value_type == 3:
                    value = field.value_double
                elif field.value_type == 4:
                    value = field.value_bool

                result[name] = value[0] if len(value) else ""

            yield result

    except ssl.SSLError:
        pass  # https://github.com/boto/boto/issues/2830

sync_records = sync.records(sc, decode=sync_decoder, summaries=sync_summaries)
```

```python
# What do the records look like?

# Example heka message:
#Timestamp: 2016-10-28 15:11:45.98653696 -0300 ADT
#Type: mozsvc.metrics
#Hostname: ip-172-31-39-11
#Pid: 11383
#UUID: 155866c8-cc58-4048-a58c-6226c620fc57
#Logger: Sync-1_5
#Payload:
#EnvVersion: 1
#Severity: 7
#Fields: [name:"remoteAddressChain" representation:"" value_string:"" value_string:""  
#         name:"path" value_string:"https://host/ver/somenum/storage/tabs"  
#         name:"fxa_uid" value_string:"some_id"  
#         name:"user_agent_version" value_type:DOUBLE value_double:49  
#         name:"user_agent_os" value_string:"Windows 7"  
#         name:"device_id" value_string:"some_device_id"  
#         name:"method" value_string:"POST"  
#         name:"user_agent_browser" value_string:"Firefox"  
#         name:"name" value_string:"mozsvc.metrics"  
#         name:"request_time" value_type:DOUBLE value_double:0.003030061721801758  
#         name:"code" value_type:DOUBLE value_double:200 
#        ]

# Example record:
#sync_records.first()

# {u'code': 200.0,
#  u'device_id': u'some_device_id',
#  u'fxa_uid': u'some_id',
#  'meta': {'Hostname': u'ip-172-31-39-11',
#   'Timestamp': 1477678305976742912L,
#   'Type': u'mozsvc.metrics'},
#  u'method': u'GET',
#  u'name': u'mozsvc.metrics',
#  u'path': u'https://host/ver/somenum/storage/crypto/keys',
#  u'remoteAddressChain': u'',
#  u'request_time': 0.017612934112548828,
#  u'syncstorage.storage.sql.db.execute': 0.014925241470336914,
#  u'syncstorage.storage.sql.pool.get': 5.221366882324219e-05,
#  u'user_agent_browser': u'Firefox',
#  u'user_agent_os': u'Windows 7',
#  u'user_agent_version': 49.0}
```

```python
# Convert data. Code ported from https://github.com/dannycoates/smt
import re
import hashlib
import math
from pyspark.sql import Row

def sha_prefix(v):
    h = hashlib.sha256()
    h.update(v)
    return h.hexdigest()[0:32]

path_uid = re.compile("(\d+)\/storage\/")
path_bucket = re.compile("\d+\/storage\/(\w+)")

def getUid(path):
    if path is None:
        return None
    match = re.search(path_uid, path)
    if match is not None:
        uid = match.group(1)
        return sha_prefix(uid)
    return None

def deriveDeviceId(uid, agent):
    if uid is None:
        return None
    return sha_prefix("{}{}".format(uid, agent))

SyncRow = Row("uid", "s_uid", "dev", "s_dev", "ts", "method", "code", 
              "bucket", "t", "ua_browser", "ua_version", "ua_os", "host")

def convert(msg):
    bmatch = re.search(path_bucket, msg.get("path", ""))
    if bmatch is None:
        return None
    bucket = bmatch.group(1)
    
    uid = msg.get("fxa_uid")
    synth_uid = getUid(msg.get("path"))
    dev = msg.get("device_id")
    synth_dev = deriveDeviceId(synth_uid,
        "{}{}{}".format(
            msg.get("user_agent_browser", ""),
            msg.get("user_agent_version", ""),
            msg.get("user_agent_os", ""))
      )
    
    code = 200
    # support modern mozlog's use of errno for http status
    errno = msg.get("errno")
    if errno is not None:
        if errno == 0: # success
            code = 200
        else:
            code = errno
    else:
        code = msg.get("code")
        if code is not None:
            code = int(code)
    
    t = msg.get("t", 0)
    if t == 0:
        t = math.floor(msg.get("request_time", 0) * 1000)
    if t is None:
        t = 0

    converted = SyncRow(
        (uid or synth_uid),
        synth_uid,
        (dev or synth_dev),
        synth_dev,
        msg.get("meta").get("Timestamp"),
        msg.get("method"),
        code,
        bucket,
        t,
        msg.get("user_agent_browser"),
        msg.get("user_agent_version"),
        msg.get("user_agent_os"),
        msg.get("meta").get("Hostname"),
    )
    return converted
```

```python
converted = sync_records.map(lambda x: convert(x))
```

```python
converted = converted.filter(lambda x: x is not None)
```

```python
from pyspark.sql import SQLContext
sync_df = sqlContext.createDataFrame(converted)
sync_df.printSchema()
```
    root
     |-- uid: string (nullable = true)
     |-- s_uid: string (nullable = true)
     |-- dev: string (nullable = true)
     |-- s_dev: string (nullable = true)
     |-- ts: long (nullable = true)
     |-- method: string (nullable = true)
     |-- code: long (nullable = true)
     |-- bucket: string (nullable = true)
     |-- t: double (nullable = true)
     |-- ua_browser: string (nullable = true)
     |-- ua_version: double (nullable = true)
     |-- ua_os: string (nullable = true)
     |-- host: string (nullable = true)
    



```python
# Determine if we need to repartition.
# A record is something like 112 bytes, so figure out how many partitions
# we need to end up with reasonably-sized files.
records_per_partition = 2500000
total_records = sync_df.count()
print "Found {} sync records".format(total_records)
```

```python
import math
num_partitions = int(math.ceil(float(total_records) / records_per_partition))

if num_partitions != sync_df.rdd.getNumPartitions():
    print "Repartitioning with {} partitions".format(num_partitions)
    sync_df = sync_df.repartition(num_partitions)

# Store data
sync_log_s3path = "{}/sync_log/v1/day={}".format(dest_s3_prefix, target_day)
sync_df.write.parquet(sync_log_s3path, mode="overwrite")
```

```python
# Transform, compute and store rollups
sync_df.registerTempTable("sync")
sql_transform = '''
  select
    uid,
    dev,
    ts,
    t,
    case 
     when substring(ua_os,0,7) in ('iPad', 'iPod', 'iPhone') then 'ios'
     when substring(ua_os,0,7) = 'Android' then 'android'
     when substring(ua_os,0,7) = 'Windows' then 'windows'
     when substring(ua_os,0,7) = 'Macinto' then 'mac'
     when substring(ua_os,0,7) = 'Linux' then 'linux'
     when ua_os is null then 'unknown'
     else 'other'
    end as ua_os,
    ua_browser,
    ua_version,
    case method when 'POST' then 1 end as posts,
    case method when 'GET' then 1 end as gets,
    case method when 'PUT' then 1 end as puts,
    case method when 'DELETE' then 1 end as dels,
    case when code < 300 then 1 end as aoks,
    case when code > 399 and code < 500 then 1 end as oops,
    case when code > 499 and code < 999 then 1 end as fups,
    case when bucket = 'clients' and method = 'GET' then 1 end as r_clients,
    case when bucket = 'crypto' and method = 'GET' then 1 end as r_crypto,
    case when bucket = 'forms' and method = 'GET' then 1 end as r_forms,
    case when bucket = 'history' and method = 'GET' then 1 end as r_history,
    case when bucket = 'keys' and method = 'GET' then 1 end as r_keys,
    case when bucket = 'meta' and method = 'GET' then 1 end as r_meta,
    case when bucket = 'bookmarks' and method = 'GET' then 1 end as r_bookmarks,
    case when bucket = 'prefs' and method = 'GET' then 1 end as r_prefs,
    case when bucket = 'tabs' and method = 'GET' then 1 end as r_tabs,
    case when bucket = 'passwords' and method = 'GET' then 1 end as r_passwords,
    case when bucket = 'addons' and method = 'GET' then 1 end as r_addons,
    case when bucket = 'clients' and method = 'POST' then 1 end as w_clients,
    case when bucket = 'crypto' and method = 'POST' then 1 end as w_crypto,
    case when bucket = 'forms' and method = 'POST' then 1 end as w_forms,
    case when bucket = 'history' and method = 'POST' then 1 end as w_history,
    case when bucket = 'keys' and method = 'POST' then 1 end as w_keys,
    case when bucket = 'meta' and method = 'POST' then 1 end as w_meta,
    case when bucket = 'bookmarks' and method = 'POST' then 1 end as w_bookmarks,
    case when bucket = 'prefs' and method = 'POST' then 1 end as w_prefs,
    case when bucket = 'tabs' and method = 'POST' then 1 end as w_tabs,
    case when bucket = 'passwords' and method = 'POST' then 1 end as w_passwords,
    case when bucket = 'addons' and method = 'POST' then 1 end as w_addons
  from sync
'''

transformed = sqlContext.sql(sql_transform)
```

```python
transformed.registerTempTable("tx")

sql_device_activity = '''
  select
    uid,
    dev,
    max(ua_os) as ua_os,
    max(ua_browser) as ua_browser,
    max(ua_version) as ua_version,
    min(t) as min_t,
    max(t) as max_t,
    sum(posts) as posts,
    sum(gets) as gets,
    sum(puts) as puts,
    sum(dels) as dels,
    sum(aoks) as aoks,
    sum(oops) as oops,
    sum(fups) as fups,
    sum(r_clients) as r_clients,
    sum(r_crypto) as r_crypto,
    sum(r_forms) as r_forms,
    sum(r_history) as r_history,
    sum(r_keys) as r_keys,
    sum(r_meta) as r_meta,
    sum(r_bookmarks) as r_bookmarks,
    sum(r_prefs) as r_prefs,
    sum(r_tabs) as r_tabs,
    sum(r_passwords) as r_passwords,
    sum(r_addons) as r_addons,
    sum(w_clients) as w_clients,
    sum(w_crypto) as w_crypto,
    sum(w_forms) as w_forms,
    sum(w_history) as w_history,
    sum(w_keys) as w_keys,
    sum(w_meta) as w_meta,
    sum(w_bookmarks) as w_bookmarks,
    sum(w_prefs) as w_prefs,
    sum(w_tabs) as w_tabs,
    sum(w_passwords) as w_passwords,
    sum(w_addons) as w_addons
  from tx group by uid, dev
'''
rolled_up = sqlContext.sql(sql_device_activity)
```

```python
# Store device activity rollups
sync_log_device_activity_s3base = "{}/sync_log_device_activity/v1".format(dest_s3_prefix)
sync_log_device_activity_s3path = "{}/day={}".format(sync_log_device_activity_s3base, target_day)

# TODO: Do we need to repartition?
rolled_up.repartition(5).write.parquet(sync_log_device_activity_s3path, mode="overwrite")
```

```python
def compute_device_counts(device_activity, target_day):
    device_activity.registerTempTable("device_activity")
    df = "%Y%m%d"
    last_week_date = dt.strptime(target_day, df) - timedelta(7)
    last_week = dt.strftime(last_week_date, df)
    sql_device_counts = """
        select
          uid,
          count(distinct dev) as devs
        from
          (select
            uid,
            dev
          from device_activity
          where uid in
            (select distinct(uid) from device_activity where day = '{}')
            and day > '{}'
            and day <= '{}')
        group by uid
    """.format(target_day, last_week, target_day)

    return sqlContext.sql(sql_device_counts)
```

```python
# Compute and store device counts

# Re-read device activity data from S3 so we can look at historic info
device_activity = sqlContext.read.parquet(sync_log_device_activity_s3base)

device_counts = compute_device_counts(device_activity, target_day)

sync_log_device_counts_s3path = "{}/sync_log_device_counts/v1/day={}".format(dest_s3_prefix, target_day)
device_counts.repartition(1).write.parquet(sync_log_device_counts_s3path, mode="overwrite")
```
