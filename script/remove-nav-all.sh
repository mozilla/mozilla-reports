#!/bin/bash

# Move to the root of the git repository.
cd $(git rev-parse --show-toplevel)

for d in $(find $PWD -name '*.kp' -type d); do
    echo "d is $d"
    ./script/remove-nav.py "$d/rendered_from_kr.html" > "$d/index.html"
done
