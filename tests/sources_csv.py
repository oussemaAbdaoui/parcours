"""data/sources.csv lists every source the app uses. This fails when a collector gains a source the file does not list,
so the list stays complete. Read from the code as text (no imports: the collectors need their own packages).
Run: python tests/sources_csv.py
"""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
read = lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read()
rows = list(csv.DictReader(open(os.path.join(ROOT, "data", "sources.csv"), encoding="utf-8-sig"), delimiter=";"))
squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
names = {squash(r["name"]) for r in rows}
code = " ".join(r["code"] for r in rows)
notes = " ".join(r["notes"] for r in rows)
missing = []

COLS = ["name", "url", "covers", "countries", "method", "status", "runs", "code", "key_needed", "alternance", "notes", "checked"]
if list(rows[0].keys()) != COLS:
    missing.append(f"columns changed: {list(rows[0].keys())}")
for r in rows:
    if r["status"] not in ("collected", "to add", "link only", "link (also collected)"):
        missing.append(f"{r['name']}: unknown status {r['status']!r}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["checked"]):
        missing.append(f"{r['name']}: checked must be a date (YYYY-MM-DD)")

# Scrapers: each function must appear in the code column, or its name as a row.
src = read("collector/sources.py")
for reg in ("SCRAPERS", "STEALTH_SCRAPERS", "HOME_SCRAPERS"):
    body = re.search(rf"^{reg} = \{{(.*?)\}}", src, re.S | re.M).group(1)
    for name, fn in re.findall(r'"([^"]+)":\s*([a-z_]+)', body):
        if fn not in code and squash(name) not in names:
            missing.append(f"collector/sources.py {reg}: {name} ({fn})")
# Company boards: one row per ATS, and every SuccessFactors employer and career page named in the notes.
boards = re.search(r"^COMPANY_BOARDS = \{(.*?)^\}", src, re.S | re.M).group(1)
for ats in re.findall(r'^\s+"([a-z]+)":', boards, re.M):
    if squash(ats + " company boards") not in names:
        missing.append(f"company boards: {ats}")
for company in re.findall(r'"[a-z0-9.-]+\.[a-z]+":\s*"([^"]+)"', re.search(r"^SF_SITES = \{(.*?)\}", src, re.S | re.M).group(1)):
    if company not in notes:
        missing.append(f"SuccessFactors employer: {company}")
for company in re.findall(r'\("([^"]+)", "https?://', re.search(r"^CAREER_PAGES = \[(.*?)\]$", src, re.S | re.M).group(1)):
    if company not in notes:
        missing.append(f"career page: {company}")
# Master's sources and scholarship schemes.
for fn in set(re.findall(r"lambda f, l: ([a-z_]+)\(", read("collector/masters.py"))) - {"country_schemes"}:
    if fn not in code:
        missing.append(f"collector/masters.py: {fn}")
for url in re.findall(r'^\s+"(https://[^"]+)",\n', re.search(r"^SCHEMES = \[(.*?)^\]", read("collector/masters.py"), re.S | re.M).group(1), re.M):
    if url not in {r["url"] for r in rows}:
        missing.append(f"scholarship scheme: {url}")
# Live search (api/jobs.js) and JobSpy sites (api/boards.py).
for s in sorted(set(re.findall(r"source: '([a-z]+)'", read("api/jobs.js")))):
    if s not in names:
        missing.append(f"api/jobs.js: {s}")
label = {"google": "googlejobs"}
for s in re.findall(r'"([a-z]+)":', re.search(r"^SITES = \{(.*?)\}", read("api/boards.py"), re.S | re.M).group(1)):
    if label.get(s, s) not in names:
        missing.append(f"api/boards.py: {s}")
# Collector scripts that read a source of their own.
for f in ("academia.py", "uk_register.py", "fr_register.py", "tn_startups.py", "insights.py", "poli.py"):
    if "collector/" + f not in code:
        missing.append(f"collector/{f}")

print(f"sources.csv: {len(rows)} sources" + ("; missing:\n  " + "\n  ".join(missing) if missing else ", all collectors listed"))
sys.exit(1 if missing else 0)
