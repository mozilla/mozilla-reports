---
title: Prefer repartition to coalesce in Spark
authors:
- Ryan Harter (:harter)
tags:
- Spark
- ATMO
created_at: 2017-03-02 00:00:00
updated_at: 2017-03-02 18:58:11.260287
tldr: When saving data to parquet in Spark/ATMO, avoid using coalesce.
---
# Introduction

I ran into some Spark weirdness when working on some ETL.
Specifically, when repartitioning a parquet file with `coalesce()`, the parallelism for the entire job (including upstream tasks) was constrained by the number of coalesce partitions.
Instead, I expected the upstream jobs to use all available cores.
We should be limited by the number of file partitions only when its time to actually write the file.

It's probably easier if I demonstrate.
Below I'll create a small example dataframe containing 10 rows.
I'll map a slow function over the example dataframe in a few different ways.
I'd expect these calculations to take a fixed amount of time, since they're happening in parallel.
However, for one example, **execution time will increase linearly with the number of rows**.

## Setup


```python
import time
from pyspark.sql.types import LongType

path = "~/tmp.parquet"
```

```python
sc.defaultParallelism
```




    32




```python
def slow_func(ping):
    """Identity function that takes 1s to return"""
    time.sleep(1)
    return(ping)
```

```python
def timer(func):
    """Times the execution of a function"""
    start_time = time.time()
    func()
    return time.time() - start_time
```

```python
# Example usage:
timer(lambda: slow_func(10))
```




    1.001082181930542




```python
def create_frame(rdd):
    return sqlContext.createDataFrame(rdd, schema=LongType())
```
## Simple RDD

First, let's look at a simple RDD. Everything seems to work as expected here. Execution time levels off to ~3.7 as the dataset increases:


```python
map(lambda x: timer(lambda: sc.parallelize(range(x)).map(slow_func).take(x)), range(10))
```




    [0.07758498191833496,
     118.664391040802,
     2.453991174697876,
     2.390385866165161,
     2.3567309379577637,
     2.3262758255004883,
     2.3200111389160156,
     3.3115720748901367,
     3.3115429878234863,
     3.274951934814453]



## Spark DataFrame

Let's create a Spark DataFrame and write the contents to parquet without any modification. Again, things seem to be behaving here. Execution time is fairly flat.


```python
map(lambda x: timer(lambda: create_frame(sc.parallelize(range(x)))\
                                .coalesce(1).write.mode("overwrite").parquet(path)),
    range(10))
```




    [5.700469017028809,
     1.5091090202331543,
     1.4622771739959717,
     1.448883056640625,
     1.4437789916992188,
     1.4351229667663574,
     1.4368910789489746,
     1.4349958896636963,
     1.4199819564819336,
     1.4395389556884766]



## Offending Example

Now, let's map the slow function over the DataFrame before saving. This should increase execution time by one second for every dataset. However, it looks like **execution time is increasing by one second for each row**.


```python
map(lambda x: timer(lambda: create_frame(sc.parallelize(range(x))\
                                .map(slow_func))\
                                .coalesce(1).write.mode("overwrite").parquet(path)),
    range(10))
```




    [1.42529296875,
     2.436065912246704,
     3.3423829078674316,
     4.332568883895874,
     5.268526077270508,
     6.280202865600586,
     7.169728994369507,
     8.18229603767395,
     9.098582029342651,
     10.119444131851196]



## Repartition fixes the issue

Using `repartition` instead of `coalesce` fixes the issue.


```python
map(lambda x: timer(lambda: create_frame(sc.parallelize(range(x))\
                                .map(slow_func))\
                                .repartition(1).write.mode("overwrite").parquet(path)),
    range(10))
```




    [0.8304200172424316,
     1.276075839996338,
     1.2515549659729004,
     1.2429919242858887,
     1.2587580680847168,
     1.2490499019622803,
     1.6439399719238281,
     1.229665994644165,
     1.2340660095214844,
     1.2454640865325928]




```python
sc.cancelAllJobs()
```
