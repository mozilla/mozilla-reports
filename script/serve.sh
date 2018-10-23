#!/bin/sh

# For local testing; starts a local HTTP server to render the site/ directory.

set -exo pipefail

# Move to the root of the git repository.
cd $(git rev-parse --show-toplevel)

# Move to the site dir
cd site/

python3 -m http.server
