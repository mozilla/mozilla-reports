---
title: Topline Summary using Main Summary Dataset
authors:
- acmiyaguchi
tags:
- main_summary
- executive
- topline
- summary
- dataframe
- spark
- joins
created_at: 2016-11-14 00:00:00
updated_at: 2016-11-30 16:34:01.126578
tldr: 'Port of the topline/executive summary using the main summary dataset (not for
  production usage).

  '
---
# Topline Summary using Main Summary Dataset

[Bug 1309574](https://bugzilla.mozilla.org/show_bug.cgi?id=1309574) involves porting the executive summary to use the main summary dataset. The original script can be found [mozilla-services/data-pipeline/run_executive_report.py](https://github.com/mozilla-services/data-pipeline/blob/e5c29541794325388336a210746029dce998b9e5/reports/executive_summary/run_executive_report.py).

### Setup and Helper Functions
First we define some helper functions that will serve us later. This report can be done on a weekly and monthly basis, so I have included a flexible date function for manipulating the report period. There are also serveral pyspark user defined functions (UDF) for preprocessing data since many of the fields are not within expected range of values.

### Sourcing the Data
This defines the sources of data used for the executive summary and the dataframes that represent them. We load the main summary from telemetry-parquet. The crash data needs to be sourced from raw pings, but the information can be easily joined with the summarized data.

### Queries
These queries translate the original sql queries into their equivalent spark dataframe operations. I have opted to avoid the use of spark's ability to run raw sql statements since there wasn't a direct mapping from the original script to this notebook. In particular, exploding the search_counts field was less than straightforward.

### Execution
Finally, the entry point for execution can be found near the end of the notebook. This is where the report date and period can be manipulated to generate a new dataset for the executive report. 

## Setup and Helper Functions


```python
!pip install arrow --quiet
```

```python
import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# reduce noise
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
```
This script takes a report start date, and will generate a report monthly or weekly. We need to get the week or month following the start date. If we are determining the count of inactive users, we will need to query in the [previous period](https://github.com/mozilla-services/data-pipeline/blob/master/reports/executive_summary/run_executive_report.py#L163).


```python
import arrow

def date_range(start_date, period, last_period=False):
    """Returns the begin_date, end_date for this report.
    
    start_date:  datestring in the format YYYYMMDD
    period:      type of period, either 'months' or 'weeks'
    last_period: determines if this will this or last month, defaults to this month
    """
    if period not in ('months', 'weeks', 'day'):
        log.warning("{} is an invalid argument to date_range, defaulting to `weeks`"
                    .format(period))
        period = 'weeks'
    
    # Not used in production, this is for testing against a smaller subset of days
    if period == 'day':
        return start_date, start_date

    fmt = 'YYYYMMDD'
    begin_date = arrow.get(start_date, fmt)
    if last_period:
        # offset the start date by a single period
        offset = {period: -1}
        begin_date = begin_date.replace(**offset)

    offset = {period: 1}
    end_date = begin_date.replace(**offset)
    
    return begin_date.format(fmt), end_date.format(fmt)
```
### User Defined Functions
These UDFs capture the logic described in the [`extract_executive_summary.lua` heka decoder]( https://github.com/mozilla-services/data-pipeline/blob/515b85101e7335a66fb8c26316cd9721c832b098/heka/sandbox/decoders/extract_executive_summary.lua).


```python
import re
from functools import partial
from pyspark.sql.functions import udf
from pyspark.sql.types import *


SEC_IN_HOUR = 60 * 60
SEC_IN_DAY = SEC_IN_HOUR * 24

# UDF for aggregating search counts based on search engine

search_schema = StructType([
    StructField("google", IntegerType(), False),
    StructField("bing", IntegerType(), False),
    StructField("yahoo", IntegerType(), False),
    StructField("other", IntegerType(), False)])

search_pat = ['[Gg]oogle', '[Bb]ing', '[Yy]ahoo', '.']
search_pat_comp = [re.compile(pat) for pat in search_pat]

def get_search_counts(row):
    """ Return a list of aggregate values for each search engine in a row. """
    counts = [0, 0, 0, 0]

    # This client does not have any searches
    if not row:
        return counts

    for cell in row:
        if not cell.engine:
            continue
        for i, regex in enumerate(search_pat_comp):
            if regex.match(cell.engine):
                counts[i] += cell['count'] or 0
    return counts


# UDF for determining hours of usage

def get_hours(uptime):
    """ Convert uptime from seconds to hours if the uptime value is plausible. """
    if not uptime or uptime < 0 or uptime >= 180 * SEC_IN_DAY:
        return 0.0
    return uptime / SEC_IN_HOUR


# UDF for determining when the client profile was created

def get_profile_creation(timestamp):
    """Convert days since unix epoch to nanoseconds since epoch"""
    if not timestamp or timestamp < 0:
        return 0
    return timestamp * SEC_IN_DAY


# UDF for normalizing country name

country_names = set([
    "AD","AE","AF","AG","AI","AL","AM","AO","AQ","AR","AS","AT","AU",
    "AW","AX","AZ","BA","BB","BD","BE","BF","BG","BH","BI","BJ","BL","BM","BN",
    "BO","BQ","BR","BS","BT","BV","BW","BY","BZ","CA","CC","CD","CF","CG","CH",
    "CI","CK","CL","CM","CN","CO","CR","CU","CV","CW","CX","CY","CZ","DE","DJ",
    "DK","DM","DO","DZ","EC","EE","EG","EH","ER","ES","ET","FI","FJ","FK","FM",
    "FO","FR","GA","GB","GD","GE","GF","GG","GH","GI","GL","GM","GN","GP","GQ",
    "GR","GS","GT","GU","GW","GY","HK","HM","HN","HR","HT","HU","ID","IE","IL",
    "IM","IN","IO","IQ","IR","IS","IT","JE","JM","JO","JP","KE","KG","KH","KI",
    "KM","KN","KP","KR","KW","KY","KZ","LA","LB","LC","LI","LK","LR","LS","LT",
    "LU","LV","LY","MA","MC","MD","ME","MF","MG","MH","MK","ML","MM","MN","MO",
    "MP","MQ","MR","MS","MT","MU","MV","MW","MX","MY","MZ","NA","NC","NE","NF",
    "NG","NI","NL","NO","NP","NR","NU","NZ","OM","PA","PE","PF","PG","PH","PK",
    "PL","PM","PN","PR","PS","PT","PW","PY","QA","RE","RO","RS","RU","RW","SA",
    "SB","SC","SD","SE","SG","SH","SI","SJ","SK","SL","SM","SN","SO","SR","SS",
    "ST","SV","SX","SY","SZ","TC","TD","TF","TG","TH","TJ","TK","TL","TM","TN",
    "TO","TR","TT","TV","TW","TZ","UA","UG","UM","US","UY","UZ","VA","VC","VE",
    "VG","VI","VN","VU","WF","WS","YE","YT","ZA","ZM","ZW"])

def normalize_country(name):
    if not name or type(name) != str:
        return "Other"
        
    name = name.upper()
    if name not in country_names:
        return "Other"
    return name


# Information relevant to creating a UDF to normalize channel column
channel_labels = ['release', 'beta', 'nightly', 'aurora', 'Other']
channel_pat = [
    '^release$',
    '^beta$', 
    '^nightly$|^nightly-cck-', 
    '^aurora$',
    '.'
]
channel_pat_comp = [re.compile(pat) for pat in channel_pat]


# Information relevant to creating a UDF to normalize os column+
os_labels = ['Windows', 'Mac', 'Linux', 'Other']
os_pat = [
    '^Windows|WINNT', 
    'Darwin', 
    'Linux|BSD|SunOS', 
    '.'
]
os_pat_comp = [re.compile(pat) for pat in os_pat]


def normalize(patterns, labels, s):
    """ Categorize a string s based on whether it matches a compiled regex pattern.
    The default pattern should be at index -1.
    
    pattern: list of compiled regex pattern to match against
    labels:  list of lables of len(pattern), where label[i] corresponds to pattern[i]
    s:       string to categorize
    """
    
    norm = labels[-1]
    if not s:
        return norm
    for label, pattern in zip(labels, patterns):
        if pattern.match(s):
            norm = label
            break
    return norm


# declare the User Defined Functions for usage later
search_udf = udf(get_search_counts, search_schema)
hour_udf = udf(get_hours, DoubleType())
creation_udf = udf(get_profile_creation, IntegerType())
country_udf = udf(normalize_country, StringType())
channel_udf = udf(partial(normalize, channel_pat_comp, channel_labels), StringType())
os_udf = udf(partial(normalize, os_pat_comp, os_labels), StringType())
```
## Sourcing the Data

The report dataframe is a subset of the `main_summary` that is relevant to our summaries. We also generate a crash dataframe to count the number of crashes based on country, channel, and operating system.

The relevant columns were found by cross referencing `run_executive_report.py` with columns generated by the `extract_executive_summary.lua` filter.

### main_summary
The [MainSummaryExample notebook](https://gist.github.com/mreid-moz/518f7515aac54cd246635c333683ecce) is good starting place for understanding how to use the main_summary.


```python
import pyspark.sql.functions as F
from pyspark.sql import SQLContext, Window


def get_report_df(start_date, end_date):
    """Return a dataframe containing the raw report data. """
    
    source_url = "s3://telemetry-parquet/main_summary/v3"
    main_summary_df = sqlContext.read.parquet(source_url)

    columns = [
        'client_id',
        country_udf('country').alias('country'),
        'submission_date',
        'is_default_browser',
        creation_udf('profile_creation_date').alias('profile_creation_date'), 
        channel_udf('channel').alias('channel'), 
        os_udf('os').alias('os'),
        search_udf('search_counts').alias('search_counts'),
        hour_udf(F.col('subsession_length').cast('double')).alias('hours')
    ]

    report_df = (
        main_summary_df
            .filter(start_date <= F.col('submission_date_s3'))
            .filter(F.col('submission_date_s3') <= end_date)
            .filter(F.col('app_name') == 'Firefox')
            .select(columns)
    )
    
    return report_df
```
### telemetry-pings where docType = 'crash'
We are missing the crash pings in the main summary, but we can filter the raw pings manually.


```python
from moztelemetry import get_pings_properties
from moztelemetry.dataset import Dataset


def get_crash_df(start_date, end_date):
    """ Return a dataframe containing relevent columns from crash pings. """t
    ping_rdd = (
        Dataset
            .from_source("telemetry")
            .where(docType='crash')
            .where(appName='Firefox')
            .where(submissionDate=lambda x: start_date <= x <= end_date)
            .records(sc)
    )

    crash_rdd = get_pings_properties(ping_rdd, {
            "country": "meta/geoCountry", 
            "channel": "meta/appUpdateChannel",
            "os": "meta/os"
        })

    crash_schema = StructType([
            StructField("country", StringType(), True),
            StructField("os", StringType(), True),t
            StructField("channel", StringType(), True)
        ])

    # this guarantees the order in the crash_schema
    def to_tuple(row):
        return row['country'], row['os'], row['channel']

    return sqlContext.createDataFrame(crash_rdd.map(to_tuple), crash_schema)
```
    Unable to parse whitelist (/home/hadoop/anaconda2/lib/python2.7/site-packages/moztelemetry/histogram-whitelists.json). Assuming all histograms are acceptable.


## Queries


```python
def get_easy_aggregates(report_df, crash_df, groups, report_date):
    """ Return the aggregates of the number of hours, crashes, and search counts. """
    
    # Clean the columns of the crash aggregate to match the easy ones
    crash_agg_df = (
        crash_df
            .select(
                country_udf('country').alias('country'),
                channel_udf('channel').alias('channel'), 
                os_udf('os').alias('os'))
            .groupby(groups) 
            .agg(F.count('*').alias('crashes'))
    )

    # Join the hours and search aggregates with the crash aggregates
    easy_aggregate_df = (
        report_df
            .groupby(groups)
            .agg(
                F.sum('hours').alias('hours'), 
                F.sum('search_counts.google').alias('google'),
                F.sum('search_counts.bing').alias('bing'),
                F.sum('search_counts.yahoo').alias('yahoo'),
                F.sum('search_counts.other').alias('other')) 
            .join(crash_agg_df, ['country', 'channel', 'os', 'date'])
    )
    
    return easy_aggregate_df
```

```python
def get_client_values(report_df, groups, report_date):
    """ Return the number of new clients, default clients, and active users. """
    
    # Used to determine new clients in the report period
    report_timestamp = arrow.get(report_date, 'YYYYMMDD').timestamp

    # First find the most recent value of all the clients.
    clients_df = (
        report_df
            .select(
                'client_id', 
                'country', 
                'channel', 
                'os',
                F.when(F.col('profile_creation_date') >= report_timestamp, 1)
                    .otherwise(0)
                    .alias('new_client'),
                F.when(F.col('is_default_browser'), 1)
                    .otherwise(0)
                    .alias('default_client'),
                F.row_number()
                    .over(Window.partitionBy('client_id')
                                .orderBy(F.desc('submission_date')))
                    .alias('clientid_rank'))
            .select(
                'client_id', 
                'country', 
                'channel', 
                'os', 
                'new_client', 
                'default_client')
            .where(F.col('clientid_rank') == 1)
    )

    # Find the client's aggregate values
    client_values_df = (
        clients_df
            .groupby(groups)
            .agg(
                F.count('*').alias('active'),
                F.sum('new_client').alias('new_client'),
                F.sum('default_client').alias('default_client'))
    )
    
    return client_values_df
```
## Execution


```python
from pyspark.storagelevel import StorageLevel

# Get the initial date in YYYYMMDD format. This is the date format given by airflow,
# as well as the date format used to partition the main_summary parquet data
report_date = '20160901'
start_date, end_date = date_range(report_date, 'weeks')
log.info("Starting executive report for dates {}-{}".format(start_date, end_date))

# Source the initial data from parquet and raw pings
report_df = get_report_df(start_date, end_date)
crash_df = get_crash_df(start_date, end_date)

report_df.persist(StorageLevel.MEMORY_AND_DISK)

# All report data is grouped by and then aggregated over the following columns
groups = ['country', 'channel', 'os', F.lit(report_date).alias('date')]

# Get the aggregated dataframes
easy_aggregates_df = get_easy_aggregates(report_df, crash_df, groups, report_date)
client_values_df = get_client_values(report_df, groups, report_date)

# Lets join these dataframes together
final_report_df = easy_aggregates_df.join(client_values_df, ['country', 'channel', 'os', 'date'])
final_report_df.show()

log.info("Done with processing")
```
## Other code
Code that doesn't need to be run during the main notebook execution


```python
def test_date_range():
    args = ['20160101', 'months']
    start, end = date_range(*args)
    assert start == args[0]  # start date is the same
    assert start < end       # the end date is in the future
    assert end[4:6] == '02'  # the month has changed
    
    args = ['20160101', 'months', True]
    start, end = date_range(*args)
    assert end == args[0]       # the start date has become the end date
    assert start < end          # the start is still smaller than the end date
    assert start[0:4] == '2015' # the year is handled correctly
    assert start[4:6] == '12'   # the day is handled correctly
    
    args = ['20160101', 'weeks']
    start, end = date_range(*args)
    assert end[6:8] == '08'  # going forward in the week works correctly
    
test_date_range()
```
