---
title: Android Clients ETL
authors:
- Frank Bertsch
tags:
- mobile
- fennec
- etl
created_at: 2017-02-09 00:00:00
updated_at: 2017-02-13 07:54:47.110346
tldr: You can write any markdown you want here (the '|' character makes this an escaped
  section)
---

```python
import datetime as dt
import os
import pandas as pd
import ujson as json
from pyspark.sql.types import *

from moztelemetry import get_pings, get_pings_properties

%pylab inline
```
Take the set of pings, make sure we have actual clientIds and remove duplicate pings. We collect each unique ping.


```python
def dedupe_pings(rdd):
    return rdd.filter(lambda p: p["meta/clientId"] is not None)\
              .map(lambda p: (p["meta/documentId"], p))\
              .reduceByKey(lambda x, y: x)\
              .map(lambda x: x[1])

```
Transform and sanitize the pings into arrays.


```python
def transform(ping):
    # Should not be None since we filter those out.
    clientId = ping["meta/clientId"]

    profileDate = None
    profileDaynum = ping["environment/profile/creationDate"]
    if profileDaynum is not None:
        try:
            # Bad data could push profileDaynum > 32767 (size of a C int) and throw exception
            profileDate = dt.datetime(1970, 1, 1) + dt.timedelta(int(profileDaynum))
        except:
            profileDate = None

    # Create date should already be in ISO format
    creationDate = ping["creationDate"]
    if creationDate is not None:
        # This is only accurate because we know the creation date is always in 'Z' (zulu) time.
        creationDate = dt.datetime.strptime(ping["creationDate"], "%Y-%m-%dT%H:%M:%S.%fZ")

    # Added via the ingestion process so should not be None.
    submissionDate = dt.datetime.strptime(ping["meta/submissionDate"], "%Y%m%d")

    appVersion = ping["application/version"]
    osVersion = ping["environment/system/os/version"]
    if osVersion is not None:
        osVersion = int(osVersion)
    locale = ping["environment/settings/locale"]
    
    # Truncate to 32 characters
    defaultSearch = ping["environment/settings/defaultSearchEngine"]
    if defaultSearch is not None:
        defaultSearch = defaultSearch[0:32]

    # Build up the device string, truncating like we do in 'core' ping.
    device = ping["environment/system/device/manufacturer"]
    model = ping["environment/system/device/model"]
    if device is not None and model is not None:
        device = device[0:12] + "-" + model[0:19]

    xpcomABI = ping["application/xpcomAbi"]
    arch = "arm"
    if xpcomABI is not None and "x86" in xpcomABI:
        arch = "x86"
        
    # Bug 1337896
    as_topsites_loader_time = ping["payload/histograms/FENNEC_ACTIVITY_STREAM_TOPSITES_LOADER_TIME_MS"]
    topsites_loader_time = ping["payload/histograms/FENNEC_TOPSITES_LOADER_TIME_MS"]
    
    if as_topsites_loader_time is not None:
        as_topsites_loader_time = map(int, as_topsites_loader_time.tolist())
    
    if topsites_loader_time is not None:
        topsites_loader_time = map(int, topsites_loader_time.tolist())

    return [clientId,
            profileDate,
            submissionDate,
            creationDate,
            appVersion,
            osVersion,
            locale,
            defaultSearch,
            device,
            arch,
            as_topsites_loader_time,
            topsites_loader_time]

```
Create a set of pings from "saved-session" to build a set of core client data. Output the data to CSV or Parquet.

This script is designed to loop over a range of days and output a single day for the given channels. Use explicit date ranges for backfilling, or now() - '1day' for automated runs.


```python
channels = ["nightly", "aurora", "beta", "release"]

batch_date = os.environ.get('date')
if batch_date:
    start = end = dt.datetime.strptime(batch_date, '%Y%m%d')
else:
    start = end = dt.datetime.now() - dt.timedelta(1)

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
                                              "creationDate",
                                              "application/version",
                                              "environment/system/os/version",
                                              "environment/profile/creationDate",
                                              "environment/settings/locale",
                                              "environment/settings/defaultSearchEngine",
                                              "environment/system/device/model",
                                              "environment/system/device/manufacturer",
                                              "application/xpcomAbi",
                                              "payload/histograms/FENNEC_ACTIVITY_STREAM_TOPSITES_LOADER_TIME_MS",
                                              "payload/histograms/FENNEC_TOPSITES_LOADER_TIME_MS"])

        subset = dedupe_pings(subset)
        transformed = subset.map(transform)

        s3_output = "s3n://telemetry-test-bucket/frank/mobile/android_clients"
        s3_output += "/v1/channel=" + channel + "/submission=" + day.strftime("%Y%m%d") 
        schema = StructType([
            StructField("clientid", StringType(), False),
            StructField("profiledate", TimestampType(), True),
            StructField("submissiondate", TimestampType(), False),
            StructField("creationdate", TimestampType(), True),
            StructField("appversion", StringType(), True),
            StructField("osversion", IntegerType(), True),
            StructField("locale", StringType(), True),
            StructField("defaultsearch", StringType(), True),
            StructField("device", StringType(), True),
            StructField("arch", StringType(), True),
            StructField("fennecActivityStreamTopsitesLoaderTimeMs", 
                        ArrayType(IntegerType()), 
                        True
            ),
            StructField("fennecTopsitesLoaderTimeMs", 
                        ArrayType(IntegerType()), 
                        True
            )
        ])
        grouped = sqlContext.createDataFrame(transformed, schema)
        grouped.coalesce(1).write.parquet(s3_output, mode="overwrite")

    day += dt.timedelta(1)

```
