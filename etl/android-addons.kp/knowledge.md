---
title: Android Addons ETL job
authors:
- Frank Bertsch
tags:
- mobile
- etl
created_at: 2017-02-17 00:00:00
updated_at: 2017-02-17 15:23:54.090332
tldr: This job takes the Fennec saved session pings and maps them to just client,
  submissionDate, activeAddons, and persona.
---

```python
import datetime as dt
import os
import pandas as pd
import operator
import ujson as json
from pyspark.sql.types import *

from moztelemetry import get_pings, get_pings_properties, get_one_ping_per_client

%pylab inline
```
Take the set of pings, make sure we have actual clientIds and remove duplicate pings.


```python
def safe_str(obj):
    """ return the byte string representation of obj """
    if obj is None:
        return unicode("")
    return unicode(obj)

def dedupe_pings(rdd):
    return rdd.filter(lambda p: p["meta/clientId"] is not None)\
              .map(lambda p: (p["meta/documentId"], p))\
              .reduceByKey(lambda x, y: x)\
              .map(lambda x: x[1])

def dedupe_addons(rdd):
    return rdd.map(lambda p: (p[0] + safe_str(p[2]) + safe_str(p[3]), p))\
              .reduceByKey(lambda x, y: x)\
              .map(lambda x: x[1])
```
We're going to dump each event from the pings. Do a little empty data sanitization so we don't get NoneType errors during the dump. We create a JSON array of active experiments as part of the dump.


```python
def clean(s):
    try:
        s = s.decode("ascii").strip()
        return s if len(s) > 0 else None
    except:
        return None

def transform(ping):    
    output = []

    # These should not be None since we filter those out & ingestion process adds the data
    clientId = ping["meta/clientId"]
    submissionDate = dt.datetime.strptime(ping["meta/submissionDate"], "%Y%m%d")

    addonset = {}
    addons = ping["environment/addons/activeAddons"]
    if addons is not None:
        for addon, desc in addons.iteritems():
            name = clean(desc.get("name", None))
            if name is not None:
                addonset[name] = 1

    persona = ping["environment/addons/persona"]

    if len(addonset) > 0 or persona is not None:
        addonarray = None
        if len(addonset) > 0:
            addonarray = json.dumps(addonset.keys())
        output.append([clientId, submissionDate, addonarray, persona])

    return output

```
Create a set of events from "saved-session" UI telemetry. Output the data to CSV or Parquet.

This script is designed to loop over a range of days and output a single day for the given channels. Use explicit date ranges for backfilling, or now() - '1day' for automated runs.


```python
channels = ["nightly", "aurora", "beta", "release"]

batch_date = os.environ.get('date')
if batch_date:
    start = end = dt.datetime.strptime(batch_date, '%Y%m%d')
else:
    start = start = dt.datetime.now() - dt.timedelta(1)

day = start
while day <= end:
    for channel in channels:
        print "\nchannel: " + channel + ", date: " + day.strftime("%Y%m%d")

        pings = get_pings(sc, app="Fennec", channel=channel,
                          submission_date=(day.strftime("%Y%m%d"), day.strftime("%Y%m%d")),
                          build_id=("20100101000000", "99999999999999"),
                          fraction=1)

        subset = get_pings_properties(pings, ["meta/clientId",
                                              "meta/documentId",
                                              "meta/submissionDate",
                                              "environment/addons/activeAddons",
                                              "environment/addons/persona"])

        subset = dedupe_pings(subset)
        print subset.first()

        rawAddons = subset.flatMap(transform)
        print "\nrawAddons count: " + str(rawAddons.count())
        print rawAddons.first()

        uniqueAddons = dedupe_addons(rawAddons)
        print "\nuniqueAddons count: " + str(uniqueAddons.count())
        print uniqueAddons.first()

        s3_output = "s3n://net-mozaws-prod-us-west-2-pipeline-analysis/mobile/android_addons"
        s3_output += "/v1/channel=" + channel + "/submission=" + day.strftime("%Y%m%d") 
        schema = StructType([
            StructField("clientid", StringType(), False),
            StructField("submissiondate", TimestampType(), False),
            StructField("addons", StringType(), True),
            StructField("lwt", StringType(), True)
        ])
        grouped = sqlContext.createDataFrame(uniqueAddons, schema)
        grouped.coalesce(1).write.parquet(s3_output, mode="overwrite")

    day += dt.timedelta(1)

```
