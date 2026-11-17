# The soup: `data/soup.sqlite`

One SQLite file. Every title is keyed by its IMDb ID (`tconst`, `tt…`), every
person by IMDb name ID (`nconst`, `nm…`). Rebuild it with
`uv run python -m soup.build`; it reads `data/raw/` and `private/` only.

Lookups by `tconst`, `nconst` or `user_key` are indexed and fast in SQLite.
For aggregates over `rating` (161 million rows), attach the file in DuckDB,
which scans it in seconds where SQLite takes many minutes:

```python
import duckdb
con = duckdb.connect()
con.execute("install sqlite; load sqlite; attach 'data/soup.sqlite' as soup (type sqlite, read_only); use soup")
```

## Titles and makers (IMDb)

- `title`: every IMDb film, series, miniseries, TV film, special, video and
  short; no vote floor. `kind` is IMDb's type; `is_series` is 1 for
  `tvSeries` and `tvMiniSeries`. `imdb_rating`, `imdb_votes` (0 when
  unrated). For series: `n_seasons`, `n_episodes`, `episode_votes` (votes
  summed over episodes).
- `person`: everyone credited on a title in `title`.
- `credit(tconst, nconst, role, billing, episodes, job)`: who made what.
  `role` is IMDb's category (`actor` covers actresses), plus `creator` for
  writer credits IMDb marks "created by", "creator" or "developed by". For a
  series, credits on its episodes are rolled up to the series and `episodes`
  counts how many episodes the person is credited on; use it to tell a
  show's maker from a one-episode director. `billing` is IMDb's order on the
  title itself (low is prominent), null when the credit is only on episodes.

## Ratings by other people

- `rating(user_key, item_key, tconst, rating, ts)`: one row per rating in
  every data set. `tconst` is null when the item could not be matched to
  IMDb. `ts` is Unix seconds (null for Letterboxd).
- `rater(user_key, source, source_user)`: which data set each user is from.
  `user_key` is unique across sources.
- `source(name, kind, scale_min, scale_max)`: each rating scale.
- `source_item(item_key, source, item_id, title, year, kind, tconst,
  match_method, n_ratings)`: each data set's own items and how each was
  matched. `match_method` is `imdb_id` (the source gives it), `title+people`,
  `people`, `title+person`, `title+year`, `title`, with `(any year)` when the
  source's year was ignored; null when unmatched. Several items can share a
  `tconst` (Amazon's DVD and streaming editions, Netflix's season discs).
- `watch(user_key, tconst, plays, last_ts)`: Trakt users' watched films and
  shows (implicit feedback, up to each user's latest 100 of each).
- `movielens_tag(tconst, user, tag, ts)`: MovieLens users' free-text tags.
- `tag_genome(tconst, tag, relevance)`: MovieLens Tag Genome 2021 scores,
  films only.

"Users who rated X", across every data set:

```sql
select r.user_key, x.source, r.rating
from rating r join rater x using (user_key)
where r.tconst = 'tt0306414';
```

## Facts and text

- `public_score(tconst, scorer, score, votes)`: `imdb`; from Plex
  `rotten_tomatoes_critics`, `rotten_tomatoes_audience`, `tmdb` (all 0 to 10,
  no vote counts); and `<source>_average` per rating data set (on that
  source's scale, `votes` = number of ratings).
- `plot(tconst, source, text)`: `plex` (TMDB or TVDB summary), `wikipedia`
  (article lead section), `amazon` (product description).
- `title_link(tconst, wikidata, enwiki, tmdb_movie, tmdb_tv,
  rotten_tomatoes, metacritic, tvdb)`: IDs on other sites, from Wikidata.
- `title_fact(tconst, fact, value, value_id)`: Wikidata facts. `fact` is one
  of country, language, broadcaster, genre, main_subject, based_on, award,
  nomination, creator, showrunner, production_company. `value_id` is a
  Wikidata ID, or an IMDb name ID for creators and showrunners where known.
- `title_trope(tconst, trope)`, `trope(trope, description)`: TV Tropes.
- `title_similar(tconst, similar, source, rank)`: Plex's "similar" list,
  kept where the similar title is also in the soup.
- `plex_title(tconst, plex_guid, studio, content_rating, first_aired,
  tagline, countries, genres)`.

## The household (from `private/`, never committed)

- `play(viewed_at, tconst, type, title, episode_title, season, episode,
  device_id)`: every Plex play. Plays are the household's viewing, not
  anyone's verdict.
- `verdict(person, target, title, verdict, words, said_on)`: what each
  person has said. `target` is a `tconst` or an `nconst` (a maker).
  `verdict` is `loved`, `liked` or `disliked`; `words` is what they said.
