#!/bin/bash

for d in $(find $PWD -name '*.kp' -type d); do
    echo "d is $d"
    ./script/remove-nav.py "$d/rendered_from_kr.html" > "$d/index.html"
done
