---
title: Bug 1381516 - How Bad Is Bug 1380880?
authors:
- chutten
tags:
- investigation
- keyed histograms
- archaeology
created_at: 2017-07-17 00:00:00
updated_at: 2017-07-17 16:05:47.117913
tldr: How broadly and how deeply do the effects of bug 1380880 extend?
---
### How many keyed histograms have identical keys across processes?

In [bug 1380880](https://bugzilla.mozilla.org/show_bug.cgi?id=1380880) :billm found that keyed histograms recorded on different processes would be aggregated together if their keys matched.

How often does this happen in practice? How long has this been happening?


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
### Which keyed histograms share keys across processes?

The whole child-process client aggregation thing was introduced by [bug 1218576](https://bugzilla.mozilla.org/show_bug.cgi?id=1218576) back in September of 2016 for Firefox 52. So that's the earliest this could have started.


```python
pings = Dataset.from_source("telemetry") \
    .where(docType='main') \
    .where(appVersion=lambda x: x.startswith("52")) \
    .where(appUpdateChannel="nightly") \
    .records(sc, sample=0.1)
```
    fetching 13254.61440MB in 54449 files...



```python
def set_of_hgram_key_tuples(payload):
    return set((kh_name, key) for (kh_name, v) in payload['keyedHistograms'].items() for key in v.keys())

def get_problem_combos(aping):
    parent_tuples = set_of_hgram_key_tuples(aping['payload'])
    child_tuples = [set_of_hgram_key_tuples(pp) for (process_name, pp) in aping['payload'].get('processes', {}).items() if 'keyedHistograms' in pp]
    problem_combos = set.intersection(*(child_tuples + [parent_tuples])) if len(child_tuples) else set()
    return problem_combos
```

```python
problem_combos = pings.flatMap(get_problem_combos)
```

```python
problem_combos.cache()
```




    PythonRDD[15] at RDD at PythonRDD.scala:48



Alright, let's get a list of the most commonly-seen histograms:


```python
sorted(problem_combos.map(lambda c: (c[0], 1)).countByKey().iteritems(), key=lambda x: x[1], reverse=True)
```




    [(u'IPC_MESSAGE_SIZE', 396905),
     (u'BLOCKED_ON_PLUGIN_MODULE_INIT_MS', 72248),
     (u'SYNC_WORKER_OPERATION', 47653),
     (u'MESSAGE_MANAGER_MESSAGE_SIZE2', 35884),
     (u'CONTENT_LARGE_PAINT_PHASE_WEIGHT', 13846),
     (u'MEDIA_CODEC_USED', 1030),
     (u'CANVAS_WEBGL_FAILURE_ID', 289),
     (u'VIDEO_INFERRED_DECODE_SUSPEND_PERCENTAGE', 288),
     (u'VIDEO_HIDDEN_PLAY_TIME_PERCENTAGE', 288),
     (u'VIDEO_INTER_KEYFRAME_MAX_MS', 208),
     (u'CANVAS_WEBGL_ACCL_FAILURE_ID', 183),
     (u'JS_TELEMETRY_ADDON_EXCEPTIONS', 150),
     (u'VIDEO_SUSPEND_RECOVERY_TIME_MS', 117),
     (u'VIDEO_INTER_KEYFRAME_AVERAGE_MS', 111),
     (u'PRINT_DIALOG_OPENED_COUNT', 4),
     (u'PRINT_COUNT', 2)]



More verbosely, what are the 20 most-commonly-seen histogram,key pairs:


```python
sorted(problem_combos.map(lambda c: (c, 1)).countByKey().iteritems(), key=lambda x: x[1], reverse=True)[:20]
```




    [((u'IPC_MESSAGE_SIZE', u'PLayerTransaction::Msg_Update'), 185499),
     ((u'IPC_MESSAGE_SIZE', u'PBrowser::Msg_AsyncMessage'), 133954),
     ((u'IPC_MESSAGE_SIZE', u'PLayerTransaction::Msg_UpdateNoSwap'), 64489),
     ((u'SYNC_WORKER_OPERATION', u'WorkerCheckAPIExposureOnMainThread'), 41428),
     ((u'MESSAGE_MANAGER_MESSAGE_SIZE2', u'SessionStore:update'), 24408),
     ((u'BLOCKED_ON_PLUGIN_MODULE_INIT_MS', u'Shockwave Flash23.0.0.185'), 21854),
     ((u'BLOCKED_ON_PLUGIN_MODULE_INIT_MS', u'Shockwave Flash23.0.0.205'), 18713),
     ((u'IPC_MESSAGE_SIZE', u'PContent::Msg_AsyncMessage'), 12066),
     ((u'BLOCKED_ON_PLUGIN_MODULE_INIT_MS', u'Shockwave Flash23.0.0.162'), 11700),
     ((u'MESSAGE_MANAGER_MESSAGE_SIZE2', u'sdk/remote/process/message'), 7776),
     ((u'SYNC_WORKER_OPERATION', u'XHR'), 5866),
     ((u'BLOCKED_ON_PLUGIN_MODULE_INIT_MS', u'Shockwave Flash23.0.0.207'), 4580),
     ((u'CONTENT_LARGE_PAINT_PHASE_WEIGHT', u'flb,r'), 1978),
     ((u'CONTENT_LARGE_PAINT_PHASE_WEIGHT', u'dl,flb'), 1978),
     ((u'CONTENT_LARGE_PAINT_PHASE_WEIGHT', u'dl'), 1978),
     ((u'CONTENT_LARGE_PAINT_PHASE_WEIGHT', u'flb'), 1978),
     ((u'CONTENT_LARGE_PAINT_PHASE_WEIGHT', u'r'), 1978),
     ((u'CONTENT_LARGE_PAINT_PHASE_WEIGHT', u'dl,r'), 1978),
     ((u'CONTENT_LARGE_PAINT_PHASE_WEIGHT', u'dl,flb,r'), 1978),
     ((u'BLOCKED_ON_PLUGIN_MODULE_INIT_MS', u'Shockwave Flash22.0.0.209'), 1642)]



#### Has this been a problem this whole time?

From earlier we note that `IPC_MESSAGE_SIZE/PLayerTransaction::Msg_Update` is the most common "present on multiple processes" combination.

To see if we've had this problem the whole time, how many pings have these messages in both parent and content, and whose histograms have identical sums?


```python
def relevant_ping(p):
    parent = p.get('payload', {}).get('keyedHistograms', {}).get('IPC_MESSAGE_SIZE', {}).get('PLayerTransaction::Msg_Update')
    content = p.get('payload', {}).get('processes', {}).get('content', {}).get('keyedHistograms', {}).get('IPC_MESSAGE_SIZE', {}).get('PLayerTransaction::Msg_Update')
    return parent is not None and content is not None and parent['sum'] == content['sum']
    
relevant_pings = pings.filter(relevant_ping)
```

```python
relevant_pings.count()
```




    149126



Yup, it appears as though we've had this problem since nightly/52.

### How about recently?


```python
modern_pings = Dataset.from_source("telemetry") \
    .where(docType='main') \
    .where(submissionDate="20170716") \
    .records(sc, sample=0.01)
```
    fetching 7012.25715MB in 1970 files...



```python
modern_combos = modern_pings.flatMap(get_problem_combos)
```

```python
modern_combos.cache()
```




    PythonRDD[51] at RDD at PythonRDD.scala:48




```python
sorted(modern_combos.map(lambda c: (c[0], 1)).countByKey().iteritems(), key=lambda x: x[1], reverse=True)
```




    [(u'NOTIFY_OBSERVERS_LATENCY_MS', 72463),
     (u'DOM_SCRIPT_SRC_ENCODING', 33021),
     (u'FX_SESSION_RESTORE_CONTENT_COLLECT_DATA_MS', 30709),
     (u'CONTENT_LARGE_PAINT_PHASE_WEIGHT', 11613),
     (u'IPC_WRITE_MAIN_THREAD_LATENCY_MS', 11186),
     (u'MAIN_THREAD_RUNNABLE_MS', 7872),
     (u'IPC_READ_MAIN_THREAD_LATENCY_MS', 6646),
     (u'SYNC_WORKER_OPERATION', 5614),
     (u'IPC_SYNC_RECEIVE_MS', 4227),
     (u'IPC_MESSAGE_SIZE', 3514),
     (u'BLOCKED_ON_PLUGIN_MODULE_INIT_MS', 2377),
     (u'IPC_SYNC_MESSAGE_MANAGER_LATENCY_MS', 902),
     (u'IPC_SYNC_MAIN_LATENCY_MS', 833),
     (u'IDLE_RUNNABLE_BUDGET_OVERUSE_MS', 701),
     (u'MESSAGE_MANAGER_MESSAGE_SIZE2', 615),
     (u'FX_TAB_REMOTE_NAVIGATION_DELAY_MS', 433),
     (u'CANVAS_WEBGL_FAILURE_ID', 138),
     (u'CANVAS_WEBGL_ACCL_FAILURE_ID', 110),
     (u'MEDIA_CODEC_USED', 20),
     (u'IPC_SYNC_LATENCY_MS', 9),
     (u'VIDEO_HIDDEN_PLAY_TIME_PERCENTAGE', 8),
     (u'VIDEO_INFERRED_DECODE_SUSPEND_PERCENTAGE', 8),
     (u'PRINT_DIALOG_OPENED_COUNT', 2)]




```python
sorted(modern_combos.map(lambda c: (c, 1)).countByKey().iteritems(), key=lambda x: x[1], reverse=True)[:20]
```




    [((u'DOM_SCRIPT_SRC_ENCODING', u'UTF-8'), 16824),
     ((u'DOM_SCRIPT_SRC_ENCODING', u'windows-1252'), 16165),
     ((u'NOTIFY_OBSERVERS_LATENCY_MS', u'cycle-collector-begin'), 13727),
     ((u'NOTIFY_OBSERVERS_LATENCY_MS', u'garbage-collection-statistics'), 13150),
     ((u'NOTIFY_OBSERVERS_LATENCY_MS', u'cycle-collector-forget-skippable'),
      12719),
     ((u'NOTIFY_OBSERVERS_LATENCY_MS', u'inner-window-destroyed'), 8619),
     ((u'NOTIFY_OBSERVERS_LATENCY_MS', u'tab-content-frameloader-created'), 7924),
     ((u'FX_SESSION_RESTORE_CONTENT_COLLECT_DATA_MS', u'historychange'), 7537),
     ((u'FX_SESSION_RESTORE_CONTENT_COLLECT_DATA_MS', u'pageStyle'), 7390),
     ((u'FX_SESSION_RESTORE_CONTENT_COLLECT_DATA_MS', u'scroll'), 7389),
     ((u'FX_SESSION_RESTORE_CONTENT_COLLECT_DATA_MS', u'storage'), 7380),
     ((u'IPC_WRITE_MAIN_THREAD_LATENCY_MS', u'PLayerTransaction::Msg_Update'),
      6284),
     ((u'SYNC_WORKER_OPERATION', u'WorkerCheckAPIExposureOnMainThread'), 4926),
     ((u'NOTIFY_OBSERVERS_LATENCY_MS', u'content-document-global-created'), 4486),
     ((u'IPC_SYNC_RECEIVE_MS', u'???'), 4227),
     ((u'IPC_READ_MAIN_THREAD_LATENCY_MS', u'PCompositorBridge::Msg_DidComposite'),
      3523),
     ((u'NOTIFY_OBSERVERS_LATENCY_MS', u'document-element-inserted'), 3498),
     ((u'IPC_WRITE_MAIN_THREAD_LATENCY_MS',
       u'PCompositorBridge::Msg_PTextureConstructor'),
      2231),
     ((u'IPC_MESSAGE_SIZE', u'PBrowser::Msg_AsyncMessage'), 2083),
     ((u'IPC_READ_MAIN_THREAD_LATENCY_MS', u'PBrowser::Msg_AsyncMessage'), 2031)]



The behaviour still exists, though this suggests that plugins and ipc messages are now less common. Instead we see more latency probes.
