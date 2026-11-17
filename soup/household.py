"""The household's own data, from private/ (never committed)."""

from .db import PRIVATE


def load(con):
    plays = PRIVATE / "plex_plays.json"
    if plays.exists():
        con.execute(f"""
        create or replace table play as
        select to_timestamp(viewed_at)::timestamp as viewed_at, tconst, type, title, episode_title,
               season, episode, device_id
        from read_json('{plays}')
        """)
    verdicts = PRIVATE / "verdicts.csv"
    if verdicts.exists():
        con.execute(f"""
        create or replace table verdict as
        select person, target, title, verdict, words, said_on::date as said_on
        from read_csv('{verdicts}', header=true, all_varchar=true)
        """)
