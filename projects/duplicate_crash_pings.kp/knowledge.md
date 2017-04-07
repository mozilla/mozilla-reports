---
title: Duplicate Crash Pings
authors:
- chutten
tags:
- duplicate
- dedupe
- crash
created_at: 2017-04-07 00:00:00
updated_at: 2017-04-07 13:38:11.063912
tldr: When the patches landed to dedupe crash pings (bug 1354468 has the list), did
  they work?
thumbnail: images/output_11_0.png
---
### How many duplicate crash pings are we receiving on Nightly/Aurora from 2017-03-28 - 2017-04-07?


```python
import pandas as pd
import numpy as np
import matplotlib

from matplotlib import pyplot as plt
from moztelemetry.dataset import Dataset
from moztelemetry import get_pings_properties, get_one_ping_per_client
```
    Unable to parse whitelist (/mnt/anaconda2/lib/python2.7/site-packages/moztelemetry/histogram-whitelists.json). Assuming all histograms are acceptable.



```python
pings = Dataset.from_source("telemetry")\
    .where(docType='crash')\
    .where(appName='Firefox')\
    .where(appUpdateChannel=lambda x: x == 'nightly' or x == 'aurora')\
    .where(appBuildId=lambda x: x > '20170210' and x < '20170408')\
    .records(sc, sample=1)
```

```python
subset = get_pings_properties(pings, ["id", "application/channel", "application/buildId"])
```
To get the proportions of each builds' crash pings that were duplicated, get the full count and the deduplicated count per-build.


```python
build_counts = subset.map(lambda s: ((s["application/buildId"][:8], s["application/channel"]), 1)).countByKey()
```

```python
deduped_counts = subset\
    .map(lambda s: (s["id"], s))\
    .reduceByKey(lambda a, b: a)\
    .map(lambda pair: pair[1])\
    .map(lambda s: ((s["application/buildId"][:8], s["application/channel"]), 1)).countByKey()
```

```python
from datetime import datetime
```

```python
sorted_counts = sorted(build_counts.iteritems())
```

```python
sorted_deduped = sorted(deduped_counts.iteritems())
```

```python
plt.figure(figsize=(16, 10))
plt.plot([datetime.strptime(k[0], '%Y%m%d') for k,v in sorted_deduped if k[1] == 'nightly'], [100.0 * (build_counts[k] - v) / build_counts[k] for k,v in sorted_deduped if k[1] == 'nightly'])
plt.plot([datetime.strptime(k[0], '%Y%m%d') for k,v in sorted_deduped if k[1] == 'aurora'], [100.0 * (build_counts[k] - v) / build_counts[k] for k,v in sorted_deduped if k[1] == 'aurora'])
plt.ylabel("% of submitted crash pings that are duplicate")
plt.xlabel("Build date")
plt.show()
```


![png](images/output_11_0.png)


#### Conclusion:

Looks like something happened on March 30 on Nightly and April 5 on Aurora to drastically reduce the proportion of duplicate crash pings we've been seeing.
