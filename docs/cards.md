# Cards file: fields beyond app/README.md

`experiments/cards.py PERSON [OTHER]` writes `private/cards/<person>.json` in
the shape `app/README.md` describes. It adds the fields below; a field with
no value is left out.

## Taste map

`taste_map.clusters` are **shelves**, the map's top level (`shelves.py`): a
handful per person, each grouping 20 to 40 fine clusters. Added per shelf:

- `clusters`: names of up to five fine clusters on the shelf that the person's
  titles sit in, strongest first.

## Cards

- `episodes`, `hours`: total episodes and approximate viewing hours (series).
- `status`: "running" or "ended YEAR", with the last episode's date when known.
- `pick_kind` ends in " (stretch)" for picks from a cluster next to the
  person's own rather than in it.
- `why_not`: the strongest thing against it for this person; may be empty.
- `art`: a wide background image.
- `trailer`: a YouTube URL (TMDB's video list, type Trailer).
- `makers`, `cast`: `[{name, role?, known_from: [{title, yours?}]}]`; `yours`
  is "liked" (their own verdict) or "on your Plex".
- `season_ratings`: `[{season, ratings: [IMDb rating per episode], average}]`.
- `closest`: titles nearest by shared audience, `{imdb_id, title, year, kind,
  closeness, flag?}`; `flag` is "you like it", "on your Plex" or
  "<Other> asked for it".
- `awards` (names), `nominations` (count), `made_for` (broadcaster or
  network), `based_on`.
- `for_other`: `{name, linked_titles, evidence_titles}`: which of the other
  person's own titles point to this one, and how many of their own verdicts
  there are to go on.
- `evidence`: the data the text is written from, whoever writes it:
  `cluster`, `relation` (in their cluster, or a stretch next to which one),
  `links` (`{imdb_id, title, how: "shared audience" | "shared maker",
  fans_who_also_loved_it?, fans?, maker?}`), `differs` (how it differs from
  their own titles) and `against` (what counts against it).

## Seen deck

Each entry adds `in_library`.
