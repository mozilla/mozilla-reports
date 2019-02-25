---
title: Health ping data analysis (Beta)
authors:
- Kate Ustiuzhanina
tags:
- firefox, telemetry, health
created_at: 2017-08-24 00:00:00
updated_at: 2017-08-29 14:32:38.854866
tldr: Validate incoming data for the new health ping and look at how clients behave.
thumbnail: images/output_7_0.png
---
```python
import ujson as json
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import plotly.plotly as py
import pandas as pd

from plotly.graph_objs import *
from moztelemetry import get_pings_properties, get_one_ping_per_client
from moztelemetry.dataset import Dataset
from collections import Counter
import operator

get_ipython().magic(u'matplotlib inline')
```

```python
pings = Dataset.from_source("telemetry") \
                .where(docType='health', appUpdateChannel="beta") \
                .records(sc, sample=1)
        
cachedData = get_pings_properties(pings, ["creationDate", "payload/pingDiscardedForSize", "payload/sendFailure", 
                                             "clientId", "meta/submissionDate", "payload/os", "payload/reason", "application/version"]).cache()
```
    fetching 3855.58046MB in 38405 files...


# Compute failures stats for each failure: sendFailure, discardedForSize. 

* for sendFailure stats include health ping count per failure type
* for discardedForSize stats include health ping count per ping type


```python
def aggregateFailures(first, second):
    if first is None:
        return second
    if second is None:
        return first
    
    res = first
    for k, v in second.items():
        if isinstance(v, int):
            if k in res:
                res[k] += v
            else: 
                res[k] = v;
    return res
```

```python
# return array of pairs [(failureName, {failureStatistic: count, ....}), ...]
# e.g. [(discardedForSize, {"main": 3, "crash": 5}), (sendFailure, {"timeout" : 34})]
def getFailuresStatPerFailureName(pings, failureNames):
    def reduceFailure(failureName):
        return pings.map(lambda p: p[failureName]).reduce(aggregateFailures)
    
    return [(name, reduceFailure(name)) for name in failureNames]
```

```python
failuresNames = ["payload/pingDiscardedForSize", "payload/sendFailure"]
```

```python
failuresStat = getFailuresStatPerFailureName(cachedData, failuresNames)
for fs in failuresStat:
    plt.title(fs[0])
    plt.bar(range(len(fs[1])), fs[1].values(), align='center')
    plt.xticks(range(len(fs[1])), fs[1].keys(), rotation=90)
    plt.show()
    print fs
```


![png](images/output_7_0.png)


    ('payload/pingDiscardedForSize', {u'main': 2013, u'crash': 222})




![png](images/output_7_2.png)


    ('payload/sendFailure', {u'eUnreachable': 46180480, u'abort': 47104, u'eChannelOpen': 45322465, u'timeout': 12014520, u'eChanndlOpen': 1})


Unknown currently represent all oversized pending pings. (https://bugzilla.mozilla.org/show_bug.cgi?id=1384903)

# sendFailures/discardedForSize per ping.


```python
import matplotlib.dates as mdates
def plotlistofTuples(listOfTuples, title="", inColor='blue'):
    keys = [t[0] for t in listOfTuples]
    values = [t[1] for t in listOfTuples]

    plt.figure(1)
    fig = plt.gcf()
    fig.set_size_inches(15, 7)

    plt.title(title)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%d/%Y'))
    plt.bar(range(len(listOfTuples)), values, align='center', color=inColor)
    plt.xticks(range(len(listOfTuples)), keys, rotation=90)
```

```python
EXPECTED_SENDFAILURES_COUNT = 60
def failureCountReasonPerPing(pings, failureName):
    pingsWithSendFailure = pings.filter(lambda ping: ping[failureName] != None) 
    return pingsWithSendFailure.map(lambda ping: (sum(ping[failureName].values()), ping["payload/reason"])).collect()

def describefailureDistribution(sendFailureCountDistr, failureName):
    failuresCount = [k for k, v in sendFailureCountDistr]
    pingsPerDaySeries = pd.Series(failuresCount)
    print pingsPerDaySeries.describe([.25, .5, .75, .95])
    
    plt.title(failureName + " per ping distribution.")
    plt.yscale('log')
    plt.ylabel('log(' + failureName + ' count)')
    plt.xlabel('ping')
    plt.plot(sorted(failuresCount))
    plt.show()

def decribeReasonDistribution(sendFailureCountDistr, failureName):
    unexpectedPingsCount = [(k, v) for k, v in sendFailureCountDistr if k > EXPECTED_SENDFAILURES_COUNT]
    print "Pings reported more than " + str(EXPECTED_SENDFAILURES_COUNT) + " " + str(len(unexpectedPingsCount))
    
    if len(unexpectedPingsCount) != 0:
        reasonStat = Counter([v for k, v in unexpectedPingsCount])  
        plotlistofTuples(reasonStat.items(), title="Reason distribution for pings reported more than " + str(EXPECTED_SENDFAILURES_COUNT) + " " + failureName)
        plt.xlabel('reason') 
        plt.ylabel('count')
        plt.show()


def describe(pings, failure):
    print "\n COMPUTATION FOR " + failure + "\n"
    countAndReason = failureCountReasonPerPing(pings, failure)
    decribeReasonDistribution(countAndReason, failure) 
    describefailureDistribution(countAndReason, failure)

```

```python
for f in failuresNames:
    describe(cachedData, f) 
```
    
     COMPUTATION FOR payload/pingDiscardedForSize
    
    Pings reported more than 60 0
    count    1364.000000
    mean        1.638563
    std         1.745934
    min         1.000000
    25%         1.000000
    50%         1.000000
    75%         1.000000
    95%         5.000000
    max        21.000000
    dtype: float64




![png](images/output_12_1.png)


    
     COMPUTATION FOR payload/sendFailure
    
    Pings reported more than 60 49712




![png](images/output_12_3.png)


    count    3.076923e+07
    mean     3.365849e+00
    std      7.436627e+00
    min      1.000000e+00
    25%      1.000000e+00
    50%      1.000000e+00
    75%      2.000000e+00
    95%      1.000000e+01
    max      1.133700e+04
    dtype: float64




![png](images/output_12_5.png)


# Validate payload
Check that:
* required fields are non-empty.
* payload/reason contains only expected values ("immediate", "delayed", "shutdown").
* payload/sendFailure and payload/discardedForSize are non empty together.
* count paramter in payload/sendFailure and payload/discardedForSize has type int.
* sendFailureType contains only expected values ("eOK", "eRequest", "eUnreachable", "eChannelOpen", "eRedirect", "abort", "timeout").
* payload/discardedForSize contains only 10 records.
* check the distribution of sendFailures (sum) per ping. We expected to have this number not more than 60. 


```python
def validate(ping):
    OK = ""
    MUST_NOT_BE_EMPTY = "must not be empty"

    # validate os
    clientId = ping["clientId"]
    
    if clientId == None:
        return ("clientId " + MUST_NOT_BE_EMPTY, ping)
    
    os = ping["payload/os"]
    if os == None:
        return ("OS " + MUST_NOT_BE_EMPTY, ping)

    name, version = os.items()
    if name == None:
        return ("OS name " + MUST_NOT_BE_EMPTY, ping)
    if version == None:
        return ("OS version " + MUST_NOT_BE_EMPTY, ping)
    
    # validate reason
    reason = ping["payload/reason"]
    if reason == None:
        return ("Reason " + MUST_NOT_BE_EMPTY, ping)
    
    if not reason in ["immediate", "delayed", "shutdown"]:
        return ("Reason must be equal to immediate, delayed or shutdown", ping)
    
    # doesn't contain failures
    sendFailure = ping["payload/sendFailure"]
    pingDiscardedForSize = ping["payload/pingDiscardedForSize"]
    if sendFailure == None and pingDiscardedForSize == None:
        return ("Ping must countain at least one of the failures", ping)

    
    # validate sendFailure
    supportedFailureTypes = ["eOK", "eRequest", "eUnreachable", "eChannelOpen", "eRedirect", "abort", "timeout"]
    if sendFailure != None and len(sendFailure) > len(supportedFailureTypes):
        return ("send Failure accept only 8 send failures", ping)
    
    if sendFailure != None:
        for key in sendFailure.keys():
            if not key in supportedFailureTypes:
                return (key + " type is not supported", ping)
        for count in sendFailure.values():
            if not isinstance(count, int):
                return ("Count must be int type", ping)
        if sum(sendFailure.values()) > 60:
            return ("sendFailure count must not be more than 60", ping)

    
     # validate pingDiscardedForSize
    if pingDiscardedForSize != None:
        if len(pingDiscardedForSize) > 10:
            return ("pingDicardedForSize accept only top ten pings types", ping)
        for count in pingDiscardedForSize.values():
            if not isinstance(count, int):
                return ("Count must be int type", ping)
    
    return (OK, ping)

# retrieve all needed fields 
validatedData = cachedData.map(validate)   
errorsPerProblem = validatedData.countByKey()   
errorsPerProblem
```




    defaultdict(int,
                {'': 30720671,
                 'OS must not be empty': 9,
                 'Ping must countain at least one of the failures': 13,
                 'Reason must be equal to immediate, delayed or shutdown': 4,
                 'clientId must not be empty': 4,
                 'sendFailure count must not be more than 60': 49712})



# Investigate errors


```python
def printOSReason(data):
    return "os: " + str(data[0]) + " reason: " + str(data[1])

def osAndReasonForErros(error):
    result = validatedData.filter(lambda pair: pair[0] == error).map(lambda pair: (pair[1]["payload/os"], pair[1]["payload/reason"])).collect()
    return result[:min(10, len(result))]
  
print "Show only 10 info lines per problem \n"
for err in errorsPerProblem.keys():
    if err != '':
        print err
        print "\n".join(map(printOSReason, osAndReasonForErros(err)))
        print "\n"
```
    Show only 10 info lines per problem 
    
    Reason must be equal to immediate, delayed or shutdown
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: ilmediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: ilmediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: ilmediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: ilmediate
    
    
    sendFailure count must not be more than 60
    os: {u'version': u'6.3', u'name': u'WINNT'} reason: delayed
    os: {u'version': u'10.0', u'name': u'WINNT'} reason: immediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: shutdown
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: shutdown
    os: {u'version': u'10.0', u'name': u'WINNT'} reason: delayed
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: delayed
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: delayed
    os: {u'version': u'6.3', u'name': u'WINNT'} reason: immediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: shutdown
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: delayed
    
    
    Ping must countain at least one of the failures
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: shutdown
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: shutdown
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: immediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: shutdown
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: shutdown
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: immediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: immediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: shutdown
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: immediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: immediate
    
    
    clientId must not be empty
    os: None reason: immediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: immediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: immediate
    os: {u'version': u'6.1', u'name': u'WINNT'} reason: immediate
    
    
    OS must not be empty
    os: None reason: immediate
    os: None reason: immediate
    os: None reason: shutdown
    os: None reason: shutdown
    os: None reason: immediate
    os: None reason: shutdown
    os: None reason: shutdown
    os: None reason: shutdown
    os: None reason: immediate
    
    


# Compute pings count per day
This includes showing diagrams and printing stats


```python
from datetime import datetime

def pingsCountPerDay(pings):
    return pings.map(lambda ping: ping["meta/submissionDate"]).countByValue()

resultDictionary = pingsCountPerDay(cachedData)
```

```python
import matplotlib.dates as mdates
def plotlistofTuples(listOfTuples, title="", inColor='blue'):
    keys = [t[0] for t in listOfTuples]
    values = [t[1] for t in listOfTuples]

    plt.figure(1)
    fig = plt.gcf()
    fig.set_size_inches(15, 7)

    plt.title(title)
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter('%m/%d/%Y'))
    plt.bar(range(len(listOfTuples)), values, align='center', color=inColor)
    plt.xticks(range(len(listOfTuples)), keys, rotation=90)

```

```python
plotlistofTuples(sorted(resultDictionary.items(), key=lambda tup: tup[0]), "Pings count per day") 
plt.xlabel('meta/submissionDate') 
plt.ylabel('pings count')
plt.show()
```


![png](images/output_20_0.png)



```python
pingsPerDaySeries = pd.Series(resultDictionary.values())
pingsPerDaySeries.describe([.25, .5, .75, .95])
```




    count    3.000000e+01
    mean     1.025680e+06
    std      1.028015e+06
    min      2.000000e+00
    25%      5.970000e+02
    50%      6.205345e+05
    75%      1.962817e+06
    95%      2.665410e+06
    max      2.998241e+06
    dtype: float64



# Compute how many clients are reporting


```python
def getClients(pings):
    clients = pings.map(lambda ping: ping["clientId"]).distinct()
    return clients
```

```python
clientsCount = getClients(cachedData).count()
print "Clients number = " + str(clientsCount)
```
    Clients number = 2413716


# Compute average number of pings per client per day

* We expect at most 24 pings per day as we send no more than one "health" ping per hour
* This includes showing diagrams and printing stats




```python
from collections import Counter

def getAvgPerDate(iterable):
    aggregare = Counter(iterable)
    result = sum(aggregare.values()) * 1.0 / len(aggregare)
    return result

def pingsPerClientPerDay(pings, date):
    return pings.map(lambda ping: (ping["clientId"], ping[date])).groupByKey()

def avgPingsPerClientPerDay(pings, date):
    idDateRDD = pingsPerClientPerDay(pings, date)
    return idDateRDD.map(lambda pair: getAvgPerDate(pair[1])).collect()
```

```python
def plotAvgPingPerDateDistr(pings, date):
    PINGS_COUNT_PER_DAY = 24
    resultDistributionList = avgPingsPerClientPerDay(pings, date)
    values = [v for v in resultDistributionList if v > PINGS_COUNT_PER_DAY]
    print date + " : clients sending too many \"health\" pings per day - " + str(len(values))
    if len(values) > 0:
        plt.title("Average pings per day per client")
        plt.ylabel('log(average ping count)')
        plt.xlabel('clientId (anonymized)')
        plt.yscale('log')
        plt.plot(sorted(values))  
        plt.show()
```

```python
plotAvgPingPerDateDistr(cachedData, "meta/submissionDate")
plotAvgPingPerDateDistr(cachedData, "creationDate")
```
    meta/submissionDate : clients sending too many "health" pings per day - 8248




![png](images/output_28_1.png)


    creationDate : clients sending too many "health" pings per day - 3




![png](images/output_28_3.png)


Turns out, clients submit health pings properly (less that 24/day) but we get them on server with some delay

# Daily active Health ping clients against DAU

ratio = DAU beta / health ping clients count. 

DAU beta from here: https://sql.telemetry.mozilla.org/queries/15337/source#table
health ping clients count: precomputed


```python
ratio = [('20170810', 0.75), ('20170811', 0.35), \
         ('20170812', 0.4), ('20170813', 0.59), ('20170814', 0.43), ('20170815', 0.73), ('20170816', 0.78), \
         ('20170817', 0.52), ('20170818', 0.38), ('20170819', 0.46), ('20170820', 0.62), ('20170821', 0.43), \
         ('20170822', 0.42), ('20170823', 0.45)]
```

```python
plotlistofTuples(sorted(ratio), inColor='red')
plt.xlabel('meta/submissionDate') 
plt.ylabel('ratio')

```




    <matplotlib.text.Text at 0x7f5dac59ac90>





![png](images/output_33_1.png)


Conclusion: Almost half of the DAU submits health ping. It is seemsed to be because of sendFailure types: eChannelOpen and eUnreachable. 

* eChannelOpen - This error happen when we failed to open channel, maybe it is better to avoid closing the channel and reuse existed channels instead. 

* eUnreachable - Probably internet connection problems. 


```python

```
