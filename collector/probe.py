"""Fetches pages with Scrapling's StealthyFetcher and saves the HTML, to write or debug parsers.

  python collector/probe.py URL [URL ...]   -> probe-out/<n>.html plus a short summary
"""
import os
import re
import sys
from collections import Counter

from scrapling.fetchers import StealthyFetcher

os.makedirs("probe-out", exist_ok=True)
for n, url in enumerate(sys.argv[1:], 1):
    try:
        page = StealthyFetcher.fetch(url, headless=True, solve_cloudflare=True, network_idle=True, timeout=90000)
    except Exception as e:
        print(f"[{n}] {url}\n    ERROR {e}")
        continue
    html = page.html_content if hasattr(page, "html_content") else str(page.body)
    with open(f"probe-out/{n}.html", "w", encoding="utf8") as f:
        f.write(html)
    title = (page.css("title::text").get() or "").strip()
    classes = Counter(c for c in re.findall(r'class="([^"]{3,80})"', html))
    print(f"[{n}] {url}\n    status {page.status}  title {title[:80]!r}  {len(html)} bytes")
    for c, k in classes.most_common(12):
        if k >= 5:
            print(f"    {k:4} x {c}")
