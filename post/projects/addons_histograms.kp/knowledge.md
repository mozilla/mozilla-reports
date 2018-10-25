---
title: What, if anything, Useful do we get from Addons Histograms?
authors:
- chutten
tags:
- addons
- firefox
- telemetry
created_at: 2017-04-04 00:00:00
updated_at: 2017-04-04 12:15:18.538654
tldr: We don't get a lot of call for addonHistograms anymore. Maybe we should ditch
  'em.
---
### Motivation

Can we get rid of addonHistograms?

### What, if anything, Useful do we get from Addons Histograms?


```python
import pandas as pd
import numpy as np
import matplotlib

from matplotlib import pyplot as plt
from moztelemetry.dataset import Dataset
from moztelemetry import get_pings_properties, get_one_ping_per_client
```
    Unable to parse whitelist (/mnt/anaconda2/lib/python2.7/site-packages/moztelemetry/histogram-whitelists.json). Assuming all histograms are acceptable.


Let's just look at a non-representative 10% of main pings gathered on a recent Tuesday.


```python
pings = Dataset.from_source("telemetry") \
    .where(docType='main') \
    .where(submissionDate="20170328") \
    .records(sc, sample=0.1)
```

```python
subset = get_pings_properties(pings, ["payload/addonHistograms"])
```
#### How many pings even have addonHistograms?


```python
full_count = subset.count()
full_count
```




    37815981




```python
filtered = subset.filter(lambda p: p["payload/addonHistograms"] is not None)
filtered_count = filtered.count()
filtered_count
```




    25794




```python
1.0 * filtered_count / full_count
```




    0.0006820925787962502



#### So, not many. Which addons are they from?


```python
addons = filtered.flatMap(lambda p: p['payload/addonHistograms'].keys()).map(lambda key: (key, 1))
```

```python
addons.countByKey()
```




    defaultdict(int,
                {u'Firebug': 92,
                 u'shumway@research.mozilla.org': 15,
                 u'uriloader@pdf.js': 4})



Wow, so most of those addonHistograms sections are empty.

...And those that aren't are from defunct data collection sources. Looks like we can remove this without too many complaint. Excellent.
