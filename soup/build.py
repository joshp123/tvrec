"""Rebuild data/soup.sqlite from the files in data/raw/ and private/.

    uv run python -m soup.build

Work happens in DuckDB (data/work/build.duckdb, deleted afterwards); the
result is written to SQLite. See docs/schema.md for the tables.
"""

import sqlite3
import time

from . import extra, household, imdb, ratings, text
from .db import SOUP, WORK, connect

STEPS = [
    imdb.build,
    ratings.movielens, ratings.letterboxd, ratings.amazon, ratings.netflix,
    ratings.movietweetings, ratings.trakt,
    extra.tvtropes, extra.wikidata,
    text.plex, text.wikipedia, text.amazon, text.genome, text.assemble,
    household.load,
]

# Table -> indexes. Every table in the soup is listed here.
TABLES = {
    "source": ["create unique index source_pk on source(name)"],
    "title": ["create unique index title_pk on title(tconst)", "create index title_kind on title(kind, imdb_votes)"],
    "person": ["create unique index person_pk on person(nconst)"],
    "credit": ["create index credit_tconst on credit(tconst)", "create index credit_nconst on credit(nconst)"],
    "title_link": ["create unique index title_link_pk on title_link(tconst)"],
    "title_fact": ["create index title_fact_tconst on title_fact(tconst)", "create index title_fact_value on title_fact(fact, value_id)"],
    "title_trope": ["create index title_trope_tconst on title_trope(tconst)", "create index title_trope_trope on title_trope(trope)"],
    "trope": ["create unique index trope_pk on trope(trope)"],
    "title_similar": ["create index title_similar_tconst on title_similar(tconst)"],
    "plex_title": ["create unique index plex_title_pk on plex_title(tconst)"],
    "plot": ["create index plot_tconst on plot(tconst)"],
    "public_score": ["create index public_score_tconst on public_score(tconst)"],
    "tag_genome": ["create index tag_genome_tconst on tag_genome(tconst)"],
    "movielens_tag": ["create index movielens_tag_tconst on movielens_tag(tconst)"],
    "rater": ["create unique index rater_pk on rater(user_key)"],
    "source_item": ["create unique index source_item_pk on source_item(item_key)", "create index source_item_tconst on source_item(tconst)"],
    "rating": ["create index rating_tconst on rating(tconst)", "create index rating_user on rating(user_key)"],
    "watch": ["create index watch_tconst on watch(tconst)", "create index watch_user on watch(user_key)"],
    "play": ["create index play_tconst on play(tconst)"],
    "verdict": [],
}

SOURCES = """
create or replace table source as select * from (values
    ('movielens', 'ratings', 0.5, 5.0),
    ('letterboxd', 'ratings', 0.5, 5.0),
    ('amazon', 'ratings', 1.0, 5.0),
    ('netflix', 'ratings', 1.0, 5.0),
    ('movietweetings', 'ratings', 0.0, 10.0),
    ('trakt', 'ratings', 1.0, 10.0)
) as t(name, kind, scale_min, scale_max)
"""


def export(con):
    tmp = SOUP.with_suffix(".sqlite.tmp")
    tmp.unlink(missing_ok=True)
    con.execute("install sqlite; load sqlite")
    con.execute(f"attach '{tmp}' as soup (type sqlite)")
    have = {r[0] for r in con.execute("select table_name from information_schema.tables where table_catalog = 'build'").fetchall()}
    for t in TABLES:
        if t in have:
            con.execute(f"create table soup.{t} as select * from {t}")
    con.execute("detach soup")
    db = sqlite3.connect(tmp)
    for t, idx in TABLES.items():
        if t in have:
            for sql in idx:
                db.execute(sql)
    db.execute("analyze")
    db.commit()
    db.close()
    tmp.replace(SOUP)


def main():
    path = WORK / "build.duckdb"
    path.unlink(missing_ok=True)
    con = connect()
    con.execute(SOURCES)
    for step in STEPS:
        t = time.time()
        step(con)
        print(f"{step.__module__.split('.')[-1]}.{step.__name__}: {time.time() - t:.0f}s", flush=True)
    t = time.time()
    export(con)
    print(f"export: {time.time() - t:.0f}s", flush=True)
    con.close()
    path.unlink()


if __name__ == "__main__":
    main()
