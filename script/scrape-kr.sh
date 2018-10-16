#!/bin/bash

# Scrape existing rendered Knowledge Repo pages and store as static html.

# Move to the root of the git repository.
cd $(git rev-parse --show-toplevel)

for d in $(find . -name '*week?.kp' -type d); do
    echo "$d"
    url="http://reports.telemetry.mozilla.org/post/${d/.\//}"
    echo $url
    curl "$url" -o "$d/rendered_from_kr.html"
done
