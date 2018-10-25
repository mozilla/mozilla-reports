---
title: TELEMETRY_SEND Failure Logs
authors:
- chutten
tags:
- log
- failure
- telemetry
- send
created_at: 2017-05-05 00:00:00
updated_at: 2017-05-05 12:51:21.213942
tldr: What kind of failures are we seeing when people fail to send Telemetry pings?
  (bug 1319026)
---
### TELEMETRY_SEND Failure Logs

[Bug 1319026](https://bugzilla.mozilla.org/show_bug.cgi?id=1319026) introduced logs to try and nail down what kinds of failures users experience when trying to send Telemetry pings. Let's see what we've managed to collect.


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
    Unable to parse whitelist (/mnt/anaconda2/lib/python2.7/site-packages/moztelemetry/histogram-whitelists.json). Assuming all histograms are acceptable.



```python
pings = Dataset.from_source("telemetry") \
    .where(docType='main') \
    .where(appUpdateChannel='nightly') \
    .where(submissionDate=lambda x: x >= "20170429") \
    .where(appBuildId=lambda x: x >= '20170429') \
    .records(sc, sample=1)
```

```python
subset = get_pings_properties(pings, ["clientId",
                                      "environment/system/os/name",
                                      "payload/log"])
```

```python
log_entries = subset\
    .flatMap(lambda p: [] if p['payload/log'] is None else [l for l in p['payload/log'] if l[0] == 'TELEMETRY_SEND_FAILURE'])
```

```python
log_entries = log_entries.cache()
```

```python
error_counts = log_entries.map(lambda l: (tuple(l[2:]), 1)).countByKey()
```

```python
entries_count = log_entries.count()
sorted(map(lambda i: ('{:.2%}'.format(1.0 * i[-1] / entries_count), i), error_counts.iteritems()), key=lambda x: x[1][1], reverse=True)
```




    [('72.16%', ((u'errorhandler', u'error'), 530178)),
     ('27.04%', ((u'errorhandler', u'timeout'), 198698)),
     ('0.73%', ((u'5xx failure', u'504'), 5327)),
     ('0.07%', ((u'errorhandler', u'abort'), 530)),
     ('0.00%', ((u"4xx 'failure'", u'403'), 7)),
     ('0.00%', ((u'5xx failure', u'502'), 3))]



#### Conclusion

Alrighty, looks like we're mostly "error". Not too helpful, but does narrow things down a bit.

"timeout" is the reason for more than one in every four failures. That's a smaller cohort than I'd originally thought.

A few Gateway Timeouts (504) which could be server load, very few aborts, and essentially no Forbidden (403) or Bad Gateway (502).
