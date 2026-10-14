"""Every check that must pass before a deploy (run by .github/workflows/ci.yml on each push, or by hand):
- the scoring regression cases (node tests/score.test.js), the sync server's wipe guards (tests/state_guard.test.js) and the
  public accounts, sandboxed in an in-memory Postgres (tests/users.test.js; needs npm ci);
- the inline scripts of both pages (index.html: login and public app, admin.html: the admin app), sw.js, score.js and every api/*.js parse;
- every Python file in collector/, api/ and tests/ compiles;
- data/sources.csv lists every source the collectors use (tests/sources_csv.py).
Exit code 1 on any failure. Run: python tests/check.py
"""
import glob
import os
import py_compile
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failed = []


def node_check(path, label):
    r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
    if r.returncode:
        failed.append(f"{label}: {r.stderr.strip()[:300]}")


with tempfile.TemporaryDirectory() as tmp:
    for page in ("index.html", "admin.html"):
        html = open(os.path.join(ROOT, page), encoding="utf-8").read()
        for i, js in enumerate(re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S)):
            f = os.path.join(tmp, f"{page}-{i}.js")
            open(f, "w", encoding="utf-8").write(js)
            node_check(f, f"{page} script {i}")
for f in ["sw.js", "score.js"] + sorted(glob.glob(os.path.join(ROOT, "api", "*.js"))):
    node_check(os.path.join(ROOT, f), os.path.relpath(os.path.join(ROOT, f), ROOT))
for f in sorted(glob.glob(os.path.join(ROOT, "collector", "*.py")) + glob.glob(os.path.join(ROOT, "api", "*.py")) + glob.glob(os.path.join(ROOT, "tests", "*.py"))):
    try:
        py_compile.compile(f, doraise=True, cfile=os.path.join(tempfile.gettempdir(), "parcours_check.pyc"))
    except py_compile.PyCompileError as e:
        failed.append(f"{os.path.relpath(f, ROOT)}: {str(e)[:300]}")
for test, label in (("score.test.js", "scoring cases"), ("state_guard.test.js", "sync guards"), ("users.test.js", "public accounts")):
    r = subprocess.run(["node", os.path.join(ROOT, "tests", test)], capture_output=True, text=True)
    print(f"{label}: " + (r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "no output"))
    if r.returncode:
        failed.append(f"{label}:\n" + "\n".join(l for l in r.stdout.splitlines() if not l.startswith("PASS")))

# .vercelignore must not leave out what the site runs on (requirements.txt once was: api/boards.py lost its packages).
import fnmatch
import json
rules = [l.strip() for l in open(os.path.join(ROOT, ".vercelignore"), encoding="utf-8") if l.strip() and not l.startswith("#")]


def ignored(path):
    out = False
    for rule in rules:
        neg, pat = rule.startswith("!"), rule.lstrip("!").strip("/")
        if fnmatch.fnmatch(path, pat) or path.startswith(pat + "/") or fnmatch.fnmatch(path.split("/")[0], pat) and "/" not in pat:
            out = not neg
    return out


cfg = json.load(open(os.path.join(ROOT, "vercel.json"), encoding="utf-8"))
needed = ["index.html", "admin.html", "sw.js", "score.js", "manifest.webmanifest", "logo-96.png", "logo-full.png", "favicon.ico", "favicon-64.png", "icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png", "package.json", "package-lock.json", "requirements.txt"]
needed += [os.path.relpath(f, ROOT).replace(os.sep, "/") for f in glob.glob(os.path.join(ROOT, "api", "*.*"))]
for fn in cfg.get("functions", {}).values():
    m = re.match(r"(.*)\{(.*)\}(.*)", fn.get("includeFiles", ""))
    needed += [m.group(1) + x + m.group(3) for x in m.group(2).split(",")] if m else ([fn["includeFiles"]] if fn.get("includeFiles") else [])
for f in needed:
    if ignored(f):
        failed.append(f".vercelignore leaves out {f}, which the site needs")
print("deploy files: " + ("missing some" if any(".vercelignore" in f for f in failed) else f"{len(needed)} needed files deployed"))

r = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "sources_csv.py")], capture_output=True, text=True)
print(r.stdout.strip().splitlines()[0] if r.stdout.strip() else "sources list: no output")
if r.returncode:
    failed.append("data/sources.csv is missing sources:\n" + r.stdout.strip())

print("\n".join(failed) if failed else "all checks passed")
sys.exit(1 if failed else 0)
