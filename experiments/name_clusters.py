"""Name each map cluster from what is in it, with the frontier model through
the local `claude` command. Names are cached per cluster membership, so a
cluster is named once until its members change.

Writes clusters.json: id -> {name, description, coherent, members}.
Usage: python name_clusters.py [CLUSTER_ID...]"""
import hashlib
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import duckdb
import numpy as np

from core import W

BATCH, SHOW = 15, 25
OUT = W / "clusters.json"


def members(level="cluster"):
    d = np.load(W / "nb_full.npz")
    likers = dict(zip(d["items"], d["n"]))
    df = duckdb.sql(f"""
        select m.t, m.cluster, ti.title, ti.start_year, ti.is_series, ti.genres, ti.imdb_votes, pm.country
        from '{W}/map.parquet' m join '{W}/titles.parquet' ti using (t)
        left join '{W}/plex_meta.parquet' pm using (t)""").df()
    df["likers"] = df.t.map(likers).fillna(0)
    if level == "shelf":
        df["cluster"] = np.load(W / "shelves.npy")[df.cluster.values]
    out = {}
    for c, g in df.groupby("cluster"):
        g = g.sort_values(["likers", "imdb_votes", "t"], ascending=[False, False, True])
        out[int(c)] = [f"{r.title} ({r.start_year}, {'series' if r.is_series else 'film'}"
                       f"{', ' + r.country.split(',')[0] if isinstance(r.country, str) and r.country else ''}"
                       f"{', ' + r.genres if isinstance(r.genres, str) else ''})" for r in g.head(SHOW).itertuples()]
    return out


def ask(batch):
    text = "\n\n".join(f"Cluster {c}:\n" + "\n".join(m) for c, m in batch)
    prompt = (
        "Each cluster below is a group of films and TV series that the same audiences rate highly, found from "
        "millions of viewers' ratings and, for little-rated titles, shared makers and plot; titles are listed "
        "most-rated first. For each cluster, say what kind of "
        "thing it is, the way a well-read friend would name a shelf in a video shop: a specific name of 2 to 6 "
        "words (not a bare genre like 'Drama'), and one sentence on what the titles share in tone, era, origin "
        "or audience. If the cluster is mostly an accident of a data set (one era of DVD releases, one country's "
        "catalogue) rather than a taste, say so in the sentence. Set coherent to false if the titles have no "
        "real common thread.\n\nReply with only a JSON list of objects with keys id, name, description, "
        "coherent.\n\n" + text)
    out = subprocess.run(["claude", "-p", "--model", "opus", "--tools", "", "--strict-mcp-config", "--safe-mode",
                          "--setting-sources", "", "--system-prompt", "You are a film and television expert.",
                          "--no-session-persistence"], input=prompt, capture_output=True, text=True,
                         timeout=900, cwd="/tmp").stdout
    m = re.search(r"\[.*\]", out, re.S)
    return json.loads(m.group(0)) if m else []


def main(ids=None, level="cluster"):
    """Name the given clusters or shelves (all when None) whose members changed since last named."""
    OUT = W / ("shelves.json" if level == "shelf" else "clusters.json")
    mem = members(level)
    if ids is not None:
        mem = {c: m for c, m in mem.items() if c in set(ids)}
    cache = json.loads(OUT.read_text()) if OUT.exists() else {}
    key = {c: hashlib.sha1("\n".join(m).encode()).hexdigest()[:12] for c, m in mem.items()}
    todo = [(c, m) for c, m in mem.items() if cache.get(str(c), {}).get("key") != key[c]]
    print("clusters", len(mem), "to name", len(todo), flush=True)
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)]
    with ThreadPoolExecutor(4) as ex:
        for res in ex.map(ask, batches):
            for r in res:
                c = int(r["id"])
                if c in mem:
                    cache[str(c)] = {"name": r["name"], "description": r["description"],
                                     "coherent": bool(r.get("coherent", True)), "key": key[c], "members": mem[c][:10]}
    OUT.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    missing = [c for c in mem if cache.get(str(c), {}).get("key") != key[c]]
    print("named", len(mem) - len(missing), "missing", len(missing))


if __name__ == "__main__":
    level = "shelf" if "--shelves" in sys.argv else "cluster"
    main([int(x) for x in sys.argv[1:] if x.isdigit()] or None, level)
