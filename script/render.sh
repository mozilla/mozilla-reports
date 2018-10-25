#!/bin/bash

# Render all content in publishable form to a site/ directory.

set -exo pipefail

# Move to the root of the git repository.
cd $(git rev-parse --show-toplevel)

REPORT_DIRS=$(find . -name 'report.json' | awk -F/ '{print $2}' | grep -v 'stage' | grep -v 'site' | sort | uniq)

rm -rf stage/ && mkdir -p stage/

# Copy in html content to stage/ directory.
for d in $REPORT_DIRS; do
    cp -r $d stage/
done

# Copy in static resources to stage directory once we have them in the repo.
cp -r static/ stage/static/

# Generate the site content using docere.
python -m docere.cli render --knowledge-repo stage/ --outdir site/
