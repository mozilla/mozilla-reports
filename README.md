# Mozilla Reports

This repository contains public data analyses.

You can find the rendered reports at:

- https://mozilla.report

# Adding a new report

First, fork this repository and clone the fork locally.
Be sure to set the `upstream` remote:

```sh
git remote add upstream git@github.com:mozilla/mozilla-reports.git
```

## Copy your report
Once you have a local copy of the repository,
copy your report to a new directory in this repository.
For example, if you have an analysis in `~/Documents/user_count/`:

```sh
cd mozilla-private-reports
cp -r ~/Documents/user_count ./user_count
```
Your report is **copied to the rendered site without any modifications**.
Be sure that your analysis directory
contains a fully rendered copy of your report

The entire directory is included in the rendered site,
so your report can be comprised of multiple pages

## Add metadata

Add a `report.json` file to your new directory.
This registers your index.html file as a report
and provides metadata necessary for generating the index pages.

The required fields are documented in [`docere`'s documentation](docere):
Here's a minimal example:

```json
{
  "title": "User Count Report",
  "publish_date": "2018-03-01",
  "author": "Wadley Hickam"
}
```

By default, [docere] looks links to an `index.html` file in your report directory.
You can override this by specifying a "file" key to `report.json`

## Preview your changes

We use [docere] to generate metadata pages for these reports.

Make sure you have a python environment with docere installed:

```bash
python3 -m venv venv
source venv/bin/active
pip install docere
```

And then you can preview content by invoking:

```bash
./script/render.sh
firefox site/index.html
```

## Publish

To publish your report, create a pull request and get review.
Once your report is merged to main,
it will automatically be pushed to [dev RTMO]

For example, using [GitHub's CLI, `hub`](https://github.com/github/hub):

```sh
git add .
git checkout -b user_count_report
git commit -am "Add user count report"
git push -u origin user_count_report
hub pull-request
```

[docere]: https://github.com/harterrt/docere
