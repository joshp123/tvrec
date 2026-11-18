"""Match a rating source's items to IMDb titles.

The caller fills a table `_item` with one row per source item:
item_id, title, year, kind ('film', 'series' or null), people (names of
directors and cast, possibly empty). Evidence for a candidate title:

- title: the normalised item title, with or without edition wording,
  equals a normalised IMDb title or
  English alternative title (rank 0 for primary/original, 1 for an alias);
- people: how many of the item's names (directors, writers, cast) are
  credited on the title (for a series, on any of its episodes);
- year and kind agreement.

A candidate is accepted with a title match backed by one person or by year
and kind, or without a title match when at least two people, and at least
half of the item's names (up to six), are credited on it and year and kind
agree. A season's year inside a series' run counts as agreeing. Without two
people in common, a candidate is refused when the item has more than 20
times as many ratings as the title has IMDb votes: thousands of raters point
to a well-known title, not an obscure one of the same name. Candidates are
ranked by people in common, title match, year and kind agreement, then IMDb
votes. When the top two are level on all but votes, the most-voted wins only
with at least five times the votes of the next; otherwise the item stays
unmatched. The result is
`_match(item_id, tconst, method)`.
"""

# Season or volume wording at the end of a title ("The Wire: Season 1",
# "Seinfeld: Seasons 1 & 2"): stripped before matching, marks a series.
SEASON = (r"(?i)[\s:,\-–(]+(the\s+)?("
          r"(seasons?|series)\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten|[ivx]+)\b"
          r"|(complete\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|final)\s+(seasons?|series|year)\b"
          r"|complete\s+(seasons?|series|collection)\b"
          r").*$")

PEOPLE_ROLES = "('director','creator','writer','actor')"


def run(con, year_fallback=False):
    """Match `_item` into `_match`. With `year_fallback`, items left unmatched
    are tried again allowing three years' difference, for sources whose year
    is that of a DVD or streaming edition rather than of the title; that
    second pass needs a title match."""
    con.execute("create or replace table _item_n as select item_id, count(*) as n_ratings from _r group by 1")
    _run(con, 1)
    if year_fallback:
        con.execute("create or replace table _match1 as select * from _match")
        con.execute("create or replace table _item1 as select * from _item")
        con.execute("create or replace table _item as select * from _item1 where item_id not in (select item_id from _match1)")
        _run(con, 3)
        con.execute("create or replace table _match as select * from _match1 union all select item_id, tconst, method || ' (year within 3)' from _match")
        con.execute("create or replace table _item as select * from _item1")
        con.execute("drop table _match1; drop table _item1")


def _run(con, years):
    con.execute("""
    create or replace table _cand_title as
    with keys as (
        select item_id, norm(title) as key from _item
        union
        select item_id, norm(clean_title(title)) from _item)
    select i.item_id, k.tconst, min(k.rank) as trank
    from keys i join _title_key k using (key)
    group by all
    """)

    con.execute(f"""
    create or replace table _cand_people as
    with names as (
        select distinct item_id, norm_name(n) as key
        from (select item_id, unnest(people) as n from _item where len(people) > 0)
        where norm_name(n) is not null)
    , hits as (
        select distinct n.item_id, c.tconst, n.key
        from names n
        join _person_key p using (key)
        join credit c on c.nconst = p.nconst and c.role in {PEOPLE_ROLES})
    select h.item_id, h.tconst, count(*) as hits, any_value(nn.n_names) as n_names
    from hits h join (select item_id, count(*) as n_names from names group by 1) nn using (item_id)
    group by all
    """)

    con.execute(f"""
    create or replace table _cand as
    with c as (
        select coalesce(t.item_id, p.item_id) as item_id,
               coalesce(t.tconst, p.tconst) as tconst,
               t.trank, coalesce(p.hits, 0) as hits, p.n_names
        from _cand_title t full join _cand_people p using (item_id, tconst)),
    f as (
        select c.*, i.year, t.imdb_votes, coalesce(n.n_ratings, 0) as n_ratings,
               t.is_series and i.year between t.start_year and coalesce(t.end_year, 9999) + 1 as in_run,
               i.year is null or abs(t.start_year - i.year) <= {years} or in_run as year_ok,
               i.kind is null
                 or (i.kind = 'series' and t.is_series)
                 or (i.kind = 'film' and t.kind <> 'tvSeries') as kind_ok
        from c join _item i using (item_id) join title t using (tconst) left join _item_n n using (item_id))
    select * from f
    where ((hits >= 2 and kind_ok and year_ok and hits >= least(n_names, 6) / 2 and {years} = 1)
           or (trank is not null and (hits >= 1 or (year_ok and kind_ok))))
      -- Without two people in common, an item rated far more often than the
      -- IMDb title has votes is a different, better-known title.
      and (hits >= 2 or n_ratings <= 20 * greatest(imdb_votes, 1))
    """)

    con.execute("""
    create or replace table _match as
    with ranked as (
        select *, row_number() over (partition by item_id order by
                     hits desc, trank asc nulls last, year_ok desc, kind_ok desc,
                     imdb_votes desc, tconst) as pos
        from _cand),
    top2 as (
        select a.*, b.hits as hits2, b.trank as trank2, b.year_ok as year_ok2,
               b.kind_ok as kind_ok2, b.imdb_votes as votes2
        from ranked a left join ranked b on b.item_id = a.item_id and b.pos = 2
        where a.pos = 1)
    select item_id, tconst,
           case when hits >= 2 and trank is not null then 'title+people'
                when hits >= 2 then 'people'
                when hits = 1 then 'title+person'
                when year is not null then 'title+year'
                else 'title' end as method
    from top2
    where hits2 is null
       or hits > hits2
       or (coalesce(trank, 9), year_ok, kind_ok) <> (coalesce(trank2, 9), year_ok2, kind_ok2)
       or imdb_votes >= 5 * greatest(votes2, 1)
    """)
