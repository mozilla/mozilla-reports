---
title: Containers Testpilot Pipeline
authors:
- Ryan Harter (:harter)
tags:
- Spark
- ATMO
- ETL
created_at: 2017-03-08 00:00:00
updated_at: 2017-03-08 12:10:58.441694
tldr: Populates containers_testpilottest
---
```python
# %load ~/cliqz_ping_pipeline/transform.py
import ujson as json
from datetime import *
import pandas as pd
from pyspark.sql.types import *
from pyspark.sql.functions import split
import base64
from Crypto.Cipher import AES

from moztelemetry import get_pings_properties
from moztelemetry.dataset import Dataset

class ColumnConfig:
    def __init__(self, name, path, cleaning_func, struct_type):
        self.name = name
        self.path = path
        self.cleaning_func = cleaning_func
        self.struct_type = struct_type

class DataFrameConfig:
    def __init__(self, col_configs, ping_filter):
        self.columns = [ColumnConfig(*col) for col in col_configs]
        self.ping_filter = ping_filter

    def toStructType(self):
        return StructType(map(
            lambda col: StructField(col.name, col.struct_type, True),
            self.columns))

    def get_names(self):
        return map(lambda col: col.name, self.columns)

    def get_paths(self):
        return map(lambda col: col.path, self.columns)


def pings_to_df(sqlContext, pings, data_frame_config):
    """Performs simple data pipelining on raw pings

    Arguments:
        data_frame_config: a list of tuples of the form:
                 (name, path, cleaning_func, column_type)
    """
    filtered_pings = get_pings_properties(pings, data_frame_config.get_paths())\
        .filter(data_frame_config.ping_filter)

    return config_to_df(sqlContext, filtered_pings, data_frame_config)

def config_to_df(sqlContext, raw_data, data_frame_config):
    """Performs simple data pipelining on raw pings

    Arguments:
        data_frame_config: a list of tuples of the form:
                 (name, path, cleaning_func, column_type)
    """
    def build_cell(ping, column_config):
        """Takes a json ping and a column config and returns a cleaned cell"""
        raw_value = ping[column_config.path]
        func = column_config.cleaning_func
        if func is not None:
            return func(raw_value)
        else:
            return raw_value

    def ping_to_row(ping):
        return [build_cell(ping, col) for col in data_frame_config.columns]

    return sqlContext.createDataFrame(
        raw_data.map(ping_to_row).collect(),
        schema = data_frame_config.toStructType())


```

```python
def save_df(df, name, date_partition, partitions=1):
    if date_partition is not None:
        partition_str = "/submission_date={day}".format(day=date_partition)
    else:
        partition_str=""

    # TODO: this name should include the experiment name
    path_fmt = "s3n://telemetry-parquet/harter/containers_{name}/v1{partition_str}"
    path = path_fmt.format(name=name, partition_str=partition_str)
    df.repartition(partitions).write.mode("overwrite").parquet(path)

def __main__(sc, sqlContext, day=None, save=True):
    if day is None:
        # Set day to yesterday
        day = (date.today() - timedelta(1)).strftime("%Y%m%d")

    get_doctype_pings = lambda docType: Dataset.from_source("telemetry") \
        .where(docType=docType) \
        .where(submissionDate=day) \
        .where(appName="Firefox") \
        .records(sc)

    testpilottest_df = pings_to_df(
        sqlContext,
        get_doctype_pings("testpilottest"),
        DataFrameConfig(
            [
                ("uuid", "payload/payload/uuid", None, StringType()),
                ("userContextId", "payload/payload/userContextId", None, LongType()),
                ("clickedContainerTabCount", "payload/payload/clickedContainerTabCount", None, LongType()),
                ("eventSource", "payload/payload/eventSource", None, StringType()),
                ("event", "payload/payload/event", None, StringType()),
                ("hiddenContainersCount", "payload/payload/hiddenContainersCount", None, LongType()),
                ("shownContainersCount", "payload/payload/shownContainersCount", None, LongType()),
                ("totalContainersCount", "payload/payload/totalContainersCount", None, LongType()),
                ("totalContainerTabsCount", "payload/payload/totalContainerTabsCount", None, LongType()),
                ("totalNonContainerTabsCount", "payload/payload/totalNonContainerTabsCount", None, LongType()),
                ("test", "payload/test", None, StringType()),
            ],
            lambda ping: ping['payload/test'] == "@testpilot-containers"
        )
    )

    if save:
        save_df(testpilottest_df, "testpilottest", day, partitions=1)

    return testpilottest_df

```

```python
tpt = __main__(sc, sqlContext)
```

```python
tpt.take(2)
```

```python

```
