---
title: update ping (reason = success) validation on Nightly
authors:
- dexter
tags:
- firefox
- update
- latency
created_at: 2016-09-14 00:00:00
updated_at: 2017-09-19 11:26:30.321006
tldr: This notebook verifies that the `update` ping with `reason = success` behaves
  as expected on Nightly.
thumbnail: images/output_23_0.png
---
# Validate 'update' ping submissions on Nightly (`reason = success`)

This analysis validates the `update` ping with `reason = success`, which was introduced in [bug 1380256](https://bugzilla.mozilla.org/show_bug.cgi?id=1380256) and should be sent every time an update is applied after the browser is restarted. We are going to verify that:

- the ping is received within a reasonable time after the browser is started;
- we receive one ping per update;
- that the payload looks ok;
- check if the volume of update pings is within the expected range by cross-checking it with the update ping with `reason = ready`;
- that we don't receive many duplicates.


```python
import ujson as json
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import plotly.plotly as py
import IPython

from plotly.graph_objs import *
from moztelemetry import get_pings_properties, get_one_ping_per_client
from moztelemetry.dataset import Dataset
from datetime import datetime, timedelta
from email.utils import parsedate_tz, mktime_tz, formatdate

%matplotlib inline
IPython.core.pylabtools.figsize(16, 7)
```
The `update` ping with `reason = success` landed on the Nightly channel on the 1st of September, 2017. Let's get the first full-week of data after that date: 3rd-9th September, 2017. Restrict to the data coming from the Nightly builds after the day the ping landed.


```python
MIN_DATE = "20170903"
MAX_DATE = "20170910"

update_pings = Dataset.from_source("telemetry") \
    .where(docType="update") \
    .where(appUpdateChannel="nightly") \
    .where(submissionDate=lambda x: MIN_DATE <= x < MAX_DATE) \
    .where(appBuildId=lambda x: MIN_DATE <= x < MAX_DATE) \
    .records(sc, sample=1.0)
```
    fetching 256.36621MB in 8021 files...


### Define some misc functions


```python
def pct(a, b):
    return 100.0 * a / b

def dedupe(pings, duping_key):
    return pings\
            .map(lambda p: (p[duping_key], p))\
            .reduceByKey(lambda a, b: a if a["meta/Timestamp"] < b["meta/Timestamp"] else b)\
            .map(lambda pair: pair[1])
```
Misc functions to plot the CDF of the submission delay.


```python
MAX_DELAY_S = 60 * 60 * 96.0
HOUR_IN_S = 60 * 60.0

def setup_plot(title, max_x, area_border_x=0.1, area_border_y=0.1):
    plt.title(title)
    plt.xlabel("Delay (hours)")
    plt.ylabel("% of pings")

    plt.xticks(range(0, int(max_x) + 1, 2))
    plt.yticks(map(lambda y: y / 20.0, range(0, 21, 1)))

    plt.ylim(0.0 - area_border_y, 1.0 + area_border_y)
    plt.xlim(0.0 - area_border_x, max_x + area_border_x)

    plt.grid(True)

def plot_cdf(data, **kwargs):
    sortd = np.sort(data)
    ys = np.arange(len(sortd))/float(len(sortd))

    plt.plot(sortd, ys, **kwargs)
    
def calculate_submission_delay(p):
    created = datetime.fromtimestamp(p["meta/creationTimestamp"] / 1000.0 / 1000.0 / 1000.0)
    received = datetime.fromtimestamp(p["meta/Timestamp"] / 1000.0 / 1000.0 / 1000.0)
    sent = datetime.fromtimestamp(mktime_tz(parsedate_tz(p["meta/Date"]))) if p["meta/Date"] is not None else received
    clock_skew = received - sent

    return (received - created - clock_skew).total_seconds()
```
### Validate the ping payload
Check that the payload section contains the right entries with consistent values.


```python
subset = get_pings_properties(update_pings, ["id",
                                             "clientId",
                                             "meta/creationTimestamp",
                                             "meta/Date",
                                             "meta/Timestamp",
                                             "application/buildId",
                                             "application/channel",
                                             "application/version",
                                             "environment/system/os/name",
                                             "payload/reason",
                                             "payload/targetBuildId",
                                             "payload/targetChannel",
                                             "payload/targetVersion",
                                             "payload/previousBuildId",
                                             "payload/previousChannel",
                                             "payload/previousVersion"])
```

```python
ping_success = subset.filter(lambda p: p.get("payload/reason") == "success")
ping_ready = subset.filter(lambda p: p.get("payload/reason") == "ready")

ping_success_count = ping_success.count()
ping_ready_count = ping_ready.count()
ping_count = ping_ready_count + ping_success_count
# As a safety precaution, assert that we only received the
# reasons we were looking for.
assert ping_count == subset.count()
```
Quantify the percentage of duplicate pings we're receiving. We don't expect this value to be greater than ~1%, which is the amount we usually get from `main` and `crash`: as a rule of thumb, we threat anything less than 1% as *probably* well behaving.


```python
deduped_subset = dedupe(ping_success, "id")
deduped_count = deduped_subset.count()
print("Percentage of duplicate pings: {:.3f}".format(100.0 - pct(deduped_count, ping_success_count)))
```
    Percentage of duplicate pings: 0.078


The percentage of duplicate pings is within the expected range. Move on and verify the payload of the `update` pings.


```python
def validate_update_payload(p):
    PAYLOAD_KEYS = [
        "payload/reason",
        "payload/previousBuildId",
        "payload/previousChannel",
        "payload/previousVersion"
    ]

    # All the payload keys needs to be strings.
    for k in PAYLOAD_KEYS:
        if not isinstance(p.get(k), basestring):
            return ("'{}' is not a string".format(k), 1)
        
    # For Nightly, the previous channel should be the same as the
    # application channel.
    if p.get("payload/previousChannel") != p.get("application/channel"):
        return ("Previous channel mismatch: expected {} got {}"\
                .format(p.get("payload/previousChannel"), p.get("application/channel")), 1)
                
    # The previous buildId must be smaller than the application build id.
    if p.get("payload/previousBuildId") > p.get("application/buildId"):
        return ("Previous buildId mismatch: {} must be older than {}"\
                .format(p.get("payload/previousBuildId"), p.get("application/buildId")), 1)
    
    return ("Ok", 1)

validation_results = deduped_subset.map(validate_update_payload).countByKey()
for k, v in sorted(validation_results.iteritems()):
    print("{}:\t{:.3f}%".format(k, pct(v, ping_success_count)))
```
    Ok:	99.875%
    Previous buildId mismatch: 20170903140023 must be older than 20170903100443:	0.001%
    Previous buildId mismatch: 20170904100131 must be older than 20170903220032:	0.001%
    Previous buildId mismatch: 20170904220027 must be older than 20170903100443:	0.001%
    Previous buildId mismatch: 20170904220027 must be older than 20170903220032:	0.001%
    Previous buildId mismatch: 20170904220027 must be older than 20170904100131:	0.001%
    Previous buildId mismatch: 20170905100117 must be older than 20170903220032:	0.001%
    Previous buildId mismatch: 20170905100117 must be older than 20170904220027:	0.001%
    Previous buildId mismatch: 20170905220108 must be older than 20170903220032:	0.001%
    Previous buildId mismatch: 20170905220108 must be older than 20170904100131:	0.001%
    Previous buildId mismatch: 20170905220108 must be older than 20170904220027:	0.002%
    Previous buildId mismatch: 20170905220108 must be older than 20170905100117:	0.001%
    Previous buildId mismatch: 20170906100107 must be older than 20170903220032:	0.001%
    Previous buildId mismatch: 20170906100107 must be older than 20170904100131:	0.001%
    Previous buildId mismatch: 20170906100107 must be older than 20170905100117:	0.002%
    Previous buildId mismatch: 20170906100107 must be older than 20170905220108:	0.001%
    Previous buildId mismatch: 20170906220306 must be older than 20170903100443:	0.001%
    Previous buildId mismatch: 20170906220306 must be older than 20170904220027:	0.001%
    Previous buildId mismatch: 20170906220306 must be older than 20170905100117:	0.002%
    Previous buildId mismatch: 20170906220306 must be older than 20170905220108:	0.002%
    Previous buildId mismatch: 20170906220306 must be older than 20170906100107:	0.001%
    Previous buildId mismatch: 20170907100318 must be older than 20170903100443:	0.001%
    Previous buildId mismatch: 20170907100318 must be older than 20170905100117:	0.001%
    Previous buildId mismatch: 20170907100318 must be older than 20170905220108:	0.002%
    Previous buildId mismatch: 20170907100318 must be older than 20170906100107:	0.002%
    Previous buildId mismatch: 20170907100318 must be older than 20170906220306:	0.003%
    Previous buildId mismatch: 20170907194642 must be older than 20170903220032:	0.001%
    Previous buildId mismatch: 20170907194642 must be older than 20170905100117:	0.001%
    Previous buildId mismatch: 20170907194642 must be older than 20170906100107:	0.001%
    Previous buildId mismatch: 20170907194642 must be older than 20170906220306:	0.001%
    Previous buildId mismatch: 20170907194642 must be older than 20170907100318:	0.001%
    Previous buildId mismatch: 20170907220212 must be older than 20170903220032:	0.001%
    Previous buildId mismatch: 20170907220212 must be older than 20170905100117:	0.001%
    Previous buildId mismatch: 20170907220212 must be older than 20170905220108:	0.001%
    Previous buildId mismatch: 20170907220212 must be older than 20170906100107:	0.001%
    Previous buildId mismatch: 20170907220212 must be older than 20170907100318:	0.002%
    Previous buildId mismatch: 20170908100218 must be older than 20170907100318:	0.001%
    Previous buildId mismatch: 20170908100218 must be older than 20170907220212:	0.001%
    Previous buildId mismatch: 20170908220146 must be older than 20170907100318:	0.001%
    Previous buildId mismatch: 20170908220146 must be older than 20170907220212:	0.001%
    Previous buildId mismatch: 20170908220146 must be older than 20170908100218:	0.001%
    Previous channel mismatch: expected nightly-cck-google got nightly:	0.001%
    Previous channel mismatch: expected nightly-cck-mint got nightly:	0.003%
    Previous channel mismatch: expected nightly-cck-mozillaonline got nightly:	0.001%
    Previous channel mismatch: expected nightly-cck-yandex got nightly:	0.001%


The vast majority of the data in the payload seems reasonable (99.87%).

However, a handful of `update` pings are reporting a `previousBuildId` mismatch: this is unexpected. **After discussing this with the *update team*, it seems like this could either be due to Nigthly channel weirdness or to the customization applied by the [CCK tool](https://mike.kaply.com/cck2/).** Additionally, some pings are reporting a `previousChannel` different than the one in the environment: this is definitely due to the CCK tool, given the *cck* entry in the channel name. These issues do not represent a problem, as most of the data is correct and their volume is fairly low.

## Check that we receive one ping per client and target update
For each ping, build a key with the client id and the previous build update details. Since we expect to have exactly one ping for each successfully applied *update*, we don't expect duplicate keys.


```python
update_dupes = deduped_subset.map(lambda p: ((p.get("clientId"),
                                              p.get("payload/previousChannel"),
                                              p.get("payload/previousVersion"),
                                              p.get("payload/previousBuildId")), 1)).countByKey()

print("Percentage of pings related to the same update (for the same client):\t{:.3f}%"\
      .format(pct(sum([v for v in update_dupes.values() if v > 1]), deduped_count)))
```
    Percentage of pings related to the same update (for the same client):	1.318%


We're receiving `update` pings with different `documentId` related to the same initial build, for a few clients. One possible reason for this could be users having multiple copies of Firefox installed on their machine. Let's see if that's the case.


```python
clientIds_sending_dupes = [k[0] for k, v in update_dupes.iteritems() if v > 1]

def check_same_original_build(ping_list):
    # Build a "unique" identifier for the build by
    # concatenating the buildId, channel and version.
    unique_build_ids = [
        "{}{}{}".format(p.get("application/buildId"), p.get("application/channel"), p.get("application/version"))\
        for p in ping_list[1]
    ]
    
    # Remove the duplicates and return True if all the pings came
    # from the same build.
    return len(set(unique_build_ids)) < 2
    
# Count how many duplicates are updating to the same builds and how many are
# updating to different builds.
original_builds_same =\
    deduped_subset.filter(lambda p: p.get("clientId") in clientIds_sending_dupes)\
                  .map(lambda p: ((p.get("clientId"),
                                   p.get("payload/previousChannel"),
                                   p.get("payload/previousVersion"),
                                   p.get("payload/previousBuildId")), [p]))\
                  .reduceByKey(lambda a, b: a + b)\
                  .filter(lambda p: len(p[1]) > 1)\
                  .map(check_same_original_build).countByValue()
                    
print("Updated builds are identical:\t{:.3f}%"\
      .format(pct(original_builds_same.get(True), sum(original_builds_same.values()))))
print("Updated builds are different:\t{:.3f}%"\
      .format(pct(original_builds_same.get(False), sum(original_builds_same.values()))))
```
    Updated builds are identical:	16.472%
    Updated builds are different:	83.528%


The data shows that 83.52% of the 1.31% dupes are updating from different builds. The 0.22% of all `update` pings that are the same client updating to the same build from the same build are, at present, unexplained (but in small enough quantities we can ignore for the moment).

The `update` pings with the same previous build information may be coming from the same profile, copied and then used with different versions of Firefox. Depending on when the browser is started with a specific copied profile, the downloaded *update* blob might be different (more recent), thus resulting in an `update` with `reason = success` being sent with the same *previous build* information but with different *current build* information.

## Validate the submission delay

### How long until we receive the ping after it's created?


```python
delays = deduped_subset.map(lambda p: calculate_submission_delay(p))
```

```python
setup_plot("'update' ('success') ping submission delay CDF",
           MAX_DELAY_S / HOUR_IN_S, area_border_x=1.0)

plot_cdf(delays\
         .map(lambda d: d / HOUR_IN_S if d < MAX_DELAY_S else MAX_DELAY_S / HOUR_IN_S)\
         .collect(), label="CDF", linestyle="solid")

plt.show()
```


![png](images/output_23_0.png)


Almost 95% of the `update` pings with `reason = success` are submitted within an hour from the ping being created. Since we know that this ping is created as soon as the [update is applied](https://firefox-source-docs.mozilla.org/toolkit/components/telemetry/telemetry/data/update-ping.html#payload-reason) we can claim that we receive 95% of these pings within an hour from the update being applied. 

## Make sure that the volume of incoming pings is reasonable
Check if the volume of `update` pings with `reason = ready` matches with the volume of pings with `reason = success`. For each ping with `reason = ready`, find the matching ping with `reason = success`.

We are considering the data within a very narrow window of time: we could see `reason = success` pings from users that sent a `reason = ready` ping before the 3rd of September and `reason = ready` pings from users that have sent us a `reason = success` after the 9th of September. Filter these edge cases out by inspecting the `previousBuildId` and `targetBuildId`.


```python
filtered_ready = ping_ready.filter(lambda p: p.get("payload/targetBuildId") < "{}999999".format(MAX_DATE))
filtered_success = ping_success.filter(lambda p: p.get("payload/previousBuildId") >= "{}000000".format(MIN_DATE))
```
Use the filtered RDDs to match between the different ping reasons.


```python
# Get an identifier that keeps in consideration both the current build
# and the target build.
ready_uuid = filtered_ready\
    .map(lambda p: (p.get("clientId"),
                    p.get("application/buildId"),
                    p.get("application/channel"),
                    p.get("application/version"),
                    p.get("payload/targetBuildId"),
                    p.get("payload/targetChannel"),
                    p.get("payload/targetVersion")))

# Get an identifier that considers both the prevous build info and the
# current build info. The order of the values in the tuple need to match
# the one from the previous RDD.
success_uuid = filtered_success\
    .map(lambda p: (p.get("clientId"),
                    p.get("payload/previousBuildId"),
                    p.get("payload/previousChannel"),
                    p.get("payload/previousVersion"),
                    p.get("application/buildId"),
                    p.get("application/channel"),
                    p.get("application/version")))
```
Let's match each `reason = ready` ping with a `reason = success` one, and count them.


```python
matching_update_pings = ready_uuid.intersection(success_uuid)
matching_update_ping_count = matching_update_pings.count()
```
Finally, show up some stats.


```python
print("{:.3f}% of the 'update' ping with reason 'ready' have a matching ping with reason 'success'."\
      .format(pct(matching_update_ping_count, filtered_ready.count())))
print("{:.3f}% of the 'update' ping with reason 'success' have a matching ping with reason 'ready'."\
      .format(pct(matching_update_ping_count, filtered_success.count())))
```
    63.834% of the 'update' ping with reason 'ready' have a matching ping with reason 'success'.
    89.428% of the 'update' ping with reason 'success' have a matching ping with reason 'ready'.


Only ~63% of the update ping sent when an update is ready to be applied have a corrensponding ping that's sent, for the same client and upgrade path, after the update is successfully applied. One possible explaination for this is the delay with which updates get applied after they get downloaded: unless the browser is restarted (and that can happen after days due to user suspending their machines), we won't see the ready ping anytime soon. 

Roughly 89% of the `update` pings with `reason = success` can be traced back to an `update` with `reason = ready`. The missing ~10% matches can be due to users disabling automatic updates (see [this query](https://sql.telemetry.mozilla.org/queries/21667#103055)) and [other edge cases](https://firefox-source-docs.mozilla.org/toolkit/components/telemetry/telemetry/data/update-ping.html#expected-behaviours): no `update` ping is sent [in that case](https://bugzilla.mozilla.org/show_bug.cgi?id=1386619) if an update is manually triggered.


```python

```
