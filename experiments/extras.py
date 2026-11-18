"""Per-pick extras, fetched only for titles shown as cards and cached:
- trailers: YouTube links from TMDB, through the household's Seerr on the
  media server (its API key is read there and never leaves it);
- a fuller "what it is": the premise, synopsis or plot section of the
  English Wikipedia article, where the Plex summary is thin.

SEERR_HOST, or PLEX_SSH in private/plex.env, names the machine Seerr runs on (never a
literal here)."""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request

from core import W

ROOT = W.parent.parent.parent
CACHE = W / "extras.json"
SECTIONS = ("premise", "synopsis", "plot", "summary", "story", "overview")

REMOTE = r"""
KEY=$(python3 -c 'import json;print(json.load(open("/var/lib/media/seerr/settings.json"))["main"]["apiKey"])')
while read kind id; do
  printf '%s %s ' "$kind" "$id"
  curl -s -m 20 -H "X-Api-Key: $KEY" "http://127.0.0.1:5055/api/v1/$kind/$id" | python3 -c '
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    d={}
print(json.dumps([{"name":v.get("name"),"type":v.get("type"),"url":v.get("url")} for v in d.get("relatedVideos") or [] if v.get("site")=="YouTube"]))'
done
"""


def host():
    if os.environ.get("SEERR_HOST"):
        return os.environ["SEERR_HOST"]
    for line in open(ROOT / "private" / "plex.env"):
        if line.startswith("PLEX_SSH="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("set SEERR_HOST")


def trailers(wanted):
    """wanted: {tconst: ('tv'|'movie', tmdb_id)} -> {tconst: [videos]}"""
    if not wanted:
        return {}
    lines = "\n".join(f"{k} {i}" for k, i in wanted.values()) + "\n"
    script = REMOTE.replace("done\n", "done <<'IDS'\n" + lines + "IDS\n", 1)
    res = subprocess.run(["ssh", host(), "bash -s"], input=script, capture_output=True, text=True, timeout=600)
    by_id = {}
    for line in res.stdout.splitlines():
        kind, i, rest = line.split(" ", 2)
        by_id[(kind, i)] = json.loads(rest)
    return {t: by_id.get((k, str(i)), []) for t, (k, i) in wanted.items()}


def wiki_section(page):
    url = ("https://en.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1&format=json&redirects=1&titles="
           + urllib.parse.quote(page))
    req = urllib.request.Request(url, headers={"User-Agent": "tvrec/0.1 (personal research script)"})
    pages = json.load(urllib.request.urlopen(req, timeout=30))["query"]["pages"]
    text = next(iter(pages.values())).get("extract", "")
    parts = re.split(r"\n={2,3} *([^=\n]+?) *={2,3}\n", text)
    for i in range(1, len(parts) - 1, 2):
        if any(parts[i].lower().startswith(s) for s in SECTIONS):
            body = parts[i + 1].strip()
            if len(body) > 200:
                return body[:2500]
    return None


def fetch(tconsts, links):
    """links: {tconst: {'tmdb_tv'|'tmdb_movie': id, 'enwiki': page}}. Returns {tconst: {...}}."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    need_tr = {t: (("tv", links[t]["tmdb_tv"]) if links[t].get("tmdb_tv") else ("movie", links[t]["tmdb_movie"]))
               for t in tconsts if t in links and "trailers" not in cache.get(t, {})
               and (links[t].get("tmdb_tv") or links[t].get("tmdb_movie"))}
    for t, v in trailers(need_tr).items():
        cache.setdefault(t, {})["trailers"] = v
    for t in tconsts:
        c = cache.setdefault(t, {})
        if "premise" not in c:
            page = links.get(t, {}).get("enwiki")
            try:
                c["premise"] = wiki_section(urllib.parse.unquote(page)) if page else None
            except Exception:
                c["premise"] = None
    CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    return {t: cache.get(t, {}) for t in tconsts}
