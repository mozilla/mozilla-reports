# Mozilla Reports

## Introduction

This project is focussed on facilitating the sharing of knowledge between data scientists and other technical roles using. Data scientists are free to use whatever tools they like to generate static HTML and supporting resources.

## Getting started

You'll need a python environment with [docere](https://github.com/harterrt/docere) installed:

```
python3 -m venv venv
source venv/bin/active
pip install docere
```

Create a new subdirectory in this repository to house your work. The only requirement is that the directory contain an `index.html` with the body of your report and a `report.json` giving metadata (see [docere's explanation of report.json](https://github.com/harterrt/docere#submit-report-to-a-knowledge-repo)).

You can generate content locally by running:

    # Output goes to site/
    ./script/render.sh

Open a PR in GitHub to propose your changes. Once your change has been reviewed and merged, it should automatically be deployed to `https://mozilla.report`.
