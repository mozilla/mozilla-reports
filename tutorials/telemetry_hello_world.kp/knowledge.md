---
title: Telemetry Hello World
authors:
- vitillo
tags:
- tutorial
- examples
- telemetry
- spark
created_at: 2016-03-10 00:00:00
updated_at: 2017-02-24 18:00:25.791035
tldr: Brief introduction to Spark and Telemetry in Python
---
### Telemetry Hello World

This is a very a brief introduction to Spark and Telemetry in Python. You should have a look at the [tutorial](https://gist.github.com/vitillo/25a20b7c8685c0c82422) in Scala and the associated [talk](http://www.slideshare.net/RobertoAgostinoVitil/spark-meets-telemetry) if you are interested to learn more about Spark.


```python
import ujson as json
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import plotly.plotly as py

from plotly.graph_objs import *
from moztelemetry import get_pings_properties, get_one_ping_per_client
from moztelemetry.dataset import Dataset

%matplotlib inline
```
### Basics

The goal of this example is to plot the startup distribution for each OS. Let's see how many parallel workers we have at our disposal:


```python
sc.defaultParallelism
```
Let's fetch 10% of Telemetry submissions for a given submission date...


```python
Dataset.from_source("telemetry").schema
```

```python
pings = Dataset.from_source("telemetry").where(
    docType='main',
    submissionDate="20161101",
    appUpdateChannel="nightly"
).records(sc, sample=0.1)
```
... and extract only the attributes we need from the Telemetry submissions:


```python
subset = get_pings_properties(pings, ["clientId",
                                      "environment/system/os/name",
                                      "payload/simpleMeasurements/firstPaint"])
```
Let's filter out submissions with an invalid startup time:


```python
subset = subset.filter(lambda p: p.get("payload/simpleMeasurements/firstPaint", -1) >= 0)
```
To prevent pseudoreplication, let's consider only a single submission for each client. As this step requires a distributed shuffle, it should always be run only after extracting the attributes of interest with *get_pings_properties*.


```python
subset = get_one_ping_per_client(subset)
```
Caching is fundamental as it allows for an iterative, real-time development workflow:


```python
cached = subset.cache()
```
How many pings are we looking at?


```python
cached.count()
```
Let's group the startup timings by OS:


```python
grouped = cached.map(lambda p: (p["environment/system/os/name"], p["payload/simpleMeasurements/firstPaint"])).groupByKey().collectAsMap()
```
And finally plot the data:


```python
frame = pd.DataFrame({x: np.log10(pd.Series(list(y))) for x, y in grouped.items()})
plt.figure(figsize=(17, 7))
frame.boxplot(return_type="axes")
plt.ylabel("log10(firstPaint)")
plt.show()
```
You can also create interactive plots with [plotly](https://plot.ly/):


```python
fig = plt.figure(figsize=(18, 7))
frame["Windows_NT"].plot(kind="hist", bins=50)
plt.title("startup distribution for Windows")
plt.ylabel("count")
plt.xlabel("log10(firstPaint)")
py.iplot_mpl(fig, strip_style=True)
```
### Histograms

Let's extract a histogram from the submissions:


```python
histograms = get_pings_properties(pings, "payload/histograms/GC_MARK_MS", with_processes=True)
```
The API returns three distinct histograms for each submission:
- a histogram for the parent process (*GC_MARK_MS_parent*)
- an aggregated histogram for the child processes (*GC_MARK_MS_children*)
- the aggregate of the parent and child histograms (*GC_MARK*)

Let's aggregate the histogram over all submissions and plot it:


```python
def aggregate_arrays(xs, ys):
    if xs is None:
        return ys
    
    if ys is None:
        return xs
    
    return xs + ys
    
aggregate = histograms.map(lambda p: p["payload/histograms/GC_MARK_MS"]).reduce(aggregate_arrays)
aggregate.plot(kind="bar", figsize=(15, 7))
```
Keyed histograms follow a similar pattern. To extract a keyed histogram for which we know the key/label we are interested in:


```python
histograms = get_pings_properties(pings, "payload/keyedHistograms/SUBPROCESS_ABNORMAL_ABORT/plugin", with_processes=True)
```
List all keys/labels for a keyed histogram:


```python
keys = pings.flatMap(lambda p: p["payload"].get("keyedHistograms", {}).get("MISBEHAVING_ADDONS_JANK_LEVEL", {}).keys())
keys = keys.distinct().collect()
```

```python
keys[:5]
```
Retrieve the histograms for a set of labels:


```python
properties = map(lambda k: "payload/keyedHistograms/{}/{}".format("MISBEHAVING_ADDONS_JANK_LEVEL", k), keys[:5])
```

```python
histograms = get_pings_properties(pings, properties, with_processes=True)
```
