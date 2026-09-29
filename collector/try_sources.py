"""Runs each scraper once and prints what it returns (raw, before the topic filter). Run with the Try script workflow."""
import sys
import time

import sources

KEYWORDS = ["machine learning", "software engineer", "data scientist"]
names = sys.argv[1:] or list(sources.SCRAPERS) + list(sources.STEALTH_SCRAPERS)
every = dict(sources.SCRAPERS, **sources.STEALTH_SCRAPERS)
for name in names:
    t = time.time()
    try:
        items = every[name](KEYWORDS)
        print(f"{name:18} {len(items):4} items  {time.time() - t:5.1f}s")
        for x in items[:3]:
            print(f"      [{x['kind']:3}] {x['title'][:50]:50} | {x['org'][:22]:22} | {x['location'][:18]:18} | {x.get('posted') or x.get('deadline')}")
        bad = [x for x in items if not x["title"] or not x["url"].startswith("http")]
        if bad:
            print(f"      {len(bad)} items missing title or url")
    except Exception as e:
        print(f"{name:18} ERROR {type(e).__name__}: {str(e)[:150]}  ({time.time() - t:.1f}s)")
