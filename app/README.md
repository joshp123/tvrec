# Picks page

A phone page that shows one pick at a time as a card and records each answer.

    python3 app/server.py

It listens on this machine only (`TVREC_HOST` names another address, such as
the one on a private network), port 8788 (`TVREC_PORT`), and reads and writes
under `private/` (`TVREC_PRIVATE`). Open it from a phone over the tailnet.

## What it reads: `private/cards/<person>.json`

One file per person; the file name is the person. The server rereads it on
every request, so a new file shows up on the next page load.

```json
{
  "person": "...",
  "taste_map": {
    "clusters": [{"name": "...", "description": "...", "strength": 0.8,
                  "examples": [title], "nearby": [title], "neighbours": ["cluster name"]}],
    "away_from": [title]
  },
  "cards": [{"imdb_id": "tt...", "title": "...", "year": 2024, "end_year": null,
             "kind": "series", "seasons": 2, "runtime_min": 55, "country": "...",
             "pick_kind": "...", "cluster": "cluster name", "what": "...", "why": "...",
             "links": ["favourite"], "imdb_rating": 8.1, "imdb_votes": 120000,
             "rt_critics": 92, "rt_audience": 77, "poster": "https://...", "in_library": false}],
  "seen_deck": [{"imdb_id": "tt...", "title": "...", "year": 2008, "kind": "film",
                 "runtime_min": 110, "what": "...", "poster": "https://..."}]
}
```

`title` is `{"imdb_id", "title", "year", "kind", "poster"}`. Missing fields are
left off the card. `"sample": true` marks a stand-in file from `app/sample.py`;
the taste map then carries a placeholder notice.

## What it writes: `private/swipes.jsonl`

One answer per line:

```json
{"person": "...", "imdb_id": "tt...", "answer": "want", "note": "...", "ts": "2026-11-18T09:53:02+0100"}
```

`answer` is one of `want`, `not_for_me`, `seen_loved`, `seen_fine`,
`seen_disliked`, `dont_know`. `note` is present only when one was written. A
later line for the same person and title replaces an earlier one. In the
"have you seen this?" deck, "Not seen" is written as `dont_know`.

An answer is sent five seconds after it is given, or sooner when the next
answer comes or the page is hidden; Undo within those five seconds sends
nothing.
