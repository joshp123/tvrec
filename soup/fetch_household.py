"""Read the household's Plex play history, read-only, into
private/plex_plays.json: one entry per play, with the IMDb ID of the film or
show played. Connection details come from private/plex.env (PLEX_SSH: a host
that can reach the server; PLEX_URL; PLEX_TOKEN_CMD: run on that host to
print the token). The token never leaves that host.

    uv run python -m soup.fetch_household
"""

import json
import shlex
import subprocess

from .db import PRIVATE


def env():
    out = {}
    for line in (PRIVATE / "plex.env").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            k, v = line.split("=", 1)
            out[k] = v
    return out


def get(cfg, path):
    remote = (f"T=$({cfg['PLEX_TOKEN_CMD']}); "
              f"curl -sf -H \"X-Plex-Token: $T\" -H 'Accept: application/json' {shlex.quote(cfg['PLEX_URL'] + path)}")
    r = subprocess.run(["ssh", cfg["PLEX_SSH"], remote], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout:
        return None
    return json.loads(r.stdout)["MediaContainer"]


def main():
    cfg = env()
    plays, start = [], 0
    while True:
        page = get(cfg, f"/status/sessions/history/all?sort=viewedAt:asc"
                        f"&X-Plex-Container-Start={start}&X-Plex-Container-Size=500")
        items = page.get("Metadata", [])
        plays += items
        start += len(items)
        if not items or start >= page["totalSize"]:
            break
    # The film or show each play belongs to, and its IMDb ID.
    keys = {p.get("grandparentKey") or p.get("key") for p in plays if p.get("type") in ("movie", "episode")}
    imdb = {}
    for key in sorted(k for k in keys if k):
        meta = get(cfg, key)
        guids = [g["id"] for m in (meta or {}).get("Metadata", []) for g in m.get("Guid", [])]
        imdb[key] = next((g.removeprefix("imdb://") for g in guids if g.startswith("imdb://")), None)
    out = [{
        "viewed_at": p["viewedAt"],
        "type": p["type"],
        "tconst": imdb.get(p.get("grandparentKey") or p.get("key")),
        "title": p.get("grandparentTitle") or p.get("title"),
        "episode_title": p.get("title") if p["type"] == "episode" else None,
        "season": p.get("parentIndex"),
        "episode": p.get("index"),
        "account_id": p.get("accountID"),
        "device_id": p.get("deviceID"),
    } for p in plays]
    (PRIVATE / "plex_plays.json").write_text(json.dumps(out, indent=1))
    print(len(out), "plays;", sum(1 for p in out if p["tconst"]), "with an IMDb ID")


if __name__ == "__main__":
    main()
