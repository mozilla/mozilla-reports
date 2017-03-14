---
title: Nightly Hang Reporter Stacks
authors:
- mconley
- dthayer
tags:
- spark
- hangs
- null
created_at: 2017-03-02 00:00:00
updated_at: 2017-03-14 13:22:30.843000
tldr: Analysis for hang reporting dashboard.
---
As part of the Quantum Flow project, which seeks to make Firefox _feel_ faster, we'd like to be able to have a dashboard with various statistics on browser hangs. While we have the data in place in `threadHangStats`, we don't currently have any working visual representation of this data. This notebook is intended to process ping data into a format that can be easily consumed by a JS-powered dashboard on TMO.


```python
import os
import ujson as json
import pandas as pd
from datetime import datetime, timedelta

from moztelemetry import get_pings_properties
from moztelemetry.dataset import Dataset
```
Some configuration options:


```python
use_s3 = False
days_to_aggregate = 3
sample_size = 0.01
```
We'd like to have a roughly 1-month chart of the severity of various hangs over time.


```python
start_date = (datetime.today() - timedelta(days=days_to_aggregate))
start_date_str = start_date.strftime("%Y%m%d")
end_date = (datetime.today() - timedelta(days=0))
end_date_str = end_date.strftime("%Y%m%d")
```

```python
pings = Dataset.from_source("telemetry") \
    .where(docType='main') \
    .where(appBuildId=lambda b: (b.startswith(start_date_str) or b > start_date_str)
                                 and (b.startswith(end_date_str) or b < end_date_str)) \
    .where(appUpdateChannel="nightly") \
    .records(sc, sample=sample_size)
```

```python
properties = ["environment/system/os/name",
              "application/buildId",
              "payload/info/subsessionLength",
              "payload/childPayloads",
              "payload/threadHangStats"]

ping_props = get_pings_properties(pings, properties, with_processes=True)
```
We're currently only interested in Windows pings.


```python
def windows_only(p):
    return p["environment/system/os/name"] == "Windows_NT"

windows_pings_only = ping_props.filter(windows_only)
```
Split out content hangs from parent hangs. We need an additional loop with the content hangs due to multiple content processes.


```python
def only_hangs_of_type(ping, process_type):
    build_date = ping["application/buildId"][:8] # "YYYYMMDD" : 8 characters
    usage_seconds = float(ping['payload/info/subsessionLength'])
    
    if process_type == 'content':
        result = []
        if ping['payload/childPayloads'] is None:
            return result

        for payload in ping['payload/childPayloads']:
            if 'threadHangStats' not in payload:
                return result
            for thread_hang in payload['threadHangStats']:
                if 'name' not in thread_hang:
                    continue
                    
                if len(thread_hang['hangs']) > 0:
                    result = result + [{
                        'build_date': build_date,
                        'thread_name': thread_hang['name'],
                        'usage_seconds': usage_seconds,
                        'hang': x
                    } for x in thread_hang['hangs']]
                    
        return result
    else:
        result = []
        
        if 'payload/threadHangStats' not in ping:
            return result
            
        if ping['payload/threadHangStats'] is None:
            return result

        for thread_hang in ping['payload/threadHangStats']:
            if 'name' not in thread_hang:
                continue

            if len(thread_hang['hangs']) > 0:
                result = result + [{
                        'build_date': build_date,
                        'thread_name': thread_hang['name'],
                        'usage_seconds': usage_seconds,
                        'hang': x
                    } for x in thread_hang['hangs']]
                
        return result

def filter_for_hangs_of_type(pings, process_type):
    return pings.flatMap(lambda p: only_hangs_of_type(p, process_type))

content_hangs = filter_for_hangs_of_type(windows_pings_only, 'content')
parent_hangs = filter_for_hangs_of_type(windows_pings_only, 'parent')
```
Aggregate `hang_sum` (approximate total milliseconds for hangs greater than 100ms), and `hang_count` (approximate number of hangs greater than 100ms). This should give us some sense of both the frequency and the severity of various hangs.


```python
def map_to_hang_data(hang):
    hist_data = hang['hang']['histogram']['values']
    key_ints = map(int, hist_data.keys())
    hist = pd.Series(hist_data.values(), index=key_ints)
    weights = pd.Series(key_ints, index=key_ints)
    hang_sum = (hist * weights)[hist.index >= 100].sum()
    hang_count = hist[hist.index >= 100].sum()
    # our key will be the stack, the thread name, and the build ID. Once we've reduced on this
    # we'll collect as a map, since there should only be ~ 10^1 days, 10^1 threads, 10^3 stacks : 100,000 records
    return (tuple(hang['hang']['stack'] + [hang['thread_name'], hang['build_date']]), {
            'hang_sum': hang_sum,
            'hang_count': hang_count,
            'usage_seconds': hang['usage_seconds']
        })

def merge_hang_data(a, b):
    return {
        'hang_sum': a['hang_sum'] + b['hang_sum'],
        'hang_count': a['hang_count'] + b['hang_count'],
        'usage_seconds': a['usage_seconds'] + b['usage_seconds'],
    }

def get_grouped_sums_and_counts(hangs):
    return hangs.map(map_to_hang_data).reduceByKey(merge_hang_data).collectAsMap()

content_grouped_hangs = get_grouped_sums_and_counts(content_hangs)
parent_grouped_hangs = get_grouped_sums_and_counts(parent_hangs)
```
First group by date:


```python
def group_by_date(stacks):
    dates = {}
    for stack, stats in stacks.iteritems():
        hang_sum = stats['hang_sum']
        hang_count = stats['hang_count']
        usage_seconds = stats['usage_seconds']
        
        if len(stack) == 0:
            continue
        stack_date = stack[-1]
        stack = stack[:-1]
        if not stack_date in dates:
            dates[stack_date] = {
                "date": stack_date,
                "threads": [],
                "usage_seconds": 0
            }

        date = dates[stack_date]

        date["threads"].append((stack, {'hang_sum': hang_sum, 'hang_count': hang_count}))
        date["usage_seconds"] += usage_seconds

    return dates

content_by_date = group_by_date(content_grouped_hangs)
parent_by_date = group_by_date(parent_grouped_hangs)
```
Then by thread name:


```python
def group_by_thread_name(stacks):
    thread_names = {}
    for stack, stats in stacks:
        hang_sum = stats['hang_sum']
        hang_count = stats['hang_count']
        
        if len(stack) == 0:
            continue
        stack_thread_name = stack[-1]
        stack = stack[:-1]
        if not stack_thread_name in thread_names:
            thread_names[stack_thread_name] = {
                "thread": stack_thread_name,
                "hangs": [],
            }

        thread_name = thread_names[stack_thread_name]

        thread_name["hangs"].append((stack, {'hang_sum': hang_sum, 'hang_count': hang_count}))

    return thread_names
```
Then by the top frame, which will serve as the hang's signature for the time being.


```python
def group_by_top_frame(stacks):
    top_frames = {}
    for stack, stats in stacks:
        hang_sum = stats['hang_sum']
        hang_count = stats['hang_count']
        
        if len(stack) == 0:
            continue
        stack_top_frame = stack[-1]
        if not stack_top_frame in top_frames:
            top_frames[stack_top_frame] = {
                "frame": stack_top_frame,
                "stacks": [],
                "hang_sum": 0,
                "hang_count": 0
            }

        top_frame = top_frames[stack_top_frame]

        top_frame["stacks"].append((stack, {'hang_sum': hang_sum, 'hang_count': hang_count}))

        top_frame["hang_sum"] += hang_sum
        top_frame["hang_count"] += hang_count

    return top_frames
```
Normalize all our fields by total usage hours for that date.


```python
def score(grouping, usage_seconds):
    total_hours = usage_seconds / 60
    grouping['hang_ms_per_hour'] = grouping['hang_sum'] / total_hours
    grouping['hang_count_per_hour'] = grouping['hang_count'] / total_hours

    scored_stacks = []
    for stack_tuple in grouping['stacks']:
        stack_hang_sum = stack_tuple[1]['hang_sum'] / total_hours
        stack_hang_count = stack_tuple[1]['hang_count'] / total_hours
        scored_stacks.append((stack_tuple[0], {
                    'hang_ms_per_hour': stack_hang_sum,
                    'hang_count_per_hour': stack_hang_count
                }))
        
    grouping['stacks'] = scored_stacks
    return grouping

def score_all(grouped_by_top_frame, total_hours):
    return {k: score(g, total_hours) for k, g in grouped_by_top_frame.iteritems()}
```
Put the last three sections together:


```python
def get_by_top_frame_by_thread(by_thread, usage_seconds):
    return {k: score_all(group_by_top_frame(g["hangs"]), usage_seconds) for k, g in by_thread.iteritems()}

def get_by_thread_by_date(by_date):
    return {
        k: {
            'threads': get_by_top_frame_by_thread(group_by_thread_name(g["threads"]), g["usage_seconds"]),
            'total_hours': g["usage_seconds"] / 60
        } for k, g in by_date.iteritems()
    }

content_scored = get_by_thread_by_date(content_by_date)
parent_scored = get_by_thread_by_date(parent_by_date)
```

```python
import ujson as json

def write_file(name, stuff):
    filename = "./output/%s-%s.json" % (name, end_date_str)
    jsonblob = json.dumps(stuff, ensure_ascii=False)

    if use_s3:
        # TODO: This was adapted from another report. I'm not actually sure what the process is for
        # dumping stuff to s3, and would appreciate feedback!
        bucket = "telemetry-public-analysis-2"
        timestamped_s3_key = "bhr/data/hang_aggregates/" + name + ".json"
        client = boto3.client('s3', 'us-west-2')
        transfer = S3Transfer(client)
        transfer.upload_file(filename, bucket, timestamped_s3_key, extra_args={'ContentType':'application/json'})
    else:
        if not os.path.exists('./output'):
            os.makedirs('./output')
        with open(filename, 'w') as f:
            f.write(jsonblob)
```

```python
write_file('content_by_day', content_scored)
write_file('parent_by_day', parent_scored)
```
