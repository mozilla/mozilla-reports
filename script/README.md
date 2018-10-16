Scripts for converting content. This mostly exists for historical context
as the tools here were used for a one-time conversion from AirBnb's
Knowledge Repo to a static site generator.

The conversion can be run as follows:

```
python3 -m venv venv
source venv/bin/active
pip install beautifulsoup4 PyYAML
./script/convert-knowledge-metadata.sh
./script/scrape-kr.sh
./script/remove-nav-all.sh
```
