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
agree. Candidates are ranked by people in common, title match, year and kind
agreement, then closeness of year. When the top two are level on all of
those, the most-voted title wins only with at least five times the votes of
the next; otherwise the item stays unmatched. The result is
`_match(item_id, tconst, method)`.
"""

# Season or volume wording at the end of a title ("The Wire: Season 1",
# "Seinfeld: Seasons 1 & 2"): stripped before matching, marks a series.
SEASON = (r"(?i)[\s:,\-–(]+(the\s+)?("
          r"(seasons?|series)\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten|[ivx]+)\b"
          r"|(complete\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|final)\s+(seasons?|series)\b"
          r"|complete\s+(seasons?|series|collection)\b"
          r").*$")

PEOPLE_ROLES = "('director','creator','writer','actor')"


def run(con, year_fallback=False):
    """Match `_item` into `_match`. With `year_fallback`, items left unmatched
    are tried again ignoring their year, for sources whose year is a release
    date of a DVD or streaming edition rather than of the title."""
    _run(con)
    if year_fallback:
        con.execute("create or replace table _match1 as select * from _match")
        con.execute("create or replace table _item1 as select * from _item")
        con.execute("create or replace table _item as select * replace (null::int as year) from _item1 where item_id not in (select item_id from _match1)")
        _run(con)
        con.execute("create or replace table _match as select * from _match1 union all select item_id, tconst, method || ' (any year)' from _match")
        con.execute("create or replace table _item as select * from _item1")
        con.execute("drop table _match1; drop table _item1")


def _run(con):
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
    select n.item_id, c.tconst, count(distinct n.key) as hits, any_value(nn.n_names) as n_names
    from names n
    join (select item_id, count(*) as n_names from names group by 1) nn using (item_id)
    join _person_key p using (key)
    join credit c on c.nconst = p.nconst and c.role in {PEOPLE_ROLES}
    group by all
    """)

    con.execute("""
    create or replace table _cand as
    with c as (
        select coalesce(t.item_id, p.item_id) as item_id,
               coalesce(t.tconst, p.tconst) as tconst,
               t.trank, coalesce(p.hits, 0) as hits, p.n_names
        from _cand_title t full join _cand_people p using (item_id, tconst)),
    f as (
        select c.*, i.year, i.kind as want_kind, t.kind, t.is_series, t.start_year, t.end_year, t.imdb_votes,
               i.year is null
                 or abs(t.start_year - i.year) <= 1
                 or (t.is_series and i.year between t.start_year and coalesce(t.end_year, 9999) + 1) as year_ok,
               i.kind is null
                 or (i.kind = 'series' and t.is_series)
                 or (i.kind = 'film' and t.kind <> 'tvSeries') as kind_ok,
               coalesce(abs(t.start_year - i.year), 99) as year_diff
        from c join _item i using (item_id) join title t using (tconst))
    select * from f
    where (hits >= 2 and kind_ok and year_ok and hits >= least(n_names, 6) / 2)
       or (trank is not null and (hits >= 1 or (year_ok and kind_ok)))
    """)

    con.execute("""
    create or replace table _match as
    with ranked as (
        select *, row_number() over (partition by item_id order by
                     hits desc, trank asc nulls last, year_ok desc, kind_ok desc,
                     year_diff asc, imdb_votes desc, tconst) as pos
        from _cand),
    top2 as (
        select a.*, b.hits as hits2, b.trank as trank2, b.year_ok as year_ok2,
               b.kind_ok as kind_ok2, b.year_diff as year_diff2, b.imdb_votes as votes2
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
       or (coalesce(trank, 9), year_ok, kind_ok, year_diff)
          <> (coalesce(trank2, 9), year_ok2, kind_ok2, year_diff2)
       or imdb_votes >= 5 * greatest(votes2, 1)
    """)

