"""Quick live check of each JobSpy site through api/boards.py (run on GitHub Actions: Try script workflow)."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))
from boards import _search  # noqa: E402

CASES = [
    ("glassdoor", {"q": "machine learning engineer", "c": "fr", "loc": "Paris", "type": ""}),
    ("glassdoor", {"q": "machine learning engineer", "c": "de", "loc": "Berlin", "type": ""}),
    ("zip_recruiter", {"q": "machine learning engineer", "c": "ca", "loc": "Toronto", "type": ""}),
    ("zip_recruiter", {"q": "machine learning engineer", "c": "gl", "loc": "Remote", "type": ""}),
    ("google", {"q": "machine learning engineer", "c": "fr", "loc": "Paris", "type": ""}),
    ("google", {"q": "software engineer", "c": "tn", "loc": "Tunis", "type": ""}),
    ("bayt", {"q": "software engineer", "c": "tn", "loc": "Tunis", "type": ""}),
    ("indeed", {"q": "machine learning engineer", "c": "ch", "loc": "Zurich", "type": ""}),
]
for site, q in CASES:
    t = time.time()
    try:
        r = _search(site, q, results=15, hours=24 * 14)
        print(f"{site:14} {q['c']}  {len(r):3} jobs  {time.time() - t:5.1f}s")
        for j in r[:2]:
            print(f"      {j['title'][:55]:55} | {j['company'][:22]:22} | {j['location'][:28]}")
    except Exception as e:
        print(f"{site:14} {q['c']}  ERROR {str(e)[:150]}  ({time.time() - t:.1f}s)")
