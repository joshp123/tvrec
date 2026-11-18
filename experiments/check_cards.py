"""Check a cards file for invention: every factual claim in the written text
("what", "why", "why not") should trace to a fact the writer was handed
(private/cards/<person>.facts.json, written by cards.py). A second model lists the claims and marks each one
supported or not, and whether it is true to its knowledge.

Usage: python check_cards.py PERSON   writes private/cards/<person>.check.json"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import household
from eval_verdicts import claude

PRIVATE = household.PRIVATE


def check(args):
    card, given = args
    facts = given or {k: v for k, v in card.items() if k not in ("what", "why", "why_not", "poster", "art", "trailer")}
    prompt = ("Below are the facts handed to a writer about one title, then what the writer wrote for a card. List "
              "every factual claim the writer makes about the title or its people (not opinions, not claims about "
              "the reader's taste or their own titles' verdicts), and for each say whether the facts given support "
              "it, and separately whether, to your knowledge, it is true.\n\n"
              f"FACTS:\n{json.dumps(facts, ensure_ascii=False)}\n\nWRITTEN:\nwhat: {card.get('what')}\n"
              f"why: {card.get('why')}\nwhy not: {card.get('why_not', '')}\n\n"
              'Reply with only JSON: {"claims": [{"claim": "...", "supported": true|false, "true": true|false|null}]}')
    res = claude(prompt, "You are a careful fact-checker.") or {}
    return card["imdb_id"], card["title"], res.get("claims", [])


def main(person):
    cards = json.loads((PRIVATE / "cards" / f"{person}.json").read_text())["cards"]
    given = {it["imdb_id"]: it for it in json.loads((PRIVATE / "cards" / f"{person}.facts.json").read_text())}
    with ThreadPoolExecutor(4) as ex:
        res = list(ex.map(check, [(c, given.get(c["imdb_id"])) for c in cards]))
    out = [{"imdb_id": i, "title": t, "claims": c} for i, t, c in res]
    (PRIVATE / "cards" / f"{person}.check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    claims = [x for r in out for x in r["claims"]]
    bad = [x for x in claims if not x.get("supported")]
    print(f"{len(cards)} cards, {len(claims)} factual claims, {len(bad)} not supported by the facts given, "
          f"{sum(x.get('true') is False for x in bad)} of those false, {sum(x.get('true') is None for x in bad)} unsure")


if __name__ == "__main__":
    main(sys.argv[1])
