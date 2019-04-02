# Databricks notebook source
import numpy as np
import matplotlib as mpl
from matplotlib import pyplot as plt
import os.path as op

import pandas as pd
import statsmodels

from datetime import datetime as dt, timedelta
import json

# COMMAND ----------

# this version of pyspark instantiates a SparkContext `sc` and SQLContext `sqlContext`
spark.conf.set('spark.databricks.queryWatchdog.maxQueryTasks', 500000)
spark.conf.set('spark.sql.autoBroadcastJoinThreshold', -1)
import pyspark.sql.functions as fun
from pyspark.sql.window import Window
from pyspark.sql import Row

# COMMAND ----------

# MAGIC %md We are accessing the participants of the SHIELD study and will be addressing some of the PHD questions.

# COMMAND ----------

ROOT = op.join('/', 'dbfs', 'teon', 'cloud_storage_v2')
DATE = dt.today().strftime('%Y-%m-%d')
E_STARTDATE  = '2018-06-27'
E_ENDDATE    = '2018-07-17'

# COMMAND ----------

data = sqlContext.read.parquet("s3://net-mozaws-prod-us-west-2-pipeline-data/telemetry-shield-study-addon-parquet")  \
                 .filter("payload.study_name = 'cloudstorage-webextensionExperiment@shield.mozilla.org'")  \
                 .filter("application.channel = 'release'")

# COMMAND ----------

data = data.filter(data.creation_date.between(E_STARTDATE, E_ENDDATE))

# COMMAND ----------

# MAGIC %md Here we are adding some additional variables to make the analysis easier:
# MAGIC - `cs_provider`: describes how many cloud storage providers are currently installed on a user machine.
# MAGIC - `init_opted_in`: describes those who opted into this experiment.
# MAGIC - `opted_out`: describes those who chose to move back to their default location instead of the cloud storage provider.

# COMMAND ----------

data = data.withColumn('download_started', data.payload.data.attributes['message'] == 'download_started') \
           .withColumn('branch', data.payload.branch)  \
           .withColumn('init_opted_in', data.payload.data.attributes['message'] == 'prompt_opted_in') \
           .withColumn('opted_out', (data.payload.data.attributes['message'] == 'download_prefs') & (data.payload.data.attributes['cloud_storage_state'] == 'opted_out')) \
           .withColumn('move_download', data.payload.data.attributes['message'] == 'prompt_move_download_context_menu')  \
           .withColumn('cancel_click', data.payload.data.attributes['message'] == 'prompt_cancel_click')  \
           .withColumn('cs_provider', data.payload.data.attributes['provider_count'])

# COMMAND ----------

data_agg = data.groupBy('client_id', 'branch')  \
               .agg(fun.sum(fun.col('init_opted_in').cast('long')).alias('opted_in'),
                    fun.sum(fun.col('download_started').cast('long')).alias('total_download_started'),
                    fun.sum(fun.col('opted_out').cast('long')).alias('total_opted_out'),
                    fun.sum(fun.col('move_download').cast('long')).alias('total_move_download'),
                    fun.sum(fun.col('cancel_click').cast('long')).alias('total_cancel_click'),
                    fun.max(fun.col('cs_provider')).alias('cs_provider'))

# COMMAND ----------

data_agg = data_agg.filter("cs_provider > 0")

# COMMAND ----------

preprocess = data_agg.toPandas()

# COMMAND ----------

# MAGIC %md Let's remove outliers such that any value above or below 1.96 std is removed

# COMMAND ----------

preprocess = preprocess[np.abs(preprocess['total_download_started'] - preprocess['total_download_started'].mean()) < preprocess['total_download_started'].std() *  1.96]

# COMMAND ----------

preprocess.dropna(inplace=True)

# COMMAND ----------

preprocess.drop(['client_id'], axis=1, inplace=True)

# COMMAND ----------

PREFIX = 'cloud_storage_v2-preprocess'
EXT = '.csv'
FILENAME = op.join(ROOT, '-'.join((PREFIX, DATE)) + EXT)
preprocess.to_csv(FILENAME)
print(FILENAME)

# COMMAND ----------

# MAGIC %md Let's match the groups with equal members of the experimental and control groups

# COMMAND ----------

downloads_exp = preprocess[preprocess['opted_in'] > 0]
n_exp = len(downloads_exp)

# COMMAND ----------

downloads_control = preprocess[(preprocess['branch'] == 'control') & (preprocess['total_download_started'] > 0)].sample(n=n_exp, random_state=42)

# COMMAND ----------

df = pd.concat([downloads_control, downloads_exp])

# COMMAND ----------

PREFIX = 'cloud_storage_v2-matched'
EXT = '.csv'
FILENAME = op.join(ROOT, '-'.join((PREFIX, DATE)) + EXT)
df.to_csv(FILENAME)
print(FILENAME)

# COMMAND ----------

analysis_export = dict()

# COMMAND ----------

pd.crosstab(df['opted_in'], df['branch'])

# COMMAND ----------

# MAGIC %md View of participants filtered to have at least one download during the period.

# COMMAND ----------

pd.crosstab(df[df['total_download_started'] > 0]['opted_in'], df['branch'])

# COMMAND ----------

df.groupby(('branch', 'opted_in')).describe()

# COMMAND ----------

# MAGIC %md ## Answers to PHD questions

# COMMAND ----------

n_bootstrap = 10000
n_sample = len(df)

# COMMAND ----------

# MAGIC %md 2) We expect 1% increase in downloads in the experiment branches compared to control group. 

# COMMAND ----------

group_a = np.empty(n_bootstrap)
group_b = np.empty(n_bootstrap)

for ii in range(n_bootstrap):
  group_temp = df.sample(n=n_exp*2, replace=False, random_state=ii)['total_download_started']
  group_a[ii] = group_temp[:n_exp].mean()
  group_b[ii] = group_temp[n_exp:].mean()

# COMMAND ----------

downloads_diff = group_a - group_b

# COMMAND ----------

delta = downloads_control['total_download_started'].mean() - downloads_exp['total_download_started'].mean()
delta

# COMMAND ----------

analysis_export['downloads_diff'] = list(downloads_diff)
analysis_export['delta'] = delta

# COMMAND ----------

# MAGIC %md Plot of Differences from Permutation Testing

# COMMAND ----------

plt.clf()
plt.hist(downloads_diff, zorder=0, bins=100)
plt.axvline(delta, linestyle='dashdot', zorder=10, color='r', linewidth=3)
plt.axvline(-delta, linestyle='dashdot', zorder=10, color='r', linewidth=3)
display()

# COMMAND ----------

print('Average downloads on Control branch: {:.2f}'.format(downloads_control['total_download_started'].mean()))
print('Average downloads on Experiment branch: {:.2f}'.format(downloads_exp['total_download_started'].mean()))
print('Download Difference: {:.2f}'.format(downloads_exp['total_download_started'].mean() - downloads_control['total_download_started'].mean()))

# COMMAND ----------

print('Mean difference in bootstrapped null is: {}'.format(downloads_diff.mean()))
print('Standard deviation in bootstrapped null is: {}'.format(downloads_diff.std()))

# COMMAND ----------

p = len(downloads_diff[np.abs(downloads_diff) > np.abs(delta)]) / np.float(n_sample)
print('Bootstapped p value for observed difference is {:.2f}'.format(p))

# COMMAND ----------

download_started_exp_bootstrap = np.empty(n_bootstrap)
download_started_control_bootstrap = np.empty(n_bootstrap)
for ii in range(n_bootstrap):
    temp = df.sample(n=n_sample, replace=True, random_state=ii)
    download_started_exp_bootstrap[ii] = temp[temp['opted_in'] > 0]['total_download_started'].mean()
    download_started_control_bootstrap[ii] = temp[temp['branch'] == 'control']['total_download_started'].mean()

# COMMAND ----------

analysis_export['download_started_control_bootstrap'] = list(download_started_control_bootstrap)
analysis_export['download_started_exp_bootstrap'] = list(download_started_exp_bootstrap)

# COMMAND ----------

plt.clf()
plt.hist(download_started_control_bootstrap)
plt.title('Bootstrapped Download Means for Control Branch')
display()

# COMMAND ----------

plt.clf()
plt.hist(download_started_exp_bootstrap)
plt.title('Bootstrapped Download Means for Experiment Branch')
display()

# COMMAND ----------

ci = (download_started_control_bootstrap.mean() - 2*download_started_control_bootstrap.std(), download_started_control_bootstrap.mean() + 2*download_started_control_bootstrap.std())
'Mean Download Started in Control Branch: {:.2f}, 95% CI [{:.2f}, {:.2f}]'.format(download_started_control_bootstrap.mean(), ci[0], ci[1])

# COMMAND ----------

ci = (download_started_exp_bootstrap.mean() - 2*download_started_exp_bootstrap.std(), download_started_exp_bootstrap.mean() + 2*download_started_exp_bootstrap.std())
'Mean Download Started in Experimental Branch: {:.2f}, 95% CI [{:.2f}, {:.2f}]'.format(download_started_exp_bootstrap.mean(), ci[0], ci[1])

# COMMAND ----------

# MAGIC %md 3) Revert to local download

# COMMAND ----------

# MAGIC %md Total number of participants who opted out

# COMMAND ----------

total_opted_out = len(df[df['total_opted_out'] > 0])
total_opted_out

# COMMAND ----------

# MAGIC %md Percentage of those who opted-out

# COMMAND ----------

total_opted_in = len(df[df['opted_in'] > 0])
'Total Number of Opted-in Participants: {}'.format(total_opted_in)

# COMMAND ----------

pct_opted_out = (total_opted_out * 100 )/ float(total_opted_in)
'Percentage of subsequent opt-out: {:.2f} %'.format(pct_opted_out)

# COMMAND ----------

opted_out_bootstrap = np.empty(n_bootstrap)
for ii in range(n_bootstrap):
    temp = df.sample(n=n_sample, replace=True)
    total_opted_out = len(temp[temp['total_opted_out'] > 0])
    total_opted_in = len(temp[temp['opted_in'] > 0])
    opted_out_bootstrap[ii] = (total_opted_out)/ float(total_opted_in)

# COMMAND ----------

analysis_export['opted_out_bootstrap'] = list(opted_out_bootstrap)

# COMMAND ----------

plt.clf()
plt.hist(opted_out_bootstrap)
display()

# COMMAND ----------

ci = (opted_out_bootstrap.mean() - 2*opted_out_bootstrap.std(), opted_out_bootstrap.mean() + 2*opted_out_bootstrap.std())
'Percentage of subsequent opt-out: {:.2f}, 95% CI [{:.2f}, {:.2f}]'.format(opted_out_bootstrap.mean()*100, ci[0]*100, ci[1]*100)

# COMMAND ----------

opted_out_bootstrap.mean()

# COMMAND ----------

# MAGIC %md 4) How many users who saw cloud storage notification opted-in to cloud storage permanently by changing their download settings?

# COMMAND ----------

# MAGIC %md Total number of participants who opted in

# COMMAND ----------

total_opted_in = len(df[(df['opted_in'] > 0) & (df['total_opted_out'] == 0)])
total_opted_in

# COMMAND ----------

total_possible_cs = len(df[(df['total_cancel_click'] > 0) | (df['opted_in'] > 0)])
total_possible_cs

# COMMAND ----------

pct_opted_in = (total_opted_in * 100 )/ float(total_possible_cs)
'{:.2f} %'.format(pct_opted_in)

# COMMAND ----------

n_sample = len(df)
permanent_bootstrap = np.empty(n_bootstrap)
for ii in range(n_bootstrap):
    temp = df.sample(n=n_sample, replace=True)
    total_opted_in = len(temp[(temp['opted_in'] > 0) & (temp['total_opted_out'] == 0)])
    total_possible_cs = len(temp[(temp['total_cancel_click'] > 0) | (temp['opted_in'] > 0)])
    permanent_bootstrap[ii] = total_opted_in / float(total_possible_cs)

# COMMAND ----------

analysis_export['permanent_bootstrap'] = list(permanent_bootstrap)

# COMMAND ----------

plt.clf()
plt.hist(permanent_bootstrap)
display()

# COMMAND ----------

ci = (permanent_bootstrap.mean() - 2*permanent_bootstrap.std(), permanent_bootstrap.mean() + 2*permanent_bootstrap.std())
'Percentage of Permanent opt-in: {:.2f}, 95% CI [{:.2f}, {:.2f}]'.format(permanent_bootstrap.mean()*100, ci[0]*100, ci[1]*100)

# COMMAND ----------

# MAGIC %md 5) How many users used the "Move download" option

# COMMAND ----------

total_move_downloads = len(df[df['total_move_download'] > 0])
total_move_downloads

# COMMAND ----------

total_opted_in = len(df[df['opted_in'] > 0])
total_opted_in

# COMMAND ----------

pct_move_downloads = (total_move_downloads * 100 )/ float(total_opted_in)
'{:.2f} %'.format(pct_move_downloads)

# COMMAND ----------

pct_move_downloads_bootstrap = np.empty(n_bootstrap)
for ii in range(n_bootstrap):
    temp = df.sample(n=n_sample, replace=True)
    total_move_downloads = len(temp[temp['total_move_download'] > 0])
    total_opted_in = len(temp[temp['opted_in'] > 0])
    pct_move_downloads_bootstrap[ii] = total_move_downloads / float(total_opted_in)

# COMMAND ----------

analysis_export['pct_move_downloads_bootstrap'] = list(pct_move_downloads_bootstrap)

# COMMAND ----------

plt.clf()
plt.hist(pct_move_downloads_bootstrap)
display()

# COMMAND ----------

ci = (pct_move_downloads_bootstrap.mean() - 2*pct_move_downloads_bootstrap.std(),
      pct_move_downloads_bootstrap.mean() + 2*pct_move_downloads_bootstrap.std())
'Percentage of Move Download Users: {:.2f}, 95% CI [{:.2f}, {:.2f}]'.format(pct_move_downloads_bootstrap.mean()*100, ci[0]*100, ci[1]*100)

# COMMAND ----------

PREFIX = 'cloud_storage_v2-analysis_export'
EXT = '.csv'
FILENAME = op.join(ROOT, '-'.join((PREFIX, DATE)) + EXT)
with open(FILENAME, 'w') as FILE:
  json.dump(analysis_export, FILE)
print(FILENAME)

# COMMAND ----------


