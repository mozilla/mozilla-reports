---
title: Mobile Clients ETL Job
authors:
- Frank Bertsch
tags:
- mobile
- etl
created_at: 2017-02-17 00:00:00
updated_at: 2017-02-17 15:24:33.852490
tldr: This job basically just takes core pings and puts them in parquet format.
---

```python
import os
import datetime as dt
import pandas as pd
import ujson as json
from pyspark.sql.types import *

from moztelemetry import get_pings, get_pings_properties

%pylab inline
```

```python

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

    # Added via the ingestion process so should not be None.
    submissionDate = dt.datetime.strptime(ping["meta/submissionDate"], "%Y%m%d")
    geoCountry = ping["meta/geoCountry"]

    profileDate = None
    profileDaynum = ping["profileDate"]
    if profileDaynum is not None:
        try:
            # Bad data could push profileDaynum > 32767 (size of a C int) and throw exception
            profileDate = dt.datetime(1970, 1, 1) + dt.timedelta(int(profileDaynum))
        except:
            profileDate = None

    # Create date can be an improper string (~.03% of the time, so ignore)
    # Year can be < 2000 (~.005% of the time, so ignore)
    try: 
        # Create date should already be in ISO format
        creationDate = ping["created"]
        if creationDate is not None:
            # This is only accurate because we know the creation date is always in 'Z' (zulu) time.
            creationDate = dt.datetime.strptime(ping["created"], "%Y-%m-%d")
            if creationDate.year < 2000:
                creationDate = None
    except ValueError:
        creationDate = None

    appVersion = ping["meta/appVersion"]
    buildId = ping["meta/appBuildId"]
    locale = ping["locale"]
    os = ping["os"]
    osVersion = ping["osversion"]
    device = ping["device"]
    arch = ping["arch"]
    defaultSearch = ping["defaultSearch"]
    distributionId = ping["distributionId"]

    experiments = ping["experiments"]
    if experiments is None:
        experiments = []
        
    #bug 1315028
    defaultNewTabExperience = ping["defaultNewTabExperience"]
    defaultMailClient = ping["defaultMailClient"]

    #bug 1307419
    searches = ping["searches"]
    durations = ping["durations"]
    sessions = ping["sessions"]
    
    return [clientId, submissionDate, creationDate, profileDate, geoCountry, locale, os,
            osVersion, buildId, appVersion, device, arch, defaultSearch, distributionId,
            json.dumps(experiments), defaultNewTabExperience, defaultMailClient, searches,
            durations, sessions]
```
Create a set of pings from "core" to build a set of core client data. Output the data to CSV or Parquet.

This script is designed to loop over a range of days and output a single day for the given channels. Use explicit date ranges for backfilling, or now() - '1day' for automated runs.


```python
channels = ["nightly", "aurora", "beta", "release"]

batch_date = os.environ.get('date')
if batch_date:
    start = end = dt.datetime.strptime(batch_date, '%Y%m%d')
else:
    start = dt.datetime.now() - dt.timedelta(1)
    end = dt.datetime.now() - dt.timedelta(1)



day = start
while day <= end:
    for channel in channels:
        print "\nchannel: " + channel + ", date: " + day.strftime("%Y%m%d")

        kwargs = dict(
            doc_type="core",
            submission_date=(day.strftime("%Y%m%d"), day.strftime("%Y%m%d")),
            channel=channel,
            app="Fennec",
            fraction=1
        )

        # Grab all available source_version pings
        pings = get_pings(sc, source_version="*", **kwargs)

        subset = get_pings_properties(pings, ["meta/clientId",
                                              "meta/documentId",
                                              "meta/submissionDate",
                                              "meta/appVersion",
                                              "meta/appBuildId",
                                              "meta/geoCountry",
                                              "locale",
                                              "os",
                                              "osversion",
                                              "device",
                                              "arch",
                                              "profileDate",
                                              "created",
                                              "defaultSearch",
                                              "distributionId",
                                              "experiments",
                                              "defaultNewTabExperience",
                                              "defaultMailClient",
                                              "searches",
                                              "durations",
                                              "sessions"])

        subset = dedupe_pings(subset)
        print "\nDe-duped pings:" + str(subset.count())
        print subset.first()

        transformed = subset.map(transform)
        print "\nTransformed pings:" + str(transformed.count())
        print transformed.first()

        s3_output = "s3n://net-mozaws-prod-us-west-2-pipeline-analysis/mobile/mobile_clients"
        s3_output += "/v1/channel=" + channel + "/submission=" + day.strftime("%Y%m%d") 
        schema = StructType([
            StructField("clientid", StringType(), False),
            StructField("submissiondate", TimestampType(), False),
            StructField("creationdate", TimestampType(), True),
            StructField("profiledate", TimestampType(), True),
            StructField("geocountry", StringType(), True),
            StructField("locale", StringType(), True),
            StructField("os", StringType(), True),
            StructField("osversion", StringType(), True),
            StructField("buildid", StringType(), True),
            StructField("appversion", StringType(), True),
            StructField("device", StringType(), True),
            StructField("arch", StringType(), True),
            StructField("defaultsearch", StringType(), True),
            StructField("distributionid", StringType(), True),
            StructField("experiments", StringType(), True),
            StructField("defaultNewTabExperience", StringType(), True),
            StructField("defaultMailClient", StringType(), True),
            StructField("searches", StringType(), True),
            StructField("durations", StringType(), True),
            StructField("sessions", StringType(), True)
        ])
        # Make parquet parition file size large, but not too large for s3 to handle
        coalesce = 1
        if channel == "release":
            coalesce = 4
        grouped = sqlContext.createDataFrame(transformed, schema)
        grouped.coalesce(coalesce).write.mode('overwrite').parquet(s3_output)

    day += dt.timedelta(1)

```
