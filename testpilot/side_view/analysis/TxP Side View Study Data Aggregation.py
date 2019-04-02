# Databricks notebook source
import numpy as np
import matplotlib as mpl
from matplotlib import pyplot as plt
import os.path as op

import pandas as pd
from mozanalysis.stats import bootstrap

from datetime import datetime as dt, timedelta, date
import json

# COMMAND ----------

# this version of pyspark instantiates a SparkContext `sc` and SQLContext `sqlContext`
spark.conf.set('spark.databricks.queryWatchdog.maxQueryTasks', 500000)
spark.conf.set('spark.sql.autoBroadcastJoinThreshold', -1)
spark.conf.set('spark.databricks.queryWatchdog.maxHivePartitions', 30000)
import pyspark.sql.functions as fun
from pyspark.sql.window import Window
from pyspark.sql import Row

# COMMAND ----------

# MAGIC %md We are accessing the participants of the SHIELD study and will be addressing some of the PHD questions.

# COMMAND ----------

ROOT = op.join('/', 'dbfs', 'teon', 'testpilot', 'side_view')
DATE = dt.today().strftime('%Y-%m-%d')
B_STARTDATE = '2018-11-08'
B_ENDDATE = '2018-11-14'
E_STARTDATE  = '2018-11-15'
E_ENDDATE    = '2018-12-13'

# COMMAND ----------

b_start, b_end, e_start, e_end = [''.join(a_date.split('-')) for a_date in [B_STARTDATE, B_ENDDATE, E_STARTDATE, E_ENDDATE]]

# COMMAND ----------

ms = spark.sql("""
SELECT
    client_id,
    submission_date_s3 AS date,
    scalar_parent_browser_engagement_total_uri_count_sum AS total_uri_count
FROM
    clients_daily
WHERE
    submission_date_s3 >= '{}'
    AND submission_date_s3 <= '{}'
    AND app_name = 'Firefox'
SORT BY date
""".format(b_start, e_end))

# COMMAND ----------

# this may not be necessary
# baseline = ms.filter("date >= '{}' AND date < '{}'".format(b_start, e_end))  \
#              .join(data_client_agg.select('client_id', 'branch_exp'), on='client_id')
#
# baseline_client_agg = baseline.groupBy('client_id', 'date')  \
#                               .agg(fun.max(fun.col('branch_exp').cast('long')).alias('branch_exp'),
#                                    fun.max(fun.col('total_uri_count').cast('long')).alias('total_uri_count'))
#
# baseline_agg = baseline_client_agg.groupBy('branch_exp', 'date').agg(fun.mean(fun.col('total_uri_count')).alias('avg_total_uri_count'),
#                                                                      fun.stddev(fun.col('total_uri_count')).alias('sd_total_uri_count'),
#                                                                      fun.count(fun.col('client_id')).alias('n_clients'))

# COMMAND ----------

data = sqlContext.read.parquet("s3://net-mozaws-prod-us-west-2-pipeline-data/telemetry-shield-study-addon-parquet")  \
                 .filter("payload.study_name = 'side-view-1'")  \
                 .filter("application.channel = 'release'")

# COMMAND ----------

data = data.withColumn('date', data.metadata.submission_date)
data = data.filter("date >= {} AND date <= {}".format(e_start, e_end))

# COMMAND ----------

# MAGIC %md Here we are adding some additional variables to make the analysis easier:
# MAGIC - `panel_used_today`: describes whether the sidebar panel was used today.
# MAGIC - `total_daily_uri_to_sv`: describes the number of URIs sent to the sideview bar.
# MAGIC - `branch_control`: true if the client was given the empty control addon.
# MAGIC - `branch_exp`: true if the client was given the sideview addon.
# MAGIC - `onboarding_shown`: true if the client engaged with the onboarding

# COMMAND ----------

# data = data.withColumn('branch', fun.coalesce((data.payload.data.attributes['message'] == 'addon_control_init').cast('integer')-fun.lit(1), fun.lit(-1)))

# COMMAND ----------

data = data.withColumn('branch_control', (data.payload.data.attributes['message'] == 'addon_control_init').cast('integer')) \
           .withColumn('branch_exp', (data.payload.data.attributes['message'] == 'addon_init').cast('integer')) \
           .withColumn('panel_used_today', (data.payload.data.attributes['message'] == 'panel_used_today').cast('integer'))  \
           .withColumn('onboarding_shown', (data.payload.data.attributes['message'] == 'onboarding_shown').cast('integer'))  \
           .withColumn('uri_to_sv', (data.payload.data.attributes['message'] == 'uri_to_sv').cast('integer'))

# COMMAND ----------

data = data.withColumn('branch_exp_date', fun.when(data.branch_exp == 1, data.metadata.date))  \
           .withColumn('branch_control_date', fun.when(data.branch_control == 1, data.metadata.date))

# COMMAND ----------

data_client_agg = data.groupBy('client_id', 'date')  \
                      .agg(fun.max(fun.col('panel_used_today')).alias('panel_used'),
                           fun.max(fun.col('onboarding_shown')).alias('onboarding_shown'),
                           fun.max(fun.col('branch_exp')).alias('branch_exp'),
                           fun.max(fun.col('branch_control')).alias('branch_control'),
                           fun.sum(fun.col('uri_to_sv')).alias('total_uri_to_sv'),
                           fun.first(fun.coalesce(fun.col('branch_exp_date'), fun.lit(-1))).alias('branch_exp_date'),
                           fun.first(fun.coalesce(fun.col('branch_control_date'), fun.lit(-1))).alias('branch_control_date'))

# COMMAND ----------

# # Exploratory
# data_client_agg.filter('branch_exp = 0 AND branch_control = 0').agg(fun.countDistinct('client_id')).collect()

# COMMAND ----------

# # Exploratory
# data_client_agg.filter('branch_exp = 1 AND branch_control = 1').agg(fun.countDistinct('client_id')).collect()

# COMMAND ----------

# # Exploratory
# data_client_agg.agg(fun.countDistinct('client_id')).collect()

# COMMAND ----------

# # Exploratory
# data_client_agg.select('branch_exp', 'date').where((data_client_agg.client_id == '0ad72d14-096f-4b70-bb2e-e95078ce2d2b')).collect()
# data_client_agg.filter('branch_exp = 1 AND branch_control = 1').take(1)
# data_client_agg.where((data_client_agg.client_id == '0ad72d14-096f-4b70-bb2e-e95078ce2d2b')
#            & (data_client_agg.branch_exp_date != -1) 
#            & (data_client_agg.branch_control_date != -1)).select('client_id', 'branch_control_date', 'branch_exp_date').collect()

# COMMAND ----------

exclude_clients = data_client_agg.filter('branch_exp = 1 AND branch_control = 1').select('client_id')

# COMMAND ----------

data_client_agg = data_client_agg.join(exclude_clients, on='client_id', how='left_anti')

# COMMAND ----------

# # Exploratory
# data_client_agg.filter('panel_used = 0 AND total_uri_to_sv > 0').agg(fun.countDistinct('client_id')).collect()

# COMMAND ----------

# # Exploratory
# data_client_agg.filter('panel_used = 1 AND total_uri_to_sv = 0').agg(fun.countDistinct('client_id')).collect()

# COMMAND ----------

# # Exploratory
# data_client_agg.filter('panel_used = 1 AND total_uri_to_sv > 0').agg(fun.countDistinct('client_id')).collect()

# COMMAND ----------

# # Exploratory
# data_client_agg.filter('panel_used = 1').agg(fun.countDistinct('client_id')).collect()

# COMMAND ----------

client_uris = ms.join(data_client_agg.select('client_id'), 'client_id')

# COMMAND ----------

data_client_date_agg = data_client_agg.join(ms, on=['client_id', 'date'], how='right')

# COMMAND ----------

sv_users = data_client_agg.filter('panel_used = 1').groupby('date')  \
                          .agg(fun.mean(fun.col('total_uri_to_sv')).alias('avg_total_uri_to_sv'),
                               fun.stddev(fun.col('total_uri_to_sv')).alias('sd_total_uri_to_sv'),
                               fun.countDistinct(fun.col('client_id')).alias('n_clients'))
df_sv_users = sv_users.toPandas()
df_sv_users.sort_values('date', inplace=True)

# COMMAND ----------

PREFIX = 'side_view-df_sv_users'
EXT = '.csv'
FILENAME = op.join(ROOT, '-'.join((PREFIX, DATE)) + EXT)
df_sv_users.to_csv(FILENAME)
print(FILENAME)

# COMMAND ----------

onboarding_users = data_client_agg.filter('panel_used = 1').groupby('client_id')  \
                          .agg(fun.max(fun.col('onboarding_shown')).alias('onboarding_shown'),
                               fun.sum(fun.col('total_uri_to_sv')).alias('total_uri_to_sv'),
                               fun.mean(fun.col('total_uri_to_sv')).alias('avg_daily_total_uri_to_sv'))

# COMMAND ----------

df_onboarding_users = onboarding_users.toPandas()

# COMMAND ----------

# Bootstrapping iterations
n_iterations = 2000

# COMMAND ----------

metrics = ['total_uri_to_sv', 'avg_daily_total_uri_to_sv']
onboarding_bootstrap = {metric: np.empty((2,n_iterations), dtype=float) for metric in metrics}
filter_statements = ['onboarding_shown = 0', 'onboarding_shown = 1']

# COMMAND ----------

for metric in onboarding_bootstrap:
    for jj in range(len(filter_statements)):
      df = df_onboarding_users[onboarding_users_df['onboarding_shown'] == jj]
      n_items = len(df)
      for ii in range(n_iterations):
        onboarding_bootstrap[metric][jj, ii] = df[metric].sample(n=n_items, replace=True, random_state=ii).mean()
    del df

# COMMAND ----------

PREFIX = 'side_view-onboarding_bootstrap'
EXT = '.npy'
FILENAME = op.join(ROOT, '-'.join((PREFIX, DATE)) + EXT)
np.save(FILENAME, onboarding_bootstrap)
print(FILENAME)

# COMMAND ----------

df_sv_users

# COMMAND ----------

data.groupBy('branch_exp').agg(fun.countDistinct('client_id')).collect()

# COMMAND ----------

data_client_agg = data_client_date_agg.groupBy('client_id')  \
                                      .agg(fun.max(fun.col('branch_exp')).alias('branch_exp'),
                                           fun.max(fun.col('panel_used')).alias('total_count_panel_used'),
                                           fun.sum(fun.col('onboarding_shown')).alias('total_count_onboarding_shown'),
                                           fun.mean(fun.col('total_uri_to_sv')).alias('avg_daily_total_uri_to_sv'),
                                           fun.stddev(fun.col('total_uri_to_sv')).alias('sd_daily_total_uri_to_sv'),
                                           fun.mean(fun.col('total_uri_count')).alias('avg_daily_total_uri_count'),
                                           fun.stddev(fun.col('total_uri_count')).alias('sd_daily_total_uri_count'))

# COMMAND ----------

# Bootstrapping iterations
n_iterations = 2000

# COMMAND ----------

metrics = ['total_count_panel_used', 'total_count_onboarding_shown', 'avg_daily_total_uri_to_sv', 'avg_daily_total_uri_count']
metrics_bootstrap = {metric: np.empty((2,n_iterations), dtype=float) for metric in metrics}
filter_statements = ['branch_exp = 0', 'branch_exp = 1']

# COMMAND ----------

metrics_bootstrap['total_count_panel_used'][0, 1]

# COMMAND ----------

for jj, filter_statement in enumerate(filter_statements):
  for metric in metrics_bootstrap:
    df = data_client_agg.select(metric).filter(filter_statement).toPandas()
    n_items = len(df)
    for ii in range(n_iterations):
      metrics_bootstrap[metric][jj, ii] = df[metric].sample(n=n_items, replace=True, random_state=ii).mean()
    del df

# COMMAND ----------

PREFIX = 'side_view-metrics_bootstrap'
EXT = '.npy'
FILENAME = op.join(ROOT, '-'.join((PREFIX, DATE)) + EXT)
np.save(FILENAME, metrics_bootstrap)
print(FILENAME)

# COMMAND ----------


