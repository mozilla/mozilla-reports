---
title: Cliqz Profile Daily
authors:
- Ryan Harter (:harter)
tags:
- Spark
- ATMO
- ETL
created_at: 2017-03-08 00:00:00
updated_at: 2017-03-08 12:09:05.593538
tldr: Populates cliqz_profile_daily
---
```python
sc.cancelAllJobs()
```
## Load Test Pilot Data


```python
sqlContext.read.parquet("s3://telemetry-parquet/harter/cliqz_testpilot/v1/").createOrReplaceTempView('cliqz_testpilot')
sqlContext.read.parquet("s3://telemetry-parquet/harter/cliqz_testpilottest/v1/").createOrReplaceTempView('cliqz_testpilottest')
```

```python
txp_min_query = """
SELECT tp.client_id, min(date) as min_date
FROM cliqz_testpilot tp
JOIN cliqz_testpilottest tpt
ON tpt.client_id = tp.client_id
GROUP BY 1
"""

txp_min = sqlContext.sql(txp_min_query)

txp_query = """
SELECT 
    tp.client_id,
    tpt.cliqz_client_id,
    tp.submission as submission_date,
    tp.cliqz_version,
    tp.has_addon,
    tp.cliqz_version,
    tpt.event,
    tp.event as tp_event,
    tpt.content_search_engine
FROM cliqz_testpilot tp
JOIN cliqz_testpilottest tpt
ON tpt.client_id = tp.client_id
AND tpt.submission == tp.submission
"""
txp = sqlContext.sql(txp_query)
```
## Load Main Summary data with HBase


```python
client_ids = txp_min.rdd.map(lambda x: str(x.client_id)).distinct().collect()

import uuid
def filter_client_ids(client_id):
    try:
        uuid.UUID(client_id)
    except:
        return False
    
    return True

clean_clients = filter(filter_client_ids, client_ids)
print len(clean_clients)
print len(set(clean_clients))
```
    9844
    9844



```python
from datetime import date
def filter_ms_payload(row):
    fields = [
        'submission_date',
        'normalized_channel',
        'os',
        'is_default_browser',
        'subsession_length',
        'default_search_engine',
        'search_counts',
    ]
    
    addons = map(lambda x: x['addon_id'],
                 row.get('active_addons', []))

    return dict(zip(fields, [row.get(ff) for ff in fields]) +
                [("has_addon", "testpilot@cliqz.com" in addons)])

from moztelemetry.hbase import HBaseMainSummaryView
view = HBaseMainSummaryView()
def read_ms_data(clients):
    # This function has difficulty handling more than ~500 clients
    # see https://gist.github.com/harterrt/cf0f3812d28f6d4d5cafacfba3308f19
    return view.get_range(sc, clients,
                       range_start=date(2017,1,1),
                       range_end=date.today(), limit=180)\
        .map(lambda (k, v): (k, map(filter_ms_payload, v)))

def paginate(seq, slice_len):
    # Split a list into a list of lists with length slice_len
    for ii in xrange(0, len(seq), slice_len):
        yield seq[ii:ii+slice_len]

def get_all_ms_data(client_ids):
    # Paginate client_ids and pull data
    groups = paginate(client_ids, 250)
    sharded_data = map(lambda cc: read_ms_data(cc).collect(), groups)
    
    return sc.parallelize(sharded_data).flatMap(lambda x: x)
```

```python
ms_list = get_all_ms_data(clean_clients)
ms_list.count()
```




    9844



## Filter to two week window of main summary


```python
from datetime import datetime, timedelta
def filter_and_flatten(row):
    """Filter ms_array to rows from no earlier than 2 weeks before expt start
    
    row: (client_id, (txp_min(client_id, min_date),
                      [ms_row_dicts]))
    
    returns: filtered dicts from main_summary (including client_id)
    """
    
    min_date = datetime.strptime(row[1][0].min_date, "%Y%m%d")
    def is_ms_row_recent(ms_row):
        try:
            submission_date = datetime.strptime(ms_row['submission_date'], "%Y%m%d")
            return (min_date - submission_date) <= timedelta(14)
        except:
            return False
    
    filtered = filter(is_ms_row_recent, row[1][1])
    
    # Add the client_id to the filtered rows:
    return map(lambda ms_dict: dict(ms_dict.items() + [('client_id', row[0])]),
               filtered)

filtered_ms = txp_min.rdd.map(lambda x: (x.client_id, x))\
    .join(ms_list).flatMap(filter_and_flatten)
```

```python
filtered_ms.map(lambda x: x['client_id']).distinct().count()
```




    9735



## Aggregate

This aggregation is pretty messy. 
We effectively take an arbitrary value for anything not included in the Counter object.


```python
from collections import Counter, namedtuple

AggRow = namedtuple("AggRow", ['raw_row', 'agg_field'])

def agg_func(x, y):
    print x
    return x[0], x[1] + y[1]

def prep_ms_agg(row):
    def parse_search_counts(search_counts):
        if search_counts is not None:
            return Counter({(xx['engine'] + "-" + xx['source']): xx['count'] for xx in search_counts})
        else:
            return Counter()

    return ((row['client_id'], row['submission_date']),
        AggRow(
            raw_row = row,
            agg_field = Counter({
                "is_default_browser_counter": Counter([row['is_default_browser']]),
                "session_hours": float(row['subsession_length'] if row['subsession_length'] else 0)/3600,
                "search_counts": parse_search_counts(row['search_counts']),
                "has_addon": row['has_addon']
            })
        )
    )

def prep_txp_agg(row):
    return ((row.client_id, row.submission_date),
        AggRow(
            raw_row = row,
            agg_field = Counter({
                "cliqz_enabled": int(row.tp_event == "enabled"),
                "cliqz_enabled": int(row.tp_event == "disabled"),
                "test_enabled": int(row.event == "cliqzEnabled"),
                "test_disabled": int(row.event == "cliqzDisabled"),
                "test_installed": int(row.event == "cliqzInstalled"),
                "test_uninstalled": int(row.event == "cliqzUninstalled")
            })
        )
    )
```

```python
agg_ms = filtered_ms.map(prep_ms_agg).reduceByKey(agg_func)
```

```python
#agg_ms.take(10)
```

```python
agg_txp = txp.rdd.map(prep_txp_agg).reduceByKey(agg_func)
```

```python
#agg_txp.take(10)
```
## Join aggregated tables


```python
joined = agg_ms.fullOuterJoin(agg_txp)
```

```python
from pyspark.sql import Row
profile_daily = Row('client_id', 'cliqz_client_id', 'date', 'has_cliqz',
                    'cliqz_version', 'channel', 'os', 'is_default_browser',
                    'session_hours', 'search_default', 'search_counts',
                    'cliqz_enabled', 'cliqz_disabled', 'test_enabled',
                    'test_disabled', 'test_installed', 'test_uninstalled')

def option(value):
    return lambda func: func(value) if value is not None else None

def format_row(row):
    print(row)
    key = row[0]
    value = row[1]
    
    # Unfortunately, the named tuple labels aren't preserved in spark, 
    # unpacking the merged values:
    main_summary = option(value[0][0] if value[0] is not None else None)
    ms_agg = option(value[0][1] if value[0] is not None else None)
    testpilot = option(value[1][0] if value[1] is not None else None)
    txp_agg = option(value[1][1] if value[1] is not None else None)

    search_counts = ms_agg(lambda x:x['search_counts'])
    
    return Row(
        client_id = key[0],
        cliqz_client_id = testpilot(lambda x: x.cliqz_client_id),
        date = key[1],
        has_cliqz = ms_agg(lambda x: bool(x['has_addon'])),
        cliqz_version = testpilot(lambda x: x.cliqz_version),
        channel = main_summary(lambda x: x['normalized_channel']),
        os = main_summary(lambda x: x['os']),
        is_default_browser = ms_agg(lambda x: bool(x['is_default_browser_counter'].most_common()[0][0])),
        session_hours = ms_agg(lambda x: x['session_hours']),
        search_default = main_summary(lambda x: x['default_search_engine']),
        search_counts = dict(search_counts) if search_counts is not None else {},
        cliqz_enabled = txp_agg(lambda x: x['cliqz_enabled']),
        cliqz_disabled = txp_agg(lambda x: x['cliqz_enabled']),
        test_enabled = txp_agg(lambda x: x['test_enabled']),
        test_disabled = txp_agg(lambda x: x['test_disabled']),
        test_installed = txp_agg(lambda x: x['test_installed']),
        test_uninstalled = txp_agg(lambda x: x['test_uninstalled'])
    )
```

```python
final = joined.map(format_row)
```

```python
#ff = final.collect()
```

```python
#len(ff)
#ff[:10]
```

```python
# sqlContext.createDataFrame(final)
```

```python
#txp.filter("submission_date = 20170211").count()
```

```python
#agg_txp.count()
```

```python
#agg_ms.count()
```

```python
#agg_ms.map(lambda x: x[1][0]['client_id']).distinct().count()
```

```python
#agg_txp.count() + agg_ms.count() - final.count() 
```

```python
local_final = sqlContext.createDataFrame(final).repartition(1).write.mode("overwrite")\
    .parquet("s3n://telemetry-parquet/harter/cliqz_profile_daily/v1/")
```

```python

```
