# tvrec

A TV and film discovery engine for one household. It builds a local database
from public data about titles, their makers and how people rated them, adds
the household's own viewing and verdicts, and ranks what to watch next.

Work in progress. The data sets and all household data stay local; see
[AGENTS.md](AGENTS.md).

## The soup

`data/soup.sqlite` holds every IMDb title, its makers, public scores, plot
text, and seven rating data sets matched to IMDb IDs. Tables:
[docs/schema.md](docs/schema.md). Sources and licences:
[docs/data-sources.md](docs/data-sources.md).

```sh
./fetch.sh                          # static data sets into data/raw/
uv run python -m soup.fetch_wikidata
uv run python -m soup.build         # data/raw/ + private/ -> data/soup.sqlite
uv run python -m soup.fetch_wikipedia
PLEX_TOKEN=... uv run python -m soup.fetch_plex
uv run python -m soup.fetch_household   # needs private/plex.env
uv run python -m soup.build         # again, to load the fetched text
```

The build reads only `data/raw/` and `private/`, takes about ten minutes and
peaks at about 10 GB of memory.
