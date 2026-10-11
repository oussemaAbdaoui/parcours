"""Sources engine health check: runs each source once and checks it returns well-formed offers.

  python tests/sources_check.py            # cloud sources (as on GitHub)
  python tests/sources_check.py --home     # PC sources (stealth browser, home connection)
  python tests/sources_check.py Jobindex   # only the named sources

A source fails when it raises, returns nothing, or returns offers missing the fields the collector and the app
rely on. Exit code 1 if any source failed.
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
import sources  # noqa: E402

KEYWORDS = ["LLM engineer", "machine learning engineer", "AI engineer", "ingénieur IA", "développeur IA", "machine learning"]
COUNTRIES = {"fr", "de", "ca", "ch", "gl", "tn", "be", "nl", "lu", "se", "dk", "no", "fi", "ma", "ie", "xx"}
# Sources that need a key or a login: skipped when it is missing rather than failed.
NEEDS = {"LinkedIn posts": "SERPER_API_KEY", "Poli": "POLI_EMAIL"}


def problems(x):
    p = []
    for k in ("id", "title", "url", "source", "c", "kind"):
        if not x.get(k):
            p.append(f"no {k}")
    if x.get("url") and not str(x["url"]).startswith("http"):
        p.append("url not http")
    if x.get("c") and x["c"] not in COUNTRIES:
        p.append(f"country {x['c']!r}")
    if x.get("kind") not in ("job", "phd", "master", None):
        p.append(f"kind {x.get('kind')!r}")
    return p


def main():
    # Welcome to the Jungle remembers the offers it opened: a check must not use the real memory, or the next
    # collector run would skip the offers the check read.
    import tempfile
    sources.WTTJ_SEEN = os.path.join(tempfile.gettempdir(), "parcours-wttj-seen-check.json")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    table = sources.HOME_SCRAPERS if "--home" in sys.argv else sources.SCRAPERS
    picked = {k: v for k, v in table.items() if not args or k in args}
    failed = 0
    for name, fn in picked.items():
        if NEEDS.get(name) and not os.environ.get(NEEDS[name]):
            print(f"SKIP  {name:24} needs {NEEDS[name]}")
            continue
        t = time.time()
        try:
            out = fn(KEYWORDS)
        except Exception as e:
            failed += 1
            print(f"FAIL  {name:24} error: {str(e)[:120]}")
            continue
        bad = [(x.get("title", "?")[:40], problems(x)) for x in out if problems(x)]
        texts = sum(1 for x in out if len(x.get("desc") or "") >= 400)
        ok = out and len(bad) <= len(out) // 10  # a few odd records are tolerated, not a broken parser
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:24} {len(out):4} offers, {texts:4} with full text, {time.time() - t:5.0f}s"
              + (f" | malformed {len(bad)}: {bad[:2]}" if bad else "") + ("" if out else " | returned nothing"))
    print(f"\n{len(picked) - failed}/{len(picked)} sources passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
