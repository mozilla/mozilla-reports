Scripts used for local testing and continuous integration.

## Conversion from Knowledge Repo

Some of the scripts here exist only for historical on how we converted to
a static docere-based site from AirBnb's Knowledge Repo application.

The conversion can be run as follows:

```
python3 -m venv venv
source venv/bin/active
pip install beautifulsoup4 PyYAML
./script/convert-knowledge-metadata.sh
./script/scrape-kr.sh
./script/remove-nav-all.sh
```
