---
title: Query AMO with Add-on GUID
authors:
- Ben Miroglio
tags:
- AMO
- add-ons
- firefox-desktop
created_at: 2017-01-09 00:00:00
updated_at: 2017-01-11 09:22:17.312999
tldr: Get metadata for an add-on through AMO given its GUID
---
# Query AMO with Add-on GUID

In Telemetry and elsewhere we typically use add-on GUIDs to uniquely represent specific add-ons. Often times a GUID is ambiguous, revealing little to no information about the add-on. This script allows a user to quickly get add-on names, e10s compatibility, versions, weekly downloads, categories, etc. from AMO with just an add-on GUID. See the Appendix for an example JSON blob displaying all possible fields. Aside from easily acquiring meta data for add-ons, this example shows the various fields the user can access *not* accessible via telemetry at the moment.

The example below is a simplification of the [script](https://github.com/andymckay/new-arewee10syet.com/blob/master/build.py) used to generate the [arewee10syet.com](https://arewee10syet.com) page. For more details please see the [AMO API doc](https://addons-server.readthedocs.io/en/latest/topics/api/addons.html).



```python
import pandas as pd
import os
import requests
import json
import urllib
import sys
```
# Set Up



```python
# for manual editting of missing or incorrect add-on names
fixups = {
    'testpilot@labs.mozilla.com': 'Test Pilot (old one)',
    '{20a82645-c095-46ed-80e3-08825760534b}': 'Microsoft .NET framework assistant',
}

def process_amo(result):
    """
    Selects and processes specific fields from the dict,
    result, and returns new dict
    """
    try:
        name = result['name']['en-US']
    except KeyError:
        name = result['slug']
    return {
        'name': name,
        'url': result['url'],
        'guid': result['guid'],
        'e10s_status': result['e10s'],
        'avg_daily_users': result['average_daily_users'],
        'categories': ','.join(result['categories']['firefox']),
        'weekly_downloads': result['weekly_downloads'],
        'ratings': result['ratings']
    }

def amo(guid, raw=False):
    """
    Make AMO API call to request data for a given add-on guid 
    
    Return raw data if raw=True, which returns the full
    json returned from AMO as a python dict, otherwise call 
    process_amo() to only return fields of interest 
    (specified in process_amo())
    """
    addon_url = AMO_SERVER + '/api/v3/addons/addon/{}/'.format(guid)
    compat_url = AMO_SERVER + '/api/v3/addons/addon/{}/feature_compatibility/'.format(guid)

    result = {}
    print "Fetching Data for:", guid
    for url in (addon_url, compat_url):
        res = requests.get(url)
        if res.status_code != 200:
            return {
                'name': fixups.get(
                    guid, '{} error fetching data from AMO'.format(res.status_code)),
                'guid': guid
            }
        res.raise_for_status()
        res_json = res.json()
        result.update(res_json)
    if raw:
        return result
    return process_amo(result)

def reorder_list(lst, move_to_front):
    """
    Reorganizes the list <lst> such that the elements in
    <move_to_front> appear at the beginning, in the order they appear in
    <move_to_front>, returning a new list
    """
    result = lst[:]
    for elem in move_to_front[::-1]:
        assert elem in lst, "'{}' is not in the list".format(elem)
        result = [result.pop(result.index(elem))] + result
    return result
        
```
Instantiate amo server object to be used by the above functions


```python
AMO_SERVER = os.getenv('AMO_SERVER', 'https://addons.mozilla.org')
```
# Example: Request Data for 10 add-on GUIDs

As an example, we can call the `amo()` function for a list of 10 add-on GUIDs formatting them into a pandas DF.


```python
addon_guids = \
['easyscreenshot@mozillaonline.com',
 'firebug@software.joehewitt.com',
 'firefox@ghostery.com',
 'uBlock0@raymondhill.net',
 '{20a82645-c095-46ed-80e3-08825760534b}',
 '{73a6fe31-595d-460b-a920-fcc0f8843232}',
 '{DDC359D1-844A-42a7-9AA1-88A850A938A8}',
 '{b9db16a4-6edc-47ec-a1f4-b86292ed211d}',
 '{d10d0bf8-f5b5-c8b4-a8b2-2b9879e08c5d}',
 '{e4a8a97b-f2ed-450b-b12d-ee082ba24781}']

df = pd.DataFrame([amo(i) for i in addon_guids])

# move guid and name to front of DF
df = df[reorder_list(list(df), move_to_front=['guid', 'name'])]
df
```
    Fetching Data for: easyscreenshot@mozillaonline.com
    Fetching Data for: firebug@software.joehewitt.com
    Fetching Data for: firefox@ghostery.com
    Fetching Data for: uBlock0@raymondhill.net
    Fetching Data for: {20a82645-c095-46ed-80e3-08825760534b}
    Fetching Data for: {73a6fe31-595d-460b-a920-fcc0f8843232}
    Fetching Data for: {DDC359D1-844A-42a7-9AA1-88A850A938A8}
    Fetching Data for: {b9db16a4-6edc-47ec-a1f4-b86292ed211d}
    Fetching Data for: {d10d0bf8-f5b5-c8b4-a8b2-2b9879e08c5d}
    Fetching Data for: {e4a8a97b-f2ed-450b-b12d-ee082ba24781}






<div>
<table border="1" class="dataframe">
  <thead>
    <tr style="text-align: right;">
      <th></th>
      <th>guid</th>
      <th>name</th>
      <th>avg_daily_users</th>
      <th>categories</th>
      <th>e10s_status</th>
      <th>ratings</th>
      <th>url</th>
      <th>weekly_downloads</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>0</th>
      <td>easyscreenshot@mozillaonline.com</td>
      <td>Easy Screenshot</td>
      <td>2472392.0</td>
      <td>photos-music-videos</td>
      <td>unknown</td>
      <td>{u'count': 121, u'average': 3.9587}</td>
      <td>https://addons.mozilla.org/en-US/firefox/addon...</td>
      <td>58682.0</td>
    </tr>
    <tr>
      <th>1</th>
      <td>firebug@software.joehewitt.com</td>
      <td>Firebug</td>
      <td>1895612.0</td>
      <td>web-development</td>
      <td>compatible</td>
      <td>{u'count': 1930, u'average': 4.4813}</td>
      <td>https://addons.mozilla.org/en-US/firefox/addon...</td>
      <td>103304.0</td>
    </tr>
    <tr>
      <th>2</th>
      <td>firefox@ghostery.com</td>
      <td>Ghostery</td>
      <td>1359377.0</td>
      <td>privacy-security,web-development</td>
      <td>compatible-webextension</td>
      <td>{u'count': 1342, u'average': 4.5745}</td>
      <td>https://addons.mozilla.org/en-US/firefox/addon...</td>
      <td>56074.0</td>
    </tr>
    <tr>
      <th>3</th>
      <td>uBlock0@raymondhill.net</td>
      <td>uBlock Origin</td>
      <td>2825755.0</td>
      <td>privacy-security</td>
      <td>compatible</td>
      <td>{u'count': 813, u'average': 4.6347}</td>
      <td>https://addons.mozilla.org/en-US/firefox/addon...</td>
      <td>464652.0</td>
    </tr>
    <tr>
      <th>4</th>
      <td>{20a82645-c095-46ed-80e3-08825760534b}</td>
      <td>Microsoft .NET framework assistant</td>
      <td>NaN</td>
      <td>NaN</td>
      <td>NaN</td>
      <td>NaN</td>
      <td>NaN</td>
      <td>NaN</td>
    </tr>
    <tr>
      <th>5</th>
      <td>{73a6fe31-595d-460b-a920-fcc0f8843232}</td>
      <td>NoScript Security Suite</td>
      <td>2134660.0</td>
      <td>privacy-security,web-development</td>
      <td>compatible</td>
      <td>{u'count': 1620, u'average': 4.7068}</td>
      <td>https://addons.mozilla.org/en-US/firefox/addon...</td>
      <td>66640.0</td>
    </tr>
    <tr>
      <th>6</th>
      <td>{DDC359D1-844A-42a7-9AA1-88A850A938A8}</td>
      <td>DownThemAll!</td>
      <td>1185122.0</td>
      <td>download-management</td>
      <td>compatible</td>
      <td>{u'count': 1830, u'average': 4.459}</td>
      <td>https://addons.mozilla.org/en-US/firefox/addon...</td>
      <td>71914.0</td>
    </tr>
    <tr>
      <th>7</th>
      <td>{b9db16a4-6edc-47ec-a1f4-b86292ed211d}</td>
      <td>Video DownloadHelper</td>
      <td>4431752.0</td>
      <td>download-management</td>
      <td>compatible</td>
      <td>{u'count': 7547, u'average': 4.2242}</td>
      <td>https://addons.mozilla.org/en-US/firefox/addon...</td>
      <td>273598.0</td>
    </tr>
    <tr>
      <th>8</th>
      <td>{d10d0bf8-f5b5-c8b4-a8b2-2b9879e08c5d}</td>
      <td>Adblock Plus</td>
      <td>18902366.0</td>
      <td>privacy-security</td>
      <td>compatible</td>
      <td>{u'count': 4947, u'average': 4.8737}</td>
      <td>https://addons.mozilla.org/en-US/firefox/addon...</td>
      <td>744265.0</td>
    </tr>
    <tr>
      <th>9</th>
      <td>{e4a8a97b-f2ed-450b-b12d-ee082ba24781}</td>
      <td>Greasemonkey</td>
      <td>1162583.0</td>
      <td>other</td>
      <td>compatible</td>
      <td>{u'count': 1018, u'average': 4.2613}</td>
      <td>https://addons.mozilla.org/en-US/firefox/addon...</td>
      <td>63610.0</td>
    </tr>
  </tbody>
</table>
</div>



There you have it! Please look at the Appendix for the possible fields obtainable through AMO.

# Appendix

The function `process_amo()` uses prespecified fields. Here you can take a look at a number of the available fields and make necessary edits.


```python
# request data for a single add-on guid
result = amo(addon_guids[1], raw=True)
```
    Fetching Data for: firebug@software.joehewitt.com



```python
result
```




    {u'authors': [{u'id': 9265,
       u'name': u'Joe Hewitt',
       u'url': u'https://addons.mozilla.org/en-US/firefox/user/joe-hewitt/'},
      {u'id': 857086,
       u'name': u'Jan Odvarko',
       u'url': u'https://addons.mozilla.org/en-US/firefox/user/jan-odvarko/'},
      {u'id': 95117,
       u'name': u'robcee',
       u'url': u'https://addons.mozilla.org/en-US/firefox/user/robcee/'},
      {u'id': 4957771,
       u'name': u'Firebug Working Group',
       u'url': u'https://addons.mozilla.org/en-US/firefox/user/firebugworkinggroup/'}],
     u'average_daily_users': 1895612,
     u'categories': {u'firefox': [u'web-development']},
     u'current_beta_version': {u'compatibility': {u'firefox': {u'max': u'52.0',
        u'min': u'30.0a1'}},
      u'edit_url': u'https://addons.mozilla.org/en-US/developers/addon/firebug/versions/1951656',
      u'files': [{u'created': u'2016-10-11T11:26:53Z',
        u'hash': u'sha256:512522fd0036e4daa267f9d57d14eaf31be2913391b12e468ccc89c07b8b48eb',
        u'id': 518451,
        u'platform': u'all',
        u'size': 2617049,
        u'status': u'beta',
        u'url': u'https://addons.mozilla.org/firefox/downloads/file/518451/firebug-2.0.18b1-fx.xpi?src='}],
      u'id': 1951656,
      u'license': {u'id': 18,
       u'name': {u'bg': u'BSD \u041b\u0438\u0446\u0435\u043d\u0437',
        u'ca': u'Llic\xe8ncia BSD',
        u'cs': u'BSD licence',
        u'da': u'BSD-licens',
        u'de': u'BSD-Lizenz',
        u'el': u'\u0386\u03b4\u03b5\u03b9\u03b1 BSD',
        u'en-US': u'BSD License',
        u'es': u'Licencia BSD',
        u'eu': u'BSD Lizentzia',
        u'fa': u'\u0645\u062c\u0648\u0632 BSD',
        u'fr': u'Licence BSD',
        u'ga-IE': u'Cead\xfanas BSD',
        u'hu': u'BSD licenc',
        u'id': u'Lisensi BSD',
        u'it': u'Licenza BSD',
        u'nl': u'BSD-licentie',
        u'pt-PT': u'Licen\xe7a BSD',
        u'ru': u'\u041b\u0438\u0446\u0435\u043d\u0437\u0438\u044f BSD',
        u'sk': u'Licencia BSD',
        u'sq': u'Leje BSD',
        u'sr': u'\u0411\u0421\u0414 \u043b\u0438\u0446\u0435\u043d\u0446\u0430',
        u'sv-SE': u'BSD-licens',
        u'vi': u'Gi\u1ea5y ph\xe9p BSD',
        u'zh-CN': u'BSD \u6388\u6743'},
       u'url': u'http://www.opensource.org/licenses/bsd-license.php'},
      u'reviewed': None,
      u'url': u'https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/2.0.18b1',
      u'version': u'2.0.18b1'},
     u'current_version': {u'compatibility': {u'firefox': {u'max': u'52.0',
        u'min': u'30.0a1'}},
      u'edit_url': u'https://addons.mozilla.org/en-US/developers/addon/firebug/versions/1949588',
      u'files': [{u'created': u'2016-10-07T12:02:17Z',
        u'hash': u'sha256:7cd395e1a79f24b25856f73abaa2f1ca45b9a12dd83276e3b6b6bcb0f25c2944',
        u'id': 516537,
        u'platform': u'all',
        u'size': 2617046,
        u'status': u'public',
        u'url': u'https://addons.mozilla.org/firefox/downloads/file/516537/firebug-2.0.18-fx.xpi?src='}],
      u'id': 1949588,
      u'license': {u'id': 18,
       u'name': {u'bg': u'BSD \u041b\u0438\u0446\u0435\u043d\u0437',
        u'ca': u'Llic\xe8ncia BSD',
        u'cs': u'BSD licence',
        u'da': u'BSD-licens',
        u'de': u'BSD-Lizenz',
        u'el': u'\u0386\u03b4\u03b5\u03b9\u03b1 BSD',
        u'en-US': u'BSD License',
        u'es': u'Licencia BSD',
        u'eu': u'BSD Lizentzia',
        u'fa': u'\u0645\u062c\u0648\u0632 BSD',
        u'fr': u'Licence BSD',
        u'ga-IE': u'Cead\xfanas BSD',
        u'hu': u'BSD licenc',
        u'id': u'Lisensi BSD',
        u'it': u'Licenza BSD',
        u'nl': u'BSD-licentie',
        u'pt-PT': u'Licen\xe7a BSD',
        u'ru': u'\u041b\u0438\u0446\u0435\u043d\u0437\u0438\u044f BSD',
        u'sk': u'Licencia BSD',
        u'sq': u'Leje BSD',
        u'sr': u'\u0411\u0421\u0414 \u043b\u0438\u0446\u0435\u043d\u0446\u0430',
        u'sv-SE': u'BSD-licens',
        u'vi': u'Gi\u1ea5y ph\xe9p BSD',
        u'zh-CN': u'BSD \u6388\u6743'},
       u'url': u'http://www.opensource.org/licenses/bsd-license.php'},
      u'reviewed': None,
      u'url': u'https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/2.0.18',
      u'version': u'2.0.18'},
     u'default_locale': u'en-US',
     u'description': {u'en-US': u'<a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/fc4997ab3399c96f4fddde69c127a1a7ac4d471f70a11827f5965b04dd3d60a0/https%3A//twitter.com/%23%21/firebugnews">Follow Firebug news on Twitter</a>\n\nCompatibility table:\n\n<ul><li><strong>Firefox 3.6</strong> with <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/?page=1#version-1.7.3">Firebug 1.7.3</a></li><li><strong>Firefox 4.0</strong> with <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/?page=1#version-1.7.3">Firebug 1.7.3</a></li><li><strong>Firefox 5.0</strong> with <strong>Firebug 1.8.2</strong> (and also <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/?page=1#version-1.7.3">Firebug 1.7.3</a>)</li><li><strong>Firefox 6.0</strong> with <strong>Firebug 1.8.2</strong> (and also <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/">Firebug 1.9</a>)</li><li><strong>Firefox 7.0</strong> with <strong>Firebug 1.8.2</strong> (and also <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/">Firebug 1.9</a>)</li><li><strong>Firefox 8.0</strong> with <strong>Firebug 1.8.3</strong> (and also <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/">Firebug 1.9</a>)</li><li><strong>Firefox 9.0</strong> with <strong>Firebug 1.8.4</strong> (and also <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/">Firebug 1.9</a>)</li><li><strong>Firefox 10.0</strong> with <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/">Firebug 1.9</a></li><li><strong>Firefox 11.0</strong> with <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/">Firebug 1.9</a></li><li><strong>Firefox 12.0</strong> with <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/">Firebug 1.9</a></li><li><strong>Firefox 13.0</strong> with <b>Firebug 1.10</b> (and also <a rel="nofollow" href="https://addons.mozilla.org/en-US/firefox/addon/firebug/versions/">Firebug 1.9</a>)</li><li><strong>Firefox 14.0</strong> with <b>Firebug 1.10</b></li><li><strong>Firefox 15.0</strong> with <b>Firebug 1.10</b></li><li><strong>Firefox 16.0</strong> with <b>Firebug 1.10</b></li><li><strong>Firefox 17.0</strong> with <b>Firebug 1.11</b> (and also Firebug 1.10)</li><li><strong>Firefox 18.0</strong> with <b>Firebug 1.11</b></li><li><strong>Firefox 19.0</strong> with <b>Firebug 1.11</b></li><li><strong>Firefox 20.0</strong> with <b>Firebug 1.11</b></li><li><strong>Firefox 21.0</strong> with <b>Firebug 1.11</b></li><li><strong>Firefox 22.0</strong> with <b>Firebug 1.11</b></li><li><strong>Firefox 23.0</strong> with <b>Firebug 1.12</b> (and also Firebug 1.11)</li><li><strong>Firefox 24.0</strong> with <b>Firebug 1.12</b></li><li><strong>Firefox 25.0</strong> with <b>Firebug 1.12</b></li><li><strong>Firefox 26.0</strong> with <b>Firebug 1.12</b></li><li><strong>Firefox 27.0</strong> with <b>Firebug 1.12</b></li><li><strong>Firefox 28.0</strong> with <b>Firebug 1.12</b></li><li><strong>Firefox 29.0</strong> with <b>Firebug 1.12</b></li><li><strong>Firefox 30.0</strong> with <b>Firebug 2.0</b> (and also Firebug 1.12)</li><li><strong>Firefox 31.0</strong> with <b>Firebug 2.0</b> (and also Firebug 1.12)</li><li><strong>Firefox 32.0</strong> with <b>Firebug 2.0</b> (and also Firebug 1.12)</li><li><strong>Firefox 33 - 46</strong> with <b>Firebug 2.0</b></li></ul>\nFirebug integrates with Firefox to put a wealth of development tools at your fingertips while you browse. You can edit, debug, and monitor CSS, HTML, and JavaScript live in any web page.\n\nVisit the Firebug website for documentation and screen shots: <a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/835dbec6bd77fa1341bf5841171bc90e8a5d4069419f083a25b7f81f9fb254cb/http%3A//getfirebug.com">http://getfirebug.com</a>\nAsk questions on Firebug newsgroup: <a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/2398490bb3575c96d4cf9054e4f11236717aa6b9f353f5ada85dd8c74ed0dbbe/https%3A//groups.google.com/forum/%23%21forum/firebug">https://groups.google.com/forum/#!forum/firebug</a>\nReport an issue: <a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/82ba7e7d7600d78965967de98579334986246b827dcc5c8a0bcf0ba036ef62dd/http%3A//code.google.com/p/fbug/issues/list">http://code.google.com/p/fbug/issues/list</a>\n\n<i>Please note that bug reports or feature requests in comments on this page won\'t be tracked. Use the issue tracker or Firebug newsgroup instead thanks!</i>',
      u'ja': u'Firebug \u306f\u3001Web \u30da\u30fc\u30b8\u3092\u95b2\u89a7\u4e2d\u306b\u30af\u30ea\u30c3\u30af\u4e00\u3064\u3067\u4f7f\u3048\u308b\u8c4a\u5bcc\u306a\u958b\u767a\u30c4\u30fc\u30eb\u3092 Firefox \u306b\u7d71\u5408\u3057\u307e\u3059\u3002\u3042\u306a\u305f\u306f\u3042\u3089\u3086\u308b Web \u30da\u30fc\u30b8\u306e CSS\u3001HTML\u3001\u53ca\u3073 JavaScript \u3092\u30ea\u30a2\u30eb\u30bf\u30a4\u30e0\u306b\u7de8\u96c6\u3001\u30c7\u30d0\u30c3\u30b0\u3001\u307e\u305f\u306f\u30e2\u30cb\u30bf\u3059\u308b\u3053\u3068\u304c\u51fa\u6765\u307e\u3059\u3002',
      u'pl': u'Firebug integruje si\u0119 z Firefoksem, by doda\u0107 bogactwo narz\u0119dzi programistycznych dost\u0119pnych b\u0142yskawicznie podczas u\u017cywania przegl\u0105darki. Mo\u017cna edytowa\u0107, analizowa\u0107 kod oraz monitorowa\u0107 CSS, HTML i JavaScript bezpo\u015brednio na dowolnej stronie internetowej\u2026\n\nAby zapozna\u0107 si\u0119 z dokumentacj\u0105, zrzutami ekranu lub skorzysta\u0107 z forum dyskusyjnego, przejd\u017a na stron\u0119: <a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/835dbec6bd77fa1341bf5841171bc90e8a5d4069419f083a25b7f81f9fb254cb/http%3A//getfirebug.com">http://getfirebug.com</a>',
      u'pt-PT': u'O Firebug integra-se com o Firefox para colocar um conjunto de ferramentas de desenvolvimento nas suas m\xe3os enquanto navega. Pode editar, depurar e monitorizar CSS, HTML e JavaScript, em tempo real e em qualquer p\xe1gina Web\u2026\n\nVisite o s\xedtio do Firebug para obter documenta\xe7\xe3o, screen shots, e f\xf3runs de discuss\xe3o: <a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/835dbec6bd77fa1341bf5841171bc90e8a5d4069419f083a25b7f81f9fb254cb/http%3A//getfirebug.com">http://getfirebug.com</a>',
      u'ro': u'Firebug \xee\u021bi ofer\u0103 \xeen Firefox o gr\u0103mad\u0103 de unelte de dezvoltare \xeen timp ce navighezi. Po\u021bi edita, depana, monitoriza CSS-ul, HTML \u0219i codul JavaScript \xeen timp real \xeen orice pagin\u0103.\n\nViziteaz\u0103 saitul Firebug pentru documenta\u021bie, capturi de ecran \u0219i forumuri de discu\u021bii: <a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/835dbec6bd77fa1341bf5841171bc90e8a5d4069419f083a25b7f81f9fb254cb/http%3A//getfirebug.com">http://getfirebug.com</a>',
      u'ru': u'Firebug \u0438\u043d\u0442\u0435\u0433\u0440\u0438\u0440\u0443\u0435\u0442\u0441\u044f \u0432 Firefox \u0434\u043b\u044f \u0442\u043e\u0433\u043e, \u0447\u0442\u043e\u0431\u044b \u043f\u0440\u0438\u043d\u0435\u0441\u0442\u0438 \u0438\u0437\u043e\u0431\u0438\u043b\u0438\u0435 \u0441\u0440\u0435\u0434\u0441\u0442\u0432 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0438 \u043d\u0430 \u043a\u043e\u043d\u0447\u0438\u043a\u0438 \u0412\u0430\u0448\u0438\u0445 \u043f\u0430\u043b\u044c\u0446\u0435\u0432, \u0432 \u0442\u043e \u0432\u0440\u0435\u043c\u044f \u043a\u0430\u043a \u0412\u044b \u043f\u0443\u0442\u0435\u0448\u0435\u0441\u0442\u0432\u0443\u0435\u0442\u0435 \u043f\u043e \u0441\u0435\u0442\u0438. \u0412\u044b \u043c\u043e\u0436\u0435\u0442\u0435 \u0440\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c, \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0442\u044c \u043e\u0442\u043b\u0430\u0434\u043a\u0443 \u0438 \u043f\u0440\u043e\u0441\u043c\u0430\u0442\u0440\u0438\u0432\u0430\u0442\u044c CSS, HTML \u0438 JavaScript \u0432 \u0440\u0435\u0436\u0438\u043c\u0435 \u0440\u0435\u0430\u043b\u044c\u043d\u043e\u0433\u043e \u0432\u0440\u0435\u043c\u0435\u043d\u0438 \u043d\u0430 \u043b\u044e\u0431\u043e\u0439 \u0441\u0442\u0440\u0430\u043d\u0438\u0446\u0435 \u0432 \u0441\u0435\u0442\u0438...\n\n\u041f\u043e\u0441\u0435\u0442\u0438\u0442\u0435 \u0441\u0430\u0439\u0442 Firebug - \u0442\u0430\u043c \u0412\u044b \u043d\u0430\u0439\u0434\u0451\u0442\u0435 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430\u0446\u0438\u044e, \u0441\u043d\u0438\u043c\u043a\u0438 \u044d\u043a\u0440\u0430\u043d\u0430 \u0438 \u0444\u043e\u0440\u0443\u043c\u044b \u0434\u043b\u044f \u043e\u0431\u0441\u0443\u0436\u0434\u0435\u043d\u0438\u044f: <a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/835dbec6bd77fa1341bf5841171bc90e8a5d4069419f083a25b7f81f9fb254cb/http%3A//getfirebug.com">http://getfirebug.com</a>',
      u'vi': u'Firebug t\xedch h\u1ee3p v\xe0o Firefox v\xf4 s\u1ed1 c\xf4ng c\u1ee5 ph\xe1t tri\u1ec3n ngay tr\u01b0\u1edbc \u0111\u1ea7u ng\xf3n tay c\u1ee7a b\u1ea1n. B\u1ea1n c\xf3 th\u1ec3 ch\u1ec9nh s\u1eeda, g\u1ee1 l\u1ed7i, v\xe0 theo d\xf5i CSS, HTML v\xe0 JavaScript tr\u1ef1c ti\u1ebfp tr\xean b\u1ea5t k\xec trang web n\xe0o.\n\nV\xe0o trang web Firebug \u0111\u1ec3 xem t\xe0i li\u1ec7u, \u1ea3nh ch\u1ee5p m\xe0n h\xecnh, v\xe0 di\u1ec5n \u0111\xe0n th\u1ea3o lu\u1eadn: <a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/835dbec6bd77fa1341bf5841171bc90e8a5d4069419f083a25b7f81f9fb254cb/http%3A//getfirebug.com">http://getfirebug.com</a>',
      u'zh-CN': u'Firebug \u4e3a\u4f60\u7684 Firefox \u96c6\u6210\u4e86\u6d4f\u89c8\u7f51\u9875\u7684\u540c\u65f6\u968f\u624b\u53ef\u5f97\u7684\u4e30\u5bcc\u5f00\u53d1\u5de5\u5177\u3002\u4f60\u53ef\u4ee5\u5bf9\u4efb\u4f55\u7f51\u9875\u7684 CSS\u3001HTML \u548c JavaScript \u8fdb\u884c\u5b9e\u65f6\u7f16\u8f91\u3001\u8c03\u8bd5\u548c\u76d1\u63a7\u3002\\n\\n\u8bbf\u95ee Firebug \u7f51\u7ad9\u6765\u67e5\u770b\u6587\u6863\u3001\u622a\u5c4f\u4ee5\u53ca\u8ba8\u8bba\u7ec4\uff08\u82f1\u8bed\uff09\uff1a<a rel="nofollow" href="https://outgoing.prod.mozaws.net/v1/835dbec6bd77fa1341bf5841171bc90e8a5d4069419f083a25b7f81f9fb254cb/http%3A//getfirebug.com">http://getfirebug.com</a>'},
     u'e10s': u'compatible',
     u'edit_url': u'https://addons.mozilla.org/en-US/developers/addon/firebug/edit',
     u'guid': u'firebug@software.joehewitt.com',
     u'has_eula': False,
     u'has_privacy_policy': False,
     u'homepage': {u'en-US': u'http://getfirebug.com/',
      u'ja': u'http://getfirebug.com/jp'},
     u'icon_url': u'https://addons.cdn.mozilla.net/user-media/addon_icons/1/1843-64.png?modified=1476141618',
     u'id': 1843,
     u'is_disabled': False,
     u'is_experimental': False,
     u'is_source_public': True,
     u'last_updated': u'2016-10-10T22:39:32Z',
     u'name': {u'en-US': u'Firebug', u'ja': u'Firebug', u'pt-BR': u'Firebug'},
     u'previews': [{u'caption': {u'cs': u'',
        u'en-US': u'Command line and its auto-completion.'},
       u'id': 52710,
       u'image_url': u'https://addons.cdn.mozilla.net/user-media/previews/full/52/52710.png?modified=1295251100',
       u'thumbnail_url': u'https://addons.cdn.mozilla.net/user-media/previews/thumbs/52/52710.png?modified=1295251100'},
      {u'caption': {u'cs': u'',
        u'en-US': u'Console panel with an example error logs.'},
       u'id': 52711,
       u'image_url': u'https://addons.cdn.mozilla.net/user-media/previews/full/52/52711.png?modified=1295251100',
       u'thumbnail_url': u'https://addons.cdn.mozilla.net/user-media/previews/thumbs/52/52711.png?modified=1295251100'},
      {u'caption': {u'cs': u'', u'en-US': u'CSS panel with inline editor.'},
       u'id': 52712,
       u'image_url': u'https://addons.cdn.mozilla.net/user-media/previews/full/52/52712.png?modified=1295251100',
       u'thumbnail_url': u'https://addons.cdn.mozilla.net/user-media/previews/thumbs/52/52712.png?modified=1295251100'},
      {u'caption': {u'cs': u'',
        u'en-US': u'DOM panel displays structure of the current page.'},
       u'id': 52713,
       u'image_url': u'https://addons.cdn.mozilla.net/user-media/previews/full/52/52713.png?modified=1295251100',
       u'thumbnail_url': u'https://addons.cdn.mozilla.net/user-media/previews/thumbs/52/52713.png?modified=1295251100'},
      {u'caption': {u'cs': u'',
        u'en-US': u'HTML panel shows markup of the current page.'},
       u'id': 52714,
       u'image_url': u'https://addons.cdn.mozilla.net/user-media/previews/full/52/52714.png?modified=1295251100',
       u'thumbnail_url': u'https://addons.cdn.mozilla.net/user-media/previews/thumbs/52/52714.png?modified=1295251100'},
      {u'caption': {u'cs': u'',
        u'en-US': u'Layout panel reveals layout of selected elements.'},
       u'id': 52715,
       u'image_url': u'https://addons.cdn.mozilla.net/user-media/previews/full/52/52715.png?modified=1295251100',
       u'thumbnail_url': u'https://addons.cdn.mozilla.net/user-media/previews/thumbs/52/52715.png?modified=1295251100'},
      {u'caption': {u'cs': u'',
        u'en-US': u'Net panel monitors HTTP communication.'},
       u'id': 52716,
       u'image_url': u'https://addons.cdn.mozilla.net/user-media/previews/full/52/52716.png?modified=1295251100',
       u'thumbnail_url': u'https://addons.cdn.mozilla.net/user-media/previews/thumbs/52/52716.png?modified=1295251100'},
      {u'caption': {u'cs': u'',
        u'en-US': u'Script panel allows to explore and debug JavaScript on the current page.'},
       u'id': 52717,
       u'image_url': u'https://addons.cdn.mozilla.net/user-media/previews/full/52/52717.png?modified=1295251101',
       u'thumbnail_url': u'https://addons.cdn.mozilla.net/user-media/previews/thumbs/52/52717.png?modified=1295251101'}],
     u'public_stats': True,
     u'ratings': {u'average': 4.4813, u'count': 1930},
     u'review_url': u'https://addons.mozilla.org/en-US/editors/review/1843',
     u'slug': u'firebug',
     u'status': u'public',
     u'summary': {u'en-US': u'Firebug integrates with Firefox to put a wealth of development tools at your fingertips while you browse. You can edit, debug, and monitor CSS, HTML, and JavaScript live in any web page...',
      u'ja': u'Firebug \u306f\u3001Web \u30da\u30fc\u30b8\u3092\u95b2\u89a7\u4e2d\u306b\u30af\u30ea\u30c3\u30af\u4e00\u3064\u3067\u4f7f\u3048\u308b\u8c4a\u5bcc\u306a\u958b\u767a\u30c4\u30fc\u30eb\u3092 Firefox \u306b\u7d71\u5408\u3057\u307e\u3059\u3002\u3042\u306a\u305f\u306f\u3042\u3089\u3086\u308b Web \u30da\u30fc\u30b8\u306e CSS\u3001HTML\u3001\u53ca\u3073 JavaScript \u3092\u30ea\u30a2\u30eb\u30bf\u30a4\u30e0\u306b\u7de8\u96c6\u3001\u30c7\u30d0\u30c3\u30b0\u3001\u307e\u305f\u306f\u30e2\u30cb\u30bf\u3059\u308b\u3053\u3068\u304c\u51fa\u6765\u307e\u3059\u3002',
      u'pl': u'Firebug dodaje do Firefoksa bogactwo narz\u0119dzi programistycznych. Mo\u017cna edytowa\u0107, analizowa\u0107 kod oraz monitorowa\u0107 CSS, HTML i JavaScript bezpo\u015brednio na dowolnej stronie internetowej\u2026\n\nFirebug 1.4 dzia\u0142a z Firefoksem 3.0 i nowszymi wersjami.',
      u'pt-PT': u'O Firebug integra-se com o Firefox para colocar um conjunto de ferramentas de desenvolvimento nas suas m\xe3os enquanto navega. Pode editar, depurar e monitorizar CSS, HTML e JavaScript, em tempo real e em qualquer p\xe1gina Web\u2026\n\nFb1.4 req o Firefox 3.0+',
      u'ro': u'Firebug \xee\u021bi ofer\u0103 \xeen Firefox o gr\u0103mad\u0103 de unelte de dezvoltare \xeen timp ce navighezi. Po\u021bi edita, depana, monitoriza CSS, HTML \u0219i JavaScript \xeen timp real \xeen orice pagin\u0103...\n\nFirebug 1.4 necesit\u0103 Firefox 3.0 sau o versiune mai recent\u0103.',
      u'ru': u'Firebug \u0438\u043d\u0442\u0435\u0433\u0440\u0438\u0440\u0443\u0435\u0442\u0441\u044f \u0432 Firefox \u0434\u043b\u044f \u0442\u043e\u0433\u043e, \u0447\u0442\u043e\u0431\u044b \u043f\u0440\u0438\u043d\u0435\u0441\u0442\u0438 \u0438\u0437\u043e\u0431\u0438\u043b\u0438\u0435 \u0441\u0440\u0435\u0434\u0441\u0442\u0432 \u0440\u0430\u0437\u0440\u0430\u0431\u043e\u0442\u043a\u0438 \u043d\u0430 \u043a\u043e\u043d\u0447\u0438\u043a\u0438 \u0412\u0430\u0448\u0438\u0445 \u043f\u0430\u043b\u044c\u0446\u0435\u0432, \u0432 \u0442\u043e \u0432\u0440\u0435\u043c\u044f \u043a\u0430\u043a \u0412\u044b \u043f\u0443\u0442\u0435\u0448\u0435\u0441\u0442\u0432\u0443\u0435\u0442\u0435 \u043f\u043e \u0441\u0435\u0442\u0438.\n\n\u0414\u043b\u044f \u0440\u0430\u0431\u043e\u0442\u044b Firebug 1.4 \u0442\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f Firefox 3.0 \u0438\u043b\u0438 \u0432\u044b\u0448\u0435.',
      u'vi': u'Firebug t\xedch h\u1ee3p v\xe0o Firefox v\xf4 s\u1ed1 c\xf4ng c\u1ee5 ph\xe1t tri\u1ec3n ngay tr\u01b0\u1edbc \u0111\u1ea7u ng\xf3n tay c\u1ee7a b\u1ea1n. B\u1ea1n c\xf3 th\u1ec3 ch\u1ec9nh s\u1eeda, g\u1ee1 l\u1ed7i, v\xe0 theo d\xf5i CSS, HTML v\xe0 JavaScript tr\u1ef1c ti\u1ebfp tr\xean b\u1ea5t k\xec trang web n\xe0o...\n\nFirebug 1.4 y\xeau c\u1ea7u Firefox 3.0 ho\u1eb7c cao h\u01a1n.',
      u'zh-CN': u'Firebug \u4e3a\u4f60\u7684 Firefox \u96c6\u6210\u4e86\u6d4f\u89c8\u7f51\u9875\u7684\u540c\u65f6\u968f\u624b\u53ef\u5f97\u7684\u4e30\u5bcc\u5f00\u53d1\u5de5\u5177\u3002\u4f60\u53ef\u4ee5\u5bf9\u4efb\u4f55\u7f51\u9875\u7684 CSS\u3001HTML \u548c JavaScript \u8fdb\u884c\u5b9e\u65f6\u7f16\u8f91\u3001\u8c03\u8bd5\u548c\u76d1\u63a7\u2026\\n\\nFirebug 1.4 \u4ec5\u652f\u6301 Firefox 3.0 \u6216\u66f4\u9ad8\u7248\u672c\u3002'},
     u'support_email': None,
     u'support_url': {u'en-US': u'http://getfirebug.com'},
     u'tags': [u'ads',
      u'ads filter refinement',
      u'console',
      u'css',
      u'debugging',
      u'developer',
      u'development',
      u'dom',
      u'firebug',
      u'html',
      u'javascript',
      u'js',
      u'logging',
      u'minacoda',
      u'network',
      u'performance',
      u'profile',
      u'restartless',
      u'web',
      u'xpath'],
     u'type': u'extension',
     u'url': u'https://addons.mozilla.org/en-US/firefox/addon/firebug/',
     u'weekly_downloads': 103304}
