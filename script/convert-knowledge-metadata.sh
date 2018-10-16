#!/bin/bash

# Pull yaml frontmatter from knowledge.md files and convert to docere report.json.

# Move to the root of the git repository.
cd $(git rev-parse --show-toplevel)

for d in $(find $PWD -name '*.kp' -type d); do
    echo "processing $d"
    cat "$d"/knowledge.md \
        | sed 's/\(201.-..-..\).*/"\1"/' \
        | sed 's/created_at/publish_date/' \
        | python -c 'import sys, yaml, json; json.dump(next(yaml.load_all(sys.stdin)), sys.stdout, indent=4)' \
                 > "$d"/report.json
    #jupyter nbconvert "$d"/orig_src/*.ipynb
    #sed '/^---$/,/^---$/d' "$d"/orig_src/*.html > "$d"/index.html
    #rm "$d"/orig_src/*.html
done
