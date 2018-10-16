#!/usr/bin/env python

# Takes raw HTML from stdin as scraped from Knowledge Repo and "staticizes" it
# by removing the navigation chrome that required the KR database and modifying
# paths to static assets.

import sys

from bs4 import BeautifulSoup

with open(sys.argv[1]) as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

for div in soup.find_all("div", {'class':'navbar'}):
    div.decompose()

for div in soup.find_all("div", {'class':'btn-group'}):
    div.decompose()

for div in soup.find_all("button"):
    div.decompose()

for div in soup.find_all("div", {'class':'footer'}):
    div.decompose()

for div in soup.find_all("div", {'id':'pageview_stats'}):
    div.parent.decompose()

for span in soup.find_all("span", {'class':'tags'}):
    span.decompose()

soup.find("textarea").parent.parent.parent.parent.parent.parent.decompose()

for item in soup.find_all(src=True):
    src = item['src'] or ""
    if src.startswith('/static/'):
        item['src'] = 'https://reports.telemetry.mozilla.org' + src

for item in soup.find_all(href=True):
    href = item['href'] or ""
    if href.startswith('/static/'):
        item['href'] = 'https://reports.telemetry.mozilla.org' + href

print(soup)
