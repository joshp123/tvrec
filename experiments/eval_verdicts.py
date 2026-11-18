"""Experiment: can a frontier model tell what a person would say about a title,
and why, better than the classical evidence alone? Uses the person's own
stated verdicts, one hidden at a time; nothing for them to read.

For each hidden verdict:
- model, named: the frontier model sees the person's other verdicts with
  their words, and the hidden title's facts and evidence; it gives a verdict
  (love, like, dislike), a "why you" and a "why not";
- model, anonymous: the same with the title, people's names and other titles
  removed, to see how much rests on knowing the title's reputation;
- no model: the ranker's evidence, turned into a verdict by fixed rules and
  into reasons by templates.
Then a second model, blind to which is which, judges whether each reason
matches what the person actually said, and lists factual claims in the model
texts that the facts handed over do not support.

Writes eval_verdicts.json under data/work/exp/ (holds the person's words, so it
is copied to private/ as well; the summary printed names no titles).

Usage: python eval_verdicts.py PERSON"""
import json
import random
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

import evidence as EV
import household
import picks as P
from core import W

PRIVATE = household.PRIVATE
FAMOUS = 100_000


def claude(prompt, system="You are a film and television expert."):
    out = subprocess.run(["claude", "-p", "--model", "opus", "--tools", "", "--strict-mcp-config", "--safe-mode",
                          "--setting-sources", "", "--system-prompt", system, "--no-session-persistence"],
                         input=prompt, capture_output=True, text=True, timeout=900, cwd="/tmp").stdout
    m = re.search(r"[\[{].*[\]}]", out, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None


def without(person, t):
    q = household.Person(person.name, dict(person.evidence), set(person.known), dict(person.words), set(person.answered))
    q.evidence.pop(t, None)
    q.words.pop(t, None)
    q.known.discard(t)
    q.in_library = person.in_library
    return q


def classical(F, q, t, cl, S, placed):
    """Verdict and reasons from the ranker's evidence alone."""
    own, reach, against = P.profile(q, cl, S)
    c = cl.get(t)
    lk, _ = P.links(q, pd.DataFrame(index=[t]))
    l = lk.get(t, {})
    pos = l.get("likes", 0)
    neg = l.get("dislike", 0)
    maker = l.get("maker", 0)
    strength = own[c] if c is not None else 0
    against_c = against[c] if c is not None else 0
    if neg > pos or (against_c > 0 and strength < 0.1):
        verdict = "dislike"
    elif strength >= 0.5 or maker >= 0.3 or pos >= 0.02:
        verdict = "love"
    elif strength > 0 or pos > 0 or maker > 0 or (c is not None and reach[c] > 0.3):
        verdict = "like"
    else:
        verdict = "dislike"
    why = []
    if "likes_from" in l:
        why.append(f"people who loved {F.title(l['likes_from'])} also loved it")
    if "maker_from" in l:
        why.append(f"made by {F.people.get(l['maker_who'], '?')}, who made {F.title(l['maker_from'])}")
    if c is not None and strength > 0:
        mates = [F.title(u) for u, (w, why_) in q.evidence.items() if w > 0 and why_.startswith("said") and cl.get(u) == c][:2]
        if mates:
            why.append(f"it sits in your cluster with {', '.join(mates)}")
    why_not = []
    if neg > 0:
        dis = [u for u, (w, _) in q.evidence.items() if w < 0]
        why_not.append("its audience overlaps with titles you disliked" + (f" such as {F.title(dis[0])}" if dis else ""))
    if not why:
        why_not.append("nothing links it to your titles")
    if placed.get(t) != "likes":
        why_not.append("too few ratings to place it by audience")
    return {"verdict": verdict, "why": "; ".join(why) or "no link found", "why_not": "; ".join(why_not)}


def facts_for(F, t, q, cl, names, placed, anonymous):
    c = cl.get(t)
    e = EV.build(F, t, q, None, f"{names.get(str(c), {}).get('name', '')}: {names.get(str(c), {}).get('description', '')}"
                 if c is not None else "", "", {}, None, placed.get(t, "likes"))
    r = F.ti.loc[t]
    item = {"title": r.title, "year": int(r.start_year) if r.start_year == r.start_year else None,
            "kind": "series" if r.is_series else "film", "genres": r.genres, "imdb_rating": r.imdb_rating,
            "summary": PLOTS.get(t, ""),
            "evidence": {k: e[k] for k in ("format", "status", "makers", "cast", "closest", "awards", "against", "cluster",
                                           "made_for") if k in e}}
    if anonymous:
        names_to_hide = [r.title] + [m["name"] for m in e["makers"]] + [x["name"] for x in e["cast"]]
        item = {"title": "(hidden)", "year": item["year"], "kind": item["kind"], "genres": item["genres"],
                "summary": item["summary"], "country": F.pm.country.get(t) if t in F.pm.index else None,
                "cluster": e.get("cluster"), "format": e.get("format")}
        s = json.dumps(item, ensure_ascii=False)
        for n in names_to_hide:
            if n and len(n) > 2:
                s = s.replace(n, "(name)")
        item = json.loads(s)
    return item


PLOTS = {}


def main(person):
    import content
    import duckdb
    global PLOTS
    PLOTS = content.display_plots(800)
    p = household.load(person)
    F = EV.Facts()
    cl, S = P.load_map()
    names = json.loads((W / "clusters.json").read_text())
    placed = dict(duckdb.sql(f"select t, placed_by from '{W}/map.parquet'").fetchall())
    hidden = [t for t, (w, why) in p.evidence.items() if why.startswith("said") and why[6:] in ("loved", "liked", "disliked")
              and t in F.ti.index]
    truth = {t: {"loved": "love", "liked": "like", "disliked": "dislike"}[p.evidence[t][1][6:]] for t in hidden}
    cases = []
    for t in hidden:
        q = without(p, t)
        others = [f"- {F.title(u)}: {why[6:]}" + (f' ("{q.words[u]}")' if q.words.get(u) else "")
                  for u, (w, why) in q.evidence.items() if why.startswith("said") and u in F.ti.index]
        cases.append({"t": t, "imdb_id": F.ti.tconst[t], "title": F.title(t), "votes": int(F.ti.imdb_votes[t] or 0),
                      "truth": truth[t], "words": p.words.get(t, ""), "others": "\n".join(others),
                      "named": facts_for(F, t, q, cl, names, placed, False),
                      "anonymous": facts_for(F, t, q, cl, names, placed, True),
                      "classical": classical(F, q, t, cl, S, placed)})

    def ask_model(args):
        case, variant = args
        prompt = (f"A viewer's own verdicts on titles, with their words:\n{case['others']}\n\n"
                  "Here is a title they have not been asked about, with facts about it. Would they love it, like it "
                  "or dislike it? Then write what a card on their phone would say: \"why\" it is for them (or why "
                  "they would not like it), tied to their own titles and words, and \"why_not\", the strongest thing "
                  "against it for them. Use only the facts given and what you reliably know.\n\n"
                  f"{json.dumps(case[variant], ensure_ascii=False)}\n\n"
                  'Reply with only JSON: {"verdict": "love"|"like"|"dislike", "why": "...", "why_not": "..."}')
        return case["imdb_id"], variant, claude(prompt)

    jobs = [(c, v) for c in cases for v in ("named", "anonymous")]
    with ThreadPoolExecutor(4) as ex:
        for iid, variant, res in ex.map(ask_model, jobs):
            case = next(c for c in cases if c["imdb_id"] == iid)
            case["model_" + variant] = res or {}

    # Blind judge: does each reason match what the person said?
    def judge(case):
        opts = [("classical", case["classical"]), ("model_named", case.get("model_named", {})),
                ("model_anonymous", case.get("model_anonymous", {}))]
        random.Random(case["t"]).shuffle(opts)
        listing = "\n".join(f"{chr(65 + i)}: verdict {o.get('verdict')}; why: {o.get('why')}; why not: {o.get('why_not')}"
                            for i, (_, o) in enumerate(opts))
        prompt = (f"A viewer said this about \"{case['title']}\": verdict {case['truth']}; their words: \"{case['words']}\".\n\n"
                  f"Three systems guessed, without seeing those words:\n{listing}\n\n"
                  "For each of A, B, C: does its reasoning (why and why not together) match the viewer's own reason? "
                  "Answer match, partly or no, with a few words on why. Judge the reason, not the verdict.\n"
                  'Reply with only JSON: {"A": {"reason": "match"|"partly"|"no", "note": "..."}, "B": {...}, "C": {...}}')
        res = claude(prompt, "You are a careful, strict assessor.") or {}
        return case["imdb_id"], {name: res.get(chr(65 + i), {}) for i, (name, _) in enumerate(opts)}

    with ThreadPoolExecutor(4) as ex:
        for iid, res in ex.map(judge, cases):
            next(c for c in cases if c["imdb_id"] == iid)["judged"] = res

    # Invention: factual claims in the named model texts that the facts given do not support.
    def check(case):
        m = case.get("model_named", {})
        prompt = ("Below are facts handed to a writer, then what the writer wrote. List every factual claim the "
                  "writer makes about the title or its people (not opinions, not claims about the viewer's taste), "
                  "and for each say whether the facts given support it.\n\n"
                  f"FACTS:\n{json.dumps(case['named'], ensure_ascii=False)}\n\nWRITTEN:\nwhy: {m.get('why')}\nwhy not: {m.get('why_not')}\n\n"
                  'Reply with only JSON: {"claims": [{"claim": "...", "supported": true|false}]}')
        res = claude(prompt, "You are a careful fact-checker.") or {}
        return case["imdb_id"], res.get("claims", [])

    with ThreadPoolExecutor(4) as ex:
        for iid, claims in ex.map(check, cases):
            next(c for c in cases if c["imdb_id"] == iid)["claims"] = claims

    for c in cases:
        c.pop("others")
    out = json.dumps(cases, indent=1, ensure_ascii=False, default=str)
    (PRIVATE / "eval_verdicts.json").write_text(out)

    # Summary without titles.
    def score(c, k):
        v = (c["classical"] if k == "classical" else c.get(k, {})).get("verdict")
        return v == c["truth"], (v == "dislike") == (c["truth"] == "dislike")
    for group, sel in (("all", lambda c: True), ("less famous", lambda c: c["votes"] < FAMOUS),
                       ("famous", lambda c: c["votes"] >= FAMOUS)):
        cs = [c for c in cases if sel(c)]
        print(f"\n{group}: {len(cs)} verdicts")
        for k in ("classical", "model_named", "model_anonymous"):
            exact = sum(score(c, k)[0] for c in cs)
            side = sum(score(c, k)[1] for c in cs)
            reasons = [c["judged"].get(k, {}).get("reason") for c in cs]
            print(f"  {k:16} verdict exact {exact}/{len(cs)}, like-or-dislike right {side}/{len(cs)}, "
                  f"reason match {reasons.count('match')}, partly {reasons.count('partly')}, no {reasons.count('no')}")
    claims = [x for c in cases for x in c.get("claims", [])]
    print(f"\nmodel (named) factual claims: {len(claims)}, unsupported by the facts given: "
          f"{sum(not x.get('supported') for x in claims)}")


if __name__ == "__main__":
    main(sys.argv[1])
