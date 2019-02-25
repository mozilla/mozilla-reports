---
title: Hardware Report for Windows 7 and Windows 10 users.
authors:
- Alessio Placitelli
tags:
- hardware report
- windows
created_at: 2017-04-05 00:00:00
updated_at: 2017-04-06 10:10:40.912156
tldr: This is a one-off ETL job for getting separate hardware reports for users runing
  Windows 7 or Windows 10.
---
```python
import ujson as json
import datetime as dt
import os.path
import boto3
import botocore
import calendar
import requests
import moztelemetry.standards as moz_std

%pylab inline
```
### Miscellaneous functions


```python
def fetch_json(uri):
    """ Perform an HTTP GET on the given uri, return the results as json.
    If there is an error fetching the data, raise an exception.
    
    Args:
        uri: the string URI to fetch.
    
    Returns:
        A JSON object with the response.
    """
    data = requests.get(uri)
    # Raise an exception if the fetch failed.
    data.raise_for_status()
    return data.json()

def get_OS_arch(browser_arch, os_name, is_wow64):
    """ Infers the OS arch from environment data.
    
    Args:
        browser_arch: the browser architecture string (either "x86" or "x86-64").
        os_name: the operating system name.
        is_wow64: on Windows, indicates if the browser process is running under WOW64.
    
    Returns:
        'x86' if the underlying OS is 32bit, 'x86-64' if it's a 64bit OS.
    """
    
    is_64bit_browser = browser_arch == 'x86-64'
    # If it's a 64bit browser build, then we're on a 64bit system.
    if is_64bit_browser:
        return 'x86-64'
    
    is_windows = os_name == 'Windows_NT'
    # If we're on Windows, with a 32bit browser build, and |isWow64 = true|,
    # then we're on a 64 bit system.
    if is_windows and is_wow64:
        return 'x86-64'
    
    # Otherwise we're probably on a 32 bit system.
    return 'x86'

def vendor_name_from_id(id):
    """ Get the string name matching the provided vendor id.
    
    Args:
        id: A string containing the vendor id.
    
    Returns: 
        A string containing the vendor name or "(Other <ID>)" if
        unknown.
    """
    
    # TODO: We need to make this an external resource for easier
    # future updates.
    vendor_map = {
        '0x1013': 'Cirrus Logic',
        '0x1002': 'AMD',
        '0x8086': 'Intel',
        '0x5333': 'S3 Graphics',
        '0x1039': 'SIS',
        '0x1106': 'VIA',
        '0x10de': 'NVIDIA',
        '0x102b': 'Matrox',
        '0x15ad': 'VMWare',
        '0x80ee': 'Oracle VirtualBox',
        '0x1414': 'Microsoft Basic',
    }
    
    return vendor_map.get(id, "Other")

def get_device_family_chipset(vendor_id, device_id):
    """ Get the family and chipset strings given the vendor and device ids.
    
    Args:
        vendor_id: a string representing the vendor id (e.g. '0xabcd').
        device_id: a string representing the device id (e.g. '0xbcde').
    
    Returns:
        A string in the format "Device Family Name-Chipset Name".
    """
    if not vendor_id in device_map:
        return "Unknown"

    if not device_id in device_map[vendor_id]:
        return "Unknown"

    return "-".join(device_map[vendor_id][device_id])

def invert_device_map(m):
    """ Inverts a GPU device map fetched from the jrmuizel's Github repo. 
    The layout of the fetched GPU map layout is:
        Vendor ID -> Device Family -> Chipset -> [Device IDs]
    We should convert it to:
        Vendor ID -> Device ID -> [Device Family, Chipset]
    """
    device_id_map = {}
    for vendor, u in m.iteritems():
        device_id_map['0x' + vendor] = {}
        for family, v in u.iteritems():
            for chipset, ids in v.iteritems():
                device_id_map['0x' + vendor].update({('0x' + gfx_id): [family, chipset] for gfx_id in ids})
    return device_id_map

def build_device_map():
    """ This function builds a dictionary that will help us mapping vendor/device ids to a 
    human readable device family and chipset name."""

    intel_raw = fetch_json("https://github.com/jrmuizel/gpu-db/raw/master/intel.json")
    nvidia_raw = fetch_json("https://github.com/jrmuizel/gpu-db/raw/master/nvidia.json")
    amd_raw = fetch_json("https://github.com/jrmuizel/gpu-db/raw/master/amd.json")
    
    device_map = {}
    device_map.update(invert_device_map(intel_raw))
    device_map.update(invert_device_map(nvidia_raw))
    device_map.update(invert_device_map(amd_raw))

    return device_map
    
device_map = build_device_map()
```
### Functions to query the longitudinal dataset


```python
# Reasons why the data for a client can be discarded.
REASON_INACTIVE = "inactive"
REASON_BROKEN_DATA = "broken"

def get_valid_client_record(r, data_index):
    """ Check if the referenced record is sane or contains partial/broken data.
    
    Args:
        r: The client entry in the longitudinal dataset.
        dat_index: The index of the sample within the client record.
    
    Returns:
        An object containing the client hardware data or REASON_BROKEN_DATA if the
        data is invalid.
    """
    gfx_adapters = r["system_gfx"][data_index]["adapters"]
    monitors = r["system_gfx"][data_index]["monitors"]
    
    # We should make sure to have GFX adapter. If we don't, discard this record.
    if not gfx_adapters or not gfx_adapters[0]:
        return REASON_BROKEN_DATA
    
    # Due to bug 1175005, Firefox on Linux isn't sending the screen resolution data.
    # Don't discard the rest of the ping for that: just set the resolution to 0 if
    # unavailable. See bug 1324014 for context.
    screen_width = 0
    screen_height = 0
    if monitors and monitors[0]:
        screen_width = monitors[0]["screen_width"]
        screen_height = monitors[0]["screen_height"]
    
    # Non Windows OS do not have that property.
    is_wow64 = r["system"][data_index]["is_wow64"] == True
    
    # At this point, we should have filtered out all the weirdness. Fetch
    # the data we need. 
    data = {
        'browser_arch': r["build"][data_index]["architecture"],
        'os_name': r["system_os"][data_index]["name"],
        'os_version': r["system_os"][data_index]["version"],
        'memory_mb': r["system"][data_index]["memory_mb"],
        'is_wow64': is_wow64,
        'num_gfx_adapters': len(gfx_adapters),
        'gfx0_vendor_id': gfx_adapters[0]["vendor_id"],
        'gfx0_device_id': gfx_adapters[0]["device_id"],
        'screen_width': screen_width,
        'screen_height': screen_height,
        'cpu_cores': r["system_cpu"][data_index]["cores"],
        'cpu_vendor': r["system_cpu"][data_index]["vendor"],
        'cpu_speed': r["system_cpu"][data_index]["speed_mhz"],
        'has_flash': False
    }
    
    # The plugins data can still be null or empty, account for that.
    plugins = r["active_plugins"][data_index] if r["active_plugins"] else None
    if plugins:
        data['has_flash'] = any([True for p in plugins if p['name'] == 'Shockwave Flash'])
    
    return REASON_BROKEN_DATA if None in data.values() else data

def get_latest_valid_per_client(entry):
    """ Get the most recently submitted ping for a client.

    Then use this index to look up the data from the other columns (we can assume that the sizes
    of these arrays match, otherwise the longitudinal dataset is broken).
    Once we have the data, we make sure it's valid and return it.
    
    Args:
        entry: The record containing all the data for a single client.

    Returns:
        An object containing the valid hardware data for the client or
        REASON_BROKEN_DATA if it send broken data. 
    
    Raises:
        ValueError: if the columns within the record have mismatching lengths. This
        means the longitudinal dataset is corrupted.
    """

    # Some clients might be missing entire sections. If that's
    # a basic section, skip them, we don't want partial data.
    # Don't enforce the presence of "active_plugins", as it's not included
    # by the pipeline if no plugin is reported by Firefox (see bug 1333806).
    desired_sections = [
        "build", "system_os", "submission_date", "system",
        "system_gfx", "system_cpu"
    ]

    for field in desired_sections:
        if entry[field] is None:
            return REASON_BROKEN_DATA

        # All arrays in the longitudinal dataset should have the same length, for a
        # single client. If that's not the case, if our index is not there, throw.
        if entry[field][0] is None:
            raise ValueError("Null " + field)

    return get_valid_client_record(entry, 0)
```
### Define how we transform the data


```python
def prepare_data(p):
    """ This function prepares the data for further analyses (e.g. unit conversion,
    vendor id to string, ...). """
    cpu_speed = round(p['cpu_speed'] / 1000.0, 1)
    return {
        'browser_arch': p['browser_arch'],
        'cpu_cores': p['cpu_cores'],
        'cpu_cores_speed': str(p['cpu_cores']) + '_' + str(cpu_speed),
        'cpu_vendor': p['cpu_vendor'],
        'cpu_speed': cpu_speed,
        'num_gfx_adapters': p['num_gfx_adapters'],
        'gfx0_vendor_name': vendor_name_from_id(p['gfx0_vendor_id']),
        'gfx0_model': get_device_family_chipset(p['gfx0_vendor_id'], p['gfx0_device_id']),
        'resolution': str(p['screen_width']) + 'x' + str(p['screen_height']),
        'memory_gb': int(round(p['memory_mb'] / 1024.0)),
        'os': p['os_name'] + '-' + p['os_version'],
        'os_arch': get_OS_arch(p['browser_arch'], p['os_name'], p['is_wow64']),
        'has_flash': p['has_flash']
    }

def aggregate_data(processed_data):
    def seq(acc, v):
        # The dimensions over which we want to aggregate the different values.
        keys_to_aggregate = [
            'browser_arch',
            'cpu_cores',
            'cpu_cores_speed',
            'cpu_vendor',
            'cpu_speed',
            'num_gfx_adapters',
            'gfx0_vendor_name',
            'gfx0_model',
            'resolution',
            'memory_gb',
            'os',
            'os_arch',
            'has_flash'
        ]

        for key_name in keys_to_aggregate:
            # We want to know how many users have a particular configuration (e.g. using a particular
            # cpu vendor). For each dimension of interest, build a key as (hw, value) and count its
            # occurrences among the user base.
            acc_key = (key_name, v[key_name])
            acc[acc_key] = acc.get(acc_key, 0) + 1
        
        return acc

    def cmb(v1, v2):
        # Combine the counts from the two partial dictionaries. Hacky?
        return  { k: v1.get(k, 0) + v2.get(k, 0) for k in set(v1) | set(v2) }
    
    return processed_data.aggregate({}, seq, cmb)

def collapse_buckets(aggregated_data, count_threshold):
    """ Collapse uncommon configurations in generic groups to preserve privacy.
    
    This takes the dictionary of aggregated results from |aggregate_data| and collapses
    entries with a value less than |count_threshold| in a generic bucket.
    
    Args:
        aggregated_data: The object containing aggregated data.
        count_threhold: Groups (or "configurations") containing less than this value
        are collapsed in a generic bucket.
    """
    
    # These fields have a fixed set of values and we need to report all of them.
    EXCLUSION_LIST = [ "has_flash", "browser_arch", "os_arch" ]
    
    collapsed_groups = {}
    for k,v in aggregated_data.iteritems():
        key_type = k[0]
        
        # If the resolution is 0x0 (see bug 1324014), put that into the "Other"
        # bucket.
        if key_type == 'resolution' and k[1] == '0x0':
            other_key = ('resolution', 'Other')
            collapsed_groups[other_key] = collapsed_groups.get(other_key, 0) + v
            continue
    
        # Don't clump this group into the "Other" bucket if it has enough
        # users it in.
        if v > count_threshold or key_type in EXCLUSION_LIST:
            collapsed_groups[k] = v
            continue
        
        # If we're here, it means that the key has not enough elements.
        # Fall through the next cases and try to group things together.
        new_group_key = 'Other'
        
        # Let's try to group similar resolutions together.
        if key_type == 'resolution':
            # Extract the resolution.
            [w, h] = k[1].split('x')
            # Round to the nearest hundred.
            w = int(round(int(w), -2))
            h = int(round(int(h), -2))
            # Build up a new key.
            new_group_key = '~' + str(w) + 'x' + str(h)
        elif key_type == 'os':
            [os, ver] = k[1].split('-', 1)
            new_group_key = os + '-' + 'Other'
        
        # We don't have enough data for this particular group/configuration.
        # Aggregate it with the data in the "Other" bucket
        other_key = (k[0], new_group_key)
        collapsed_groups[other_key] = collapsed_groups.get(other_key, 0) + v
    
    # The previous grouping might have created additional groups. Let's check again.
    final_groups = {}
    for k,v in collapsed_groups.iteritems():
        # Don't clump this group into the "Other" bucket if it has enough
        # users it in.
        if (v > count_threshold and k[1] != 'Other') or k[0] in EXCLUSION_LIST:
            final_groups[k] = v
            continue

        # We don't have enough data for this particular group/configuration.
        # Aggregate it with the data in the "Other" bucket
        other_key = (k[0], 'Other')
        final_groups[other_key] = final_groups.get(other_key, 0) + v
    
    return final_groups


def finalize_data(data, sample_count, broken_ratio):
    """ Finalize the aggregated data.
    
    Translate raw sample numbers to percentages and add the date for the reported
    week along with the percentage of discarded samples due to broken data.
    
    Rename the keys to more human friendly names.
    
    Args:
        data: Data in aggregated form.
        sample_count: The number of samples the aggregates where generated from.
        broken_ratio: The percentage of samples discarded due to broken data.
        inactive_ratio: The percentage of samples discarded due to the client not sending data.
        report_date: The starting day for the reported week.
    
    Returns:
        An object containing the reported hardware statistics.
    """

    denom = float(sample_count)

    aggregated_percentages = {
        'broken': broken_ratio,
    }

    keys_translation = {
        'browser_arch': 'browserArch_',
        'cpu_cores': 'cpuCores_',
        'cpu_cores_speed': 'cpuCoresSpeed_',
        'cpu_vendor': 'cpuVendor_',
        'cpu_speed': 'cpuSpeed_',
        'num_gfx_adapters': 'gpuNum_',
        'gfx0_vendor_name': 'gpuVendor_',
        'gfx0_model': 'gpuModel_',
        'resolution': 'resolution_',
        'memory_gb': 'ram_',
        'os': 'osName_',
        'os_arch': 'osArch_',
        'has_flash': 'hasFlash_'
    }

    # Compute the percentages from the raw numbers.
    for k, v in data.iteritems():
        # The old key is a tuple (key, value). We translate the key part and concatenate the
        # value as a string.
        new_key = keys_translation[k[0]] + unicode(k[1])
        aggregated_percentages[new_key] = v / denom

    return aggregated_percentages
```
# Build the report
We compute the hardware report for users running Windows 7 or Windows 10 by taking the most recent data available.


```python
# Connect to the longitudinal dataset and get a subset of the columns
sqlQuery = "SELECT " +\
           "build," +\
           "client_id," +\
           "active_plugins," +\
           "system_os," +\
           "submission_date," +\
           "system," +\
           "system_gfx," +\
           "system_cpu," +\
           "normalized_channel " +\
           "FROM longitudinal"
frame = sqlContext.sql(sqlQuery)\
                  .where("normalized_channel = 'release'")\
                  .where("system_os is not null and system_os[0].name = 'Windows_NT'")\
                  .where("build is not null and build[0].application_name = 'Firefox'")


# The number of all the fetched records (including inactive and broken).
records_count = frame.count()
```
## Get the most recent, valid data for each client.


```python
data = frame.rdd.map(lambda r: get_latest_valid_per_client(r))

# Filter out broken data.
filtered_data = data.filter(lambda r: r is not REASON_BROKEN_DATA)

# Count the broken records
broken_count = data.filter(lambda r: r is REASON_BROKEN_DATA).count()
print("Found {} broken records.".format(broken_count))
```
## Process the data
This extracts the relevant information from each valid data unit returned from the previous step. Each *processed_data* entry represents a single user machine.


```python
processed_data = filtered_data.map(prepare_data)
```

```python
processed_data.first()
```
## Aggregate the data for Windows 7 and Windows 10
Aggregate the machine configurations in a more digestible form.


```python
# Aggregate the data for Windows 7 (Windows NT version 6.1)
windows7_data = processed_data.filter(lambda p: p.get("os") == "Windows_NT-6.1")
aggregated_w7 = aggregate_data(windows7_data)
windows7_count = windows7_data.count()
```

```python
# Aggregate the data for Windows 10 (Windows NT version 10.0)
windows10_data = processed_data.filter(lambda p: p.get("os") == "Windows_NT-10.0")
aggregated_w10 = aggregate_data(windows10_data)
windows10_count = windows10_data.count()
```
Collapse together groups that count less than 1% of our samples.


```python
valid_records_count = records_count - broken_count
threshold_to_collapse = int(valid_records_count * 0.01)

print "Collapsing smaller groups into the other bucket (threshold {th})".format(th=threshold_to_collapse)
collapsed_w7 = collapse_buckets(aggregated_w7, threshold_to_collapse)
collapsed_w10 = collapse_buckets(aggregated_w10, threshold_to_collapse)
```
## Dump the aggregates to a file.


```python
broken_ratio = broken_count / float(records_count)

w7_json = finalize_data(collapsed_w7, windows7_count, broken_ratio)
json_entry = json.dumps(w7_json)
with open("w7data.json", "w") as json_file:
    json_file.write("[" + json_entry.encode('utf8') + "]\n")
    
    
w10_json = finalize_data(collapsed_w10, windows10_count, broken_ratio)
json_entry = json.dumps(w10_json)
with open("w10data.json", "w") as json_file:
    json_file.write("[" + json_entry.encode('utf8') + "]\n")
```

```python

```
