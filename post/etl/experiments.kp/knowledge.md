---
title: Experiment Job
authors:
- Frank Bertsch
tags:
- experiment
- firefox
created_at: 2017-02-01 00:00:00
updated_at: 2017-02-09 12:39:55.049642
tldr: 'We take all the pings from yesterday, get the information about any experiments:
  those that started, those running, and those that ended. These are aggregated by
  channel and outputted to files in s3.'
---

```python
from datetime import datetime as dt, timedelta, date
import moztelemetry
from os import environ

# get the desired target date from the environment, or run
# on 'yesterday' by default.
yesterday = dt.strftime(dt.utcnow() - timedelta(1), "%Y%m%d")
target_date = environ.get('date', yesterday)
```

```python
from moztelemetry.dataset import Dataset

sample_rate = environ.get('sample', 1)
pings = Dataset.from_source("telemetry-experiments") \
                   .where(submissionDate=target_date) \
                   .where(docType="main") \
                   .records(sc, sample=sample_rate) \
                   .filter(lambda x: x.get("environment", {}).get("build", {}).get("applicationName") == "Firefox")
```

```python
from moztelemetry import get_pings_properties

subset = get_pings_properties(pings, {
    "appUpdateChannel": "meta/appUpdateChannel",
    "log": "payload/log",
    "activeExperiment": "environment/addons/activeExperiment/id",
    "activeExperimentBranch": "environment/addons/activeExperiment/branch"
})
```

```python
from collections import defaultdict
from copy import deepcopy

### Setup data structures and constants ###

ALLOWED_ENTRY_TYPES = ('EXPERIMENT_ACTIVATION', 'EXPERIMENT_TERMINATION')

experiment = {
    'EXPERIMENT_ACTIVATION': defaultdict(int), 
    'active': defaultdict(int), 
    'EXPERIMENT_TERMINATION': defaultdict(int)
}

channel = { 
    'errors': [], 
    'experiments': {}
}

def get_empty_channel():
    return deepcopy(channel)
```

```python
import gzip
import ujson
import requests

# This is a json object with {Date => {channel: count}}. It is created
# by the main_channel_counts plugin, and may be inaccurate if the ec2
# box crashed, but only for the day of the crash. If it crashes, the
# previous data will be lost.
COUNTS_JSON_URI = "https://pipeline-cep.prod.mozaws.net/dashboard_output/analysis.frank.main_channel_counts.counts.json"

### Aggregation functions, Spark job, output file creation ###

def channel_ping_agg(channel_agg, ping):
    """Aggregate a channel with a ping"""
    try:
        for item in (ping.get("log") or []):
            if item[0] in ALLOWED_ENTRY_TYPES:
                entry, _, reason, exp_id = item[:4]
                data = item[4:]
                if exp_id not in channel_agg['experiments']:
                    channel_agg['experiments'][exp_id] = deepcopy(experiment)
                channel_agg['experiments'][exp_id][entry][tuple([reason] + data)] += 1

        exp_id = ping.get("activeExperiment")
        branch = ping.get("activeExperimentBranch")
        if exp_id is not None and branch is not None:
            if exp_id not in channel_agg['experiments']:
                channel_agg['experiments'][exp_id] = deepcopy(experiment)
            channel_agg['experiments'][exp_id]['active'][branch] += 1
    except Exception as e:
        channel_agg['errors'].append('{}: {}'.format(e.__class__, str(e)))
    
    return channel_agg

def channel_channel_agg(channel_agg_1, channel_agg_2):
    """Aggregate a channel with a channel"""
    channel_agg_1['errors'] += channel_agg_2['errors']
    
    for exp_id, exp in channel_agg_2['experiments'].iteritems():
        if exp_id not in channel_agg_1['experiments']:
            channel_agg_1['experiments'][exp_id] = deepcopy(experiment)
        for entry, exp_activities in exp.iteritems():
            for exp_activity, counts in exp_activities.iteritems():
                channel_agg_1['experiments'][exp_id][entry][exp_activity] += counts
            
    return channel_agg_1

def get_channel_or_other(ping):
    channel = ping.get("appUpdateChannel")
    if channel in ("release", "nightly", "beta", "aurora"):
        return channel
    return "OTHER"

def aggregate_pings(pings):
    """Get the channel experiments from an rdd of pings"""
    return pings\
            .map(lambda x: (get_channel_or_other(x), x))\
            .aggregateByKey(get_empty_channel(), channel_ping_agg, channel_channel_agg)


def add_counts(result):
    """Add counts from a running CEP"""
    counts = requests.get(COUNTS_JSON_URI).json()
    
    for cname, channel in result:
        channel['total'] = counts.get(target_date, {}).get(cname, None)
        
    return result

def write_aggregate(agg, date, filename_prefix='experiments'):
    filenames = []
    
    for cname, channel in agg:
        d = {
            "total": channel['total'],
            "experiments": {}
        }
        for exp_id, experiment in channel['experiments'].iteritems():
            d["experiments"][exp_id] = {
                "active": experiment['active'],
                "activations": experiment['EXPERIMENT_ACTIVATION'].items(),
                "terminations": experiment['EXPERIMENT_TERMINATION'].items() 
            }
            
        filename = "{}{}-{}.json.gz".format(filename_prefix, date, cname)
        filenames.append(filename)
        
        with gzip.open(filename, "wb") as fd:
            ujson.dump(d, fd)
        
    return filenames
```

```python
### Setup Test Pings ###

def make_ping(ae, aeb, chan, log):
    return {'activeExperiment': ae,
             'activeExperimentBranch': aeb,
             'appUpdateChannel': chan,
             'log': log}

NUM_ACTIVATIONS = 5
NUM_ACTIVES = 7
NUM_TERMINATIONS = 3
TOTAL = NUM_ACTIVATIONS + NUM_ACTIVES + NUM_TERMINATIONS

_channel, exp_id, the_date = 'release', 'tls13-compat-ff51@experiments.mozilla.org', '20140101'
branch, reason, data = 'branch', 'REJECTED', ['minBuildId']
log = [17786, reason, exp_id] + data

pings = [make_ping(exp_id, branch, _channel, []) 
             for i in xrange(NUM_ACTIVES)] +\
        [make_ping(exp_id, branch, _channel, [['EXPERIMENT_ACTIVATION'] + log]) 
             for i in xrange(NUM_ACTIVATIONS)] +\
        [make_ping(exp_id, branch, _channel, [['EXPERIMENT_TERMINATION'] + log]) 
             for i in xrange(NUM_TERMINATIONS)]

### Setup expected result aggregate ###

def channels_agg_assert(channels, counts=1):
    #Should just be the channel we provided
    assert channels.viewkeys() == set([_channel]), 'Incorrect channels: ' + ','.join(channels.keys())

    #just check this one channel now
    release = channels[_channel]
    assert len(release['errors']) == 0, 'Had Errors: ' + ','.join(release['errors'])

    #now check experiment totals
    assert release['experiments'][exp_id]['EXPERIMENT_ACTIVATION'][tuple([reason] + data)] == NUM_ACTIVATIONS * counts,\
            'Expected ' + str(NUM_ACTIVATIONS * counts) + \
            ', Got ' + str(release['experiments'][exp_id]['EXPERIMENT_ACTIVATION'][tuple([reason] + data)])
    assert release['experiments'][exp_id]['EXPERIMENT_TERMINATION'][tuple([reason] + data)] == NUM_TERMINATIONS * counts,\
            'Expected ' + str(NUM_TERMINATIONS * counts) + \
            ', Got ' + str(release['experiments'][exp_id]['EXPERIMENT_TERMINATION'][tuple([reason] + data)])

    #`active` is counted for both just active, and for activations and terminations above
    assert release['experiments'][exp_id]['active'][branch] == TOTAL * counts,\
            'Expected ' + str(TOTAL * counts) +\
            'Got ' + str(release['experiments'][exp_id]['active'][branch])
    

### Test non-spark - easier debugging ###

channel_1, channel_2 = get_empty_channel(), get_empty_channel()
for ping in pings:
    channel_1 = channel_ping_agg(channel_1, ping)
    channel_2 = channel_ping_agg(channel_2, ping)

# no actual key-value reduce, so just have to add the channel as key
res_chan = ((_channel, channel_channel_agg(channel_1, channel_2)),)
res_chan = add_counts(res_chan)

# we've agggregated over the pings twice, so counts=2
channels_agg_assert({channel: agg for channel, agg in res_chan}, counts=2)

write_aggregate(res_chan, the_date, filename_prefix="nonspark_test")


#### Test Spark ###
res = aggregate_pings(sc.parallelize(pings)).collect()
res = add_counts(res)

channels = {channel: agg for channel, agg in res}

channels_agg_assert(channels, counts=1)

write_aggregate(res, the_date, filename_prefix="spark_test")
```




    ['spark_test20140101-release.json.gz']




```python
### Run on actual data - use CEP to get counts ###

result = aggregate_pings(subset).collect()
result = add_counts(result)
```

```python
### Upload target day's data files ###

import boto3
import botocore
from boto3.s3.transfer import S3Transfer

output_files = write_aggregate(result, target_date)

data_bucket = "telemetry-public-analysis-2"
s3path = "experiments/data"
gz_csv_args = {'ContentEncoding': 'gzip', 'ContentType': 'text/csv'}

client = boto3.client('s3', 'us-west-2')
transfer = S3Transfer(client)

for output_file in output_files:
    transfer.upload_file(
        output_file, 
        data_bucket, 
        "{}/{}".format(s3path, output_file),
        extra_args=gz_csv_args
    )
```
