---
title: addon_aggregates derived dataset script
authors:
- Ben Miroglio
tags:
- add-ons
- okr
- derived dataset
created_at: 2017-02-08 00:00:00
updated_at: 2017-05-03 14:17:08.858458
tldr: script to be run daily that contructs the addon_aggregates table in re:dash
---
# Add-ons 2017 OKR Data Collection

Some OKRs for 2017 can be feasibly collected via the `addons` and `main_summary` tables. These tables are huge and aren't appropriate to query directly via re:dash. This script condenses these tables so that the result contains the least data possible to track the following OKRs:

* **OKR 1: Increase number of users who self-install an Add-on by 5%**
* **OKR 2: Increase average number of add-ons per profile by 3%**
* **OKR 3: Increase number of new Firefox users who install an add-on in first 14 days by 25%**

These OKRs, in addition to other add-on metrics, are tracked via the [Add-on OKRs Dashboard](https://sql.telemetry.mozilla.org/dashboard/add-on-okrs_1#edit_dashboard_dialog) in re:dash.


```python
from __future__ import division
import pyspark.sql.functions as fun
import pyspark.sql.types as st
import math
import os
import datetime as dt

sc.setLogLevel("INFO")
```

```python
def optimize_repartition(df, record_size, partition_size=280):
    '''
    Repartitions a spark DataFrame <df> so that each partition is 
    ~ <partition_size>MB, defaulting to 280MB. record_size must be 
    estimated beforehand--i.e. write the dataframe to s3, get the size 
    in bytes and divide by df.count(). 
    
    Returns repartitioned dataframe if a repartition is necessary.
    '''
    total_records = df.count()
    print "-- Found {} records".format(total_records),
    
    #convert megabytes to bytes
    partition_size *= 1000000
    
    records_per_partition = partition_size / record_size
    num_partitions = int(math.ceil(total_records / records_per_partition))

    if num_partitions != df.rdd.getNumPartitions():
        print "-- Repartitioning with {} partitions".format(num_partitions)
        df = df.repartition(num_partitions)
    return df

def get_env_date():
    '''
    Returns environment date if it exists.
    otherwise returns yesterday's date
    '''
    yesterday = dt.datetime.strftime(dt.datetime.utcnow() - dt.timedelta(1), "%Y%m%d")
    return os.environ.get('date', yesterday)

def get_dest(bucket, prefix):
    '''
    Uses environment bucket if it exists.
    Otherwises uses the bucket passed as a parameter
    '''
    bucket = os.environ.get('bucket', bucket)
    return '/'.join([bucket, prefix])
    

# I use -1 and 1 because it allows me to segment users 
# into three groups for two different cases:
#
# **Case 1**: 
# Users that have only foreign-installed add-ons, only self-installed add-ons, 
# or a combination. Applying `boot_to_int()` on a `foreign_install` boolean, 
# I can sum the resulting field grouped by `client_id` and `submission_date_s3`  
# to identify these groups as 1, -1, and 0 respectively.
#
# **Case 2**: Users that have the default theme, a custom theme, 
# or changed their theme (from default to custom or visa versa) on a given day: 
# Applying `boot_to_int()` on a `has_custom_theme` boolean, I can sum the 
# resulting field grouped by `client_id` and `submission_date_s3`  
# to identify these groups as -1, 1, and 0 respectively.
bool_to_int = fun.udf(lambda x: 1 if x == True else -1, st.IntegerType())
```
Unless specified in the environment, the target date is yesterday, and the bucket used is passed as a string to `get_dest()`


```python
target_date = get_env_date()
dest = get_dest(bucket="telemetry-parquet", prefix="addons/agg/v1")
```
# Load `addons` and `main_summary` for yesterday (unless specified in the environment)


```python
addons = sqlContext.read.parquet("s3://telemetry-parquet/addons/v2")
addons = addons.filter(addons.submission_date_s3 == target_date) \
               .filter(addons.is_system == False) \
               .filter(addons.user_disabled == False) \
               .filter(addons.app_disabled == False) \

ms = sqlContext.read.option('mergeSchema', 'true')\
             .parquet('s3://telemetry-parquet/main_summary/v4')
ms = ms.filter(ms.submission_date_s3 == target_date)
```
# Aggregate

These are the aggregations / joins that we **don't** want to do in re:dash.

* The resulting table is one row per distinct client, day, channel, and install type
  + foreign_install = true -> side-loaded add-on, foreign_install = false ->  self-installed add-on
* Each client has a static field for profile_creation_date and min_install_day (earliest add-on installation date)
* Each client has a daily field `user_type`
   * 1  -> only foreign installed add-ons
   * -1 -> only self-installed
   * 0  -> foreign installed and self installed
* Each client has a daily field `has_custom_theme`.
   * 1  -> has a custom theme
   * -1 -> has default theme
   * 0  -> changed from default to custom on this date
* To facilitate total population percentages, each submission date/channel has two static fields
  + n_custom_theme_clients (# distinct clients on that day/channel with a custom theme)
  + n_clients (# distinct total clients on that date/channel)


```python
%%time

default_theme_id = "{972ce4c6-7e08-4474-a285-3208198ce6fd}"


# count of distinct client submission_date, channel and install type
count_by_client_day = addons\
  .select(['client_id', 'submission_date_s3', 'normalized_channel',
           'foreign_install', 'addon_id'])\
  .distinct()\
  .groupBy(['client_id', 'submission_date_s3','foreign_install', 'normalized_channel'])\
  .count()

# count of clients that have only foreign_installed, only self_installed and both
# per day/channel
user_types = count_by_client_day\
  .select(['client_id', 'submission_date_s3', 'normalized_channel',
           bool_to_int('foreign_install').alias('user_type')])\
  .groupBy(['client_id', 'submission_date_s3', 'normalized_channel'])\
  .sum('user_type')\
  .withColumnRenamed('sum(user_type)', 'user_type')

count_by_client_day = count_by_client_day.join(user_types, 
                                               on=['client_id', 'submission_date_s3', 'normalized_channel'])


# does a client have a custom theme?
# aggregate distinct values on a day/channel, since a client could have
# changed from default to custom
ms_has_theme = ms.select(\
   ms.client_id, ms.normalized_channel, bool_to_int(ms.active_theme.addon_id != default_theme_id).alias('has_custom_theme'))\
  .distinct()\
  .groupBy(['client_id', 'normalized_channel']).sum('has_custom_theme') \
  .withColumnRenamed('sum(has_custom_theme)', 'has_custom_theme')
               

# client_id, profile_creation_date and the earliest
# install day for an addon
ms_install_days = ms\
  .select(['client_id', 'profile_creation_date', 
           fun.explode('active_addons').alias('addons')])\
  .groupBy(['client_id', 'profile_creation_date'])\
  .agg(fun.min("addons.install_day").alias('min_install_day'))
    

# combine data
current = count_by_client_day\
  .join(ms_install_days, on='client_id', how='left')\
  .join(ms_has_theme, on=['client_id', 'normalized_channel'], how='left')\
  .drop('submission_date_s3')


# add total number of distinct clients per day/channel
# and total number of distinct clients with a custom theme per day/channel
# Note that we could see the same client on multiple channels
# so downstream analysis should be done within channel
n_clients = ms.select(['client_id', 'normalized_channel']).distinct()\
               .groupby('normalized_channel').count()\
               .withColumnRenamed('count', 'n_clients')

n_custom_themes = ms_has_theme\
  .filter(ms_has_theme.has_custom_theme >= 0)\
  .select(['client_id', 'normalized_channel']).distinct()\
  .groupby('normalized_channel').count()\
  .withColumnRenamed('count', 'n_custom_theme_clients')

current = current.join(n_custom_themes, on='normalized_channel')\
                 .join(n_clients, on='normalized_channel')
    
current = current.withColumn('n_clients', current.n_clients.cast(st.IntegerType()))\
                 .withColumn('n_custom_theme_clients', current.n_custom_theme_clients.cast(st.IntegerType()))
    
# repartition data
current = optimize_repartition(current, record_size=39)

# write to s3
current.write.format("parquet")\
  .save('s3://' + dest + '/submission_date_s3={}'.format(target_date), mode='overwrite')
```

```python
current.printSchema()
```
