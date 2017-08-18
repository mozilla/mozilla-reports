---
title: update ping validation on Beta
authors:
- dexter
tags:
- firefox
- update
- latency
created_at: 2016-08-18 00:00:00
updated_at: 2017-08-18 15:29:49.736708
tldr: This notebook verifies that the `update` ping with `reason = ready` behaves
  as expected on Beta.
thumbnail: images/output_23_0.png
---
# Validate 'update' ping submissions on Beta (`reason = ready`)

This analysis validates the `update` ping with `reason = ready`, which was introduced in [bug 1120372](https://bugzilla.mozilla.org/show_bug.cgi?id=1120372) and should be sent every time an update is downloaded and ready to be applied. We verified that the ping is behaving correctly [on Nightly](http://reports.telemetry.mozilla.org/post/projects/update_ping_ready_nightly_validation.kp), and we're going to perform similar validations for Beta:

- the ping is received within a reasonable time after being created;
- we receive one ping per update;
- that the payload looks ok;
- check if the volume of update pings is within the expected range by cross-checking it with the main pings;
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
The `update` ping landed on the Beta channel on the 8th of August, 2017 (*Beta 1*). The first `update` pings should have been sent when updating to *Beta 2*, which was released on the 11th of August 2017 according to the [release calendar](https://calendar.google.com/calendar/render?eid=Xzk1aG0ycjM0NmNvajJjOWc2bGozOG9iNTc0cG00YzFnNmNxNjJjcGw2Z3MzMmUzNjZrczY4YzltNnMgbW96aWxsYS5jb21fZGJxODRhbnI5aTh0Y25taGFiYXRzdHY1Y29AZw&ctz=America/Los_Angeles&sf=true&output=xml#eventpage_6). However, with [bug 1390175](https://bugzilla.mozilla.org/show_bug.cgi?id=1390175), the `update` ping started flowing to its own bucket on the 14th of August 2017. In order to have one week of data, fetch pings from the 11th to the 18th of August, 2017, both from the `OTHER` and the `update` buckets, then merge them.


```python
BETA_BUILDID_MIN = "20170808000000" # 56.0b1
BETA_BUILDID_MAX = "20170815999999" # 56.0b3

update_pings_other_bkt = Dataset.from_source("telemetry") \
    .where(docType="OTHER") \
    .where(appUpdateChannel="beta") \
    .where(submissionDate=lambda x: "20170811" <= x < "20170818") \
    .where(appBuildId=lambda x: BETA_BUILDID_MIN <= x < BETA_BUILDID_MAX) \
    .records(sc, sample=1.0)
    
update_pings_update_bkt = Dataset.from_source("telemetry") \
    .where(docType="update") \
    .where(appUpdateChannel="beta") \
    .where(submissionDate=lambda x: "20170811" <= x < "20170818") \
    .where(appBuildId=lambda x: BETA_BUILDID_MIN <= x < BETA_BUILDID_MAX) \
    .records(sc, sample=1.0)
```
    fetching 265.33015MB in 1605 files...
    fetching 248.69387MB in 819 files...



```python
# The 'OTHER' bucket is a miscellaneous bucket, it might contain stuff other than the update ping.
# Filter them out.
update_pings_other_bkt = update_pings_other_bkt.filter(lambda p: p.get("type") == "update")
# Then merge the pings from both buckets.
update_pings = update_pings_other_bkt.union(update_pings_update_bkt)
```
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
MAX_DELAY_S = 60 * 60 * 48.0
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
                                             "payload/targetVersion"])

ping_count = subset.count()
```
Quantify the percentage of duplicate pings we're receiving. We don't expect this value to be greater than ~1%, which is the amount we usually get from `main` and `crash`: as a rule of thumb, we threat anything less than 1% as *probably* well behaving.


```python
deduped_subset = dedupe(subset, "id")
deduped_count = deduped_subset.count()
print("Percentage of duplicate pings: {:.3f}".format(100.0 - pct(deduped_count, ping_count)))
```
    Percentage of duplicate pings: 0.271


The percentage of duplicate pings is within the expected range. Move on and verify the payload of the `update` pings.


```python
def validate_update_payload(p):
    PAYLOAD_KEYS = [
        "payload/reason",
        "payload/targetBuildId",
        "payload/targetChannel",
        "payload/targetVersion"
    ]

    # All the payload keys needs to be strings.
    for k in PAYLOAD_KEYS:
        if not isinstance(p.get(k), basestring):
            return ("'{}' is not a string".format(k), 1)
        
    # We only expect "reason" = ready.
    if p.get("payload/reason") != "ready":
        return ("Unexpected 'reason' {}".format(p.get("payload/reason"), 1))
        
    # For Beta, the target channel should be the same as the
    # application channel.
    if p.get("payload/targetChannel") != p.get("application/channel"):
        return ("Target channel mismatch: expected {} got {}"\
                .format(p.get("payload/targetChannel"), p.get("application/channel")), 1)
                
    # The target buildId must be greater than the application build id.
    if p.get("payload/targetBuildId") <= p.get("application/buildId"):
        return ("Target buildId mismatch: {} must be more recent than {}"\
                .format(p.get("payload/targetBuildId"), p.get("application/buildId")), 1)
    
    return ("Ok", 1)

validation_results = deduped_subset.map(validate_update_payload).countByKey()
for k, v in sorted(validation_results.iteritems()):
    if "channel mismatch" not in k:
        print("{}:\t{:.3f}%".format(k, pct(v, ping_count)))
        
# We are not sure if we can or cannot disclose channel ratios. Let's be safe
# and aggregate them.
channel_mismatch_ratios = dict([(k,v) for k,v in validation_results.iteritems() if "channel mismatch" in k])
total_channel_mismatch = pct(sum(channel_mismatch_ratios.values()), ping_count)
for k in channel_mismatch_ratios.keys():
    print("{}".format(k))
print("\nTotal channel mismatch:\t{:.3f}%".format(total_channel_mismatch))
```
    Ok:	99.454%
    Target buildId mismatch: 20170808170225 must be more recent than 20170810180547:	0.002%
    Target buildId mismatch: 20170810180547 must be more recent than 20170815141045:	0.004%
    Target channel mismatch: expected beta-cck-mozilla14 got beta
    Target channel mismatch: expected beta-cck-mozilla101 got beta
    Target channel mismatch: expected beta-cck-mozilla-EMEfree got beta
    Target channel mismatch: expected beta-cck-mozilla15 got beta
    Target channel mismatch: expected beta-cck-yahooid got beta
    Target channel mismatch: expected beta-cck-mozilla111 got beta
    Target channel mismatch: expected beta-cck-mozilla19 got beta
    Target channel mismatch: expected beta-cck-seznam got beta
    Target channel mismatch: expected beta-cck-yahoomy got beta
    Target channel mismatch: expected beta-cck-bing got beta
    Target channel mismatch: expected beta-cck-mozillaonline got beta
    Target channel mismatch: expected beta-cck-mozilla26 got beta
    Target channel mismatch: expected beta-cck-mozilla12 got beta
    Target channel mismatch: expected beta-cck-mozilla-ironsource-001 got beta
    Target channel mismatch: expected beta-cck-yandex got beta
    Target channel mismatch: expected beta-cck-yahoocfk got beta
    Target channel mismatch: expected beta-cck-yahooca got beta
    Target channel mismatch: expected beta-cck-aol got beta
    Target channel mismatch: expected beta-cck-mozilla20 got beta
    Target channel mismatch: expected beta-cck-euballot got beta
    
    Total channel mismatch:	0.269%


The vast majority of the data in the payload seems reasonable (99.45%).

However, a handful of `update` pings are reporting a `targetBuildId` which is older than the current build reported by the ping's environment: this is unexpected, as the the target build id must be always greater than the current one. After discussing this with the *update team*, it seems like this could either be due to channel weirdness or to the customization applied by the [CCK tool](https://mike.kaply.com/cck2/). Additionally, some pings are reporting a `targetChannel` different than the one in the environment: this is definitely due to the CCK tool, given the *cck* entry in the channel name. These issues do not represent a problem, as most of the data is correct and their volume is fairly low.

## Check that we receive one ping per client and target update
For each ping, build a key with the client id and the target update details. Since we expect to have exactly one ping for each update bundle marked as *ready*, we don't expect duplicate keys.


```python
update_dupes = deduped_subset.map(lambda p: ((p.get("clientId"),
                                              p.get("payload/targetChannel"),
                                              p.get("payload/targetVersion"),
                                              p.get("payload/targetBuildId")), 1)).countByKey()

print("Percentage of pings related to the same update (for the same client):\t{:.3f}%"\
      .format(pct(sum([v for v in update_dupes.values() if v > 1]), deduped_count)))
```
    Percentage of pings related to the same update (for the same client):	3.598%


We're receiving `update` pings with different `documentId` related to the same target update bundle, for some clients. The 3.59% is slightly higher than the one we [saw on Nightly](http://reports.telemetry.mozilla.org/post/projects/update_ping_ready_nightly_validation.kp#check-that-we-receive-one-ping-per-client-and-target-update), 1.74%. One possible reason for this could be users having multiple copies of Firefox installed on their machine. Let's see if that's the case.


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
    
# Count how many duplicates come from the same builds and how many come from
# different original builds.
original_builds_same =\
    deduped_subset.filter(lambda p: p.get("clientId") in clientIds_sending_dupes)\
                  .map(lambda p: ((p.get("clientId"),
                                   p.get("payload/targetChannel"),
                                   p.get("payload/targetVersion"),
                                   p.get("payload/targetBuildId")), [p]))\
                  .reduceByKey(lambda a, b: a + b)\
                  .filter(lambda p: len(p[1]) > 1)\
                  .map(check_same_original_build).countByValue()
                    
print("Original builds are identical:\t{:.3f}%"\
      .format(pct(original_builds_same.get(True), sum(original_builds_same.values()))))
print("Original builds are different:\t{:.3f}%"\
      .format(pct(original_builds_same.get(False), sum(original_builds_same.values()))))
```
    Original builds are identical:	97.293%
    Original builds are different:	2.707%


The data shows that the `update` pings with the same target version are not necessarily coming from the same profile being used on different Firefox builds/installation: most of them are, but not all of them. After discussing this with the *update team*, it turns out that this can be explained by updates failing to apply: for certain classes of errors, we download the update blob again and thus send a new `update` ping with the same target version. This problem shows up in the [update orphaning](https://telemetry.mozilla.org/update-orphaning/) dashboard as well but, unfortunately, it only reports Release data.

## Validate the submission delay


```python
delays = deduped_subset.map(lambda p: calculate_submission_delay(p))
```

```python
MAX_DELAY_S = 60 * 60 * 48.0
setup_plot("'update' ('ready') ping submission delay CDF",
           MAX_DELAY_S / HOUR_IN_S, area_border_x=1.0)

plot_cdf(delays\
         .map(lambda d: d / HOUR_IN_S if d < MAX_DELAY_S else MAX_DELAY_S / HOUR_IN_S)\
         .collect(), label="CDF", linestyle="solid")

plt.show()
```


![png](images/output_23_0.png)


Almost all of the `update` ping are submitted within an hour from the update being ready.

## Make sure that the volume of incoming `update` pings is reasonable
This is a tricky one. The `update` ping with `reason = "ready"` is sent as soon as an update package is downloaded, verified and deemed ready to be applied. However, nothing guarantees that the update is immediately (or ever) applied. To check if the volume of `update` pings is in the ballpark, we can:

1. Get a list of client ids for a specific target update build id of 56.0 Beta 2, '20170810xxxxxx'.
2. Get the `main-ping` for that version of Firefox.
3. Check how many clients from the list at (1) are in the list at (2).

**Step 1** - Get the list of client ids updating to build '20170810xxxxxx'


```python
TARGET_BUILDID_MIN = '20170810000000'
TARGET_BUILDID_MAX = '20170810999999'

update_candidates =\
    deduped_subset.filter(lambda p: TARGET_BUILDID_MIN <= p.get("payload/targetBuildId") <= TARGET_BUILDID_MAX)
update_candidates_clientIds = dedupe(update_candidates, "clientId").map(lambda p: p.get("clientId"))
candidates_count = update_candidates_clientIds.count()
```
**Step 2** - Get the `main-ping` from that Beta build and extract the list of client ids.


```python
updated_main_pings = Dataset.from_source("telemetry") \
    .where(docType="main") \
    .where(appUpdateChannel="beta") \
    .where(submissionDate=lambda x: "20170811" <= x < "20170818") \
    .where(appBuildId=lambda x: TARGET_BUILDID_MIN <= x <= TARGET_BUILDID_MAX) \
    .records(sc, sample=1)
```
    fetching 198117.80319MB in 1364 files...


We just need the client ids and a few other fields to dedupe.


```python
subset_main = get_pings_properties(updated_main_pings, ["id",
                                                        "clientId",
                                                        "meta/Timestamp",
                                                        "application/buildId",
                                                        "application/channel",
                                                        "application/version"])
```
Start by deduping by document id. After that, only get a single ping per client and extract the list of client ids.


```python
deduped_main = dedupe(subset_main, "id")
updated_clientIds = dedupe(deduped_main, "clientId").map(lambda p: p.get("clientId"))
updated_count = updated_clientIds.count()
```
**Step 3** - Count how many clients that were meant to update actually updated in the following 7 days.


```python
matching_clientIds = update_candidates_clientIds.intersection(updated_clientIds)
matching_count = matching_clientIds.count()
```

```python
print("{:.3f}% of the clients that sent the update ping updated to the newer Beta build within a week."\
      .format(pct(matching_count, candidates_count)))
print("{:.3f}% of the clients that were seen on the newer Beta build sent an update ping."\
      .format(pct(candidates_count, updated_count)))
```
    91.445% of the clients that sent the update ping updated to the newer Beta build within a week.
    98.819% of the clients that were seen on the newer Beta build sent an update ping.


Roughly 98% of the clients that were seen in the new Beta build also sent the update ping. This is way higher than the 80% we saw on Nightly, but still not 100%. This could be due to a few reasons:

- some users are disabling automatic updates and no `update` ping is sent [in that case](https://bugzilla.mozilla.org/show_bug.cgi?id=1386619) if an update is manually triggered;
- some users are doing pave-over installs, by re-installing Firefox through the installer rather than relying on the update system;
- another unkown edge case in the client, that was not documented.


```python

```
