"""Download Wikidata facts about every item with an IMDb title ID, through
QLever's public SPARQL endpoint, into data/raw/wikidata/<name>.tsv.

    uv run python -m soup.fetch_wikidata
"""

import urllib.parse
import urllib.request

from .db import RAW

ENDPOINT = "https://qlever.dev/api/wikidata"
PREFIX = """
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX schema: <http://schema.org/>
"""
TITLE = '?item wdt:P345 ?imdb . FILTER(STRSTARTS(?imdb, "tt"))'
LABEL = '?v rdfs:label ?label FILTER(LANG(?label) = "en")'

# name -> SPARQL body. Each file is (imdb, value[, label]) pairs.
QUERIES = {
    # Item ID, English Wikipedia article and IDs on other sites.
    "ids": f"""SELECT ?imdb ?item ?enwiki ?tmdb_movie ?tmdb_tv ?rt ?metacritic ?tvdb WHERE {{ {TITLE}
        OPTIONAL {{ ?enwiki schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }}
        OPTIONAL {{ ?item wdt:P4947 ?tmdb_movie }} OPTIONAL {{ ?item wdt:P4983 ?tmdb_tv }}
        OPTIONAL {{ ?item wdt:P1258 ?rt }} OPTIONAL {{ ?item wdt:P1712 ?metacritic }}
        OPTIONAL {{ ?item wdt:P4835 ?tvdb }} }}""",
    "country": f"SELECT ?imdb ?v ?label WHERE {{ {TITLE} ?item wdt:P495 ?v . {LABEL} }}",
    "language": f"SELECT ?imdb ?v ?label WHERE {{ {TITLE} ?item wdt:P364 ?v . {LABEL} }}",
    "broadcaster": f"SELECT ?imdb ?v ?label WHERE {{ {TITLE} ?item wdt:P449 ?v . {LABEL} }}",
    "genre": f"SELECT ?imdb ?v ?label WHERE {{ {TITLE} ?item wdt:P136 ?v . {LABEL} }}",
    "main_subject": f"SELECT ?imdb ?v ?label WHERE {{ {TITLE} ?item wdt:P921 ?v . {LABEL} }}",
    "based_on": f"SELECT ?imdb ?v ?label WHERE {{ {TITLE} ?item wdt:P144 ?v . {LABEL} }}",
    "award": f"SELECT ?imdb ?v ?label WHERE {{ {TITLE} ?item wdt:P166 ?v . {LABEL} }}",
    "nomination": f"SELECT ?imdb ?v ?label WHERE {{ {TITLE} ?item wdt:P1411 ?v . {LABEL} }}",
    # People, with their IMDb name ID where Wikidata has one.
    "creator": f"SELECT ?imdb ?v ?label ?nm WHERE {{ {TITLE} ?item wdt:P170 ?v . {LABEL} OPTIONAL {{ ?v wdt:P345 ?nm }} }}",
    "showrunner": f"SELECT ?imdb ?v ?label ?nm WHERE {{ {TITLE} ?item wdt:P1431 ?v . {LABEL} OPTIONAL {{ ?v wdt:P345 ?nm }} }}",
    "production_company": f"SELECT ?imdb ?v ?label WHERE {{ {TITLE} ?item wdt:P272 ?v . {LABEL} }}",
}


def main():
    out = RAW / "wikidata"
    out.mkdir(parents=True, exist_ok=True)
    for name, body in QUERIES.items():
        data = urllib.parse.urlencode({"query": PREFIX + body}).encode()
        req = urllib.request.Request(ENDPOINT, data=data, headers={
            "Accept": "text/tab-separated-values", "User-Agent": "tvrec/0.1 (personal research)"})
        with urllib.request.urlopen(req, timeout=600) as r:
            (out / f"{name}.tsv").write_bytes(r.read())
        print(name, sum(1 for _ in open(out / f"{name}.tsv")) - 1, flush=True)


if __name__ == "__main__":
    main()
