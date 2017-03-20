---
title: TxP Snoozetabs ETL
authors:
- sunahsuh
tags:
- testpilot
- etl
created_at: 2017-02-17 00:00:00
updated_at: 2017-03-20 12:24:36.935571
tldr: This notebook transforms pings from the SnoozeTabs testpilot test to a parquet
  dataset. Docs at https://github.com/bwinton/SnoozeTabs/blob/master/docs/metrics.md
---
```python
from datetime import *
import dateutil.parser
from pyspark.sql.types import *
import boto3

from moztelemetry import get_pings_properties
from moztelemetry.dataset import Dataset


class ColumnConfig:
    def __init__(self, name, path, cleaning_func, struct_type):
        self.name = name
        self.path = path
        self.cleaning_func = cleaning_func
        self.struct_type = struct_type

class DataFrameConfig:
    def __init__(self, col_configs):
        self.columns = [ColumnConfig(*col) for col in col_configs]

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

    filtered_pings = get_pings_properties(pings, data_frame_config.get_paths())

    return sqlContext.createDataFrame(
        filtered_pings.map(ping_to_row),
        schema = data_frame_config.toStructType())

def save_df(df, name, date_partition, partitions=1):
    if date_partition is not None:
        partition_str = "/submission={day}".format(day=date_partition)
    else:
        partition_str=""


    path_fmt = "s3n://telemetry-parquet/harter/cliqz_{name}/v1{partition_str}"
    path = path_fmt.format(name=name, partition_str=partition_str)
    df.coalesce(partitions).write.mode("overwrite").parquet(path)

def __main__(sc, sqlContext, submission_date):
    if submission_date is None:
        submission_date = (date.today() - timedelta(1)).strftime("%Y%m%d")
    get_doctype_pings = lambda docType: Dataset.from_source("telemetry") \
        .where(docType=docType) \
        .where(submissionDate=submission_date) \
        .where(appName="Firefox") \
        .records(sc)

    old_st = pings_to_df(
        sqlContext,
        get_doctype_pings("testpilottest"),
        DataFrameConfig([
            ("client_id", "clientId", None, StringType()),
            ("event", "payload/payload/testpilotPingData/event", None, StringType()),
            ("snooze_time", "payload/payload/testpilotPingData/snooze_time", None, LongType()),
            ("snooze_time_type", "payload/payload/testpilotPingData/snooze_time_type", None, StringType()),
            ("creation_date", "creationDate", dateutil.parser.parse, TimestampType()),
            ("test", "payload/test", None, StringType()),
            ("variants", "payload/variants", None, StringType()),
            ("timestamp", "payload/timestamp", None, LongType()),
            ("version", "payload/version", None, StringType())
        ])).filter("event IS NOT NULL") \
           .filter("test = 'snoozetabs@mozilla.com'")
    
    new_st = pings_to_df(
        sqlContext,
        get_doctype_pings("testpilottest"),
        DataFrameConfig([
            ("client_id", "clientId", None, StringType()),
            ("event", "payload/payload/event", None, StringType()),
            ("snooze_time", "payload/payload/snooze_time", None, LongType()),
            ("snooze_time_type", "payload/payload/snooze_time_type", None, StringType()),
            ("creation_date", "creationDate", dateutil.parser.parse, TimestampType()),
            ("test", "payload/test", None, StringType()),
            ("variants", "payload/variants", None, StringType()),
            ("timestamp", "payload/timestamp", None, LongType()),
            ("version", "payload/version", None, StringType())
        ])).filter("event IS NOT NULL") \
           .filter("test = 'snoozetabs@mozilla.com'")
    return old_st.union(new_st)
```
    Unable to parse whitelist (/mnt/anaconda2/lib/python2.7/site-packages/moztelemetry/histogram-whitelists.json). Assuming all histograms are acceptable.



```python
tpt = __main__(sc, sqlContext, submission_date)
```

```python
tpt.repartition(1).write.parquet('s3://telemetry-parquet/testpilot/txp_snoozetabs/v2/submission_date={}'.format(submission_date))
```
