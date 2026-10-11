"""Every check that must pass before a deploy (run by .github/workflows/ci.yml on each push, or by hand):
- the scoring regression cases (node tests/score.test.js);
- the app's inline scripts, sw.js, score.js and every api/*.js parse;
- every Python file in collector/, api/ and tests/ compiles.
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


html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
with tempfile.TemporaryDirectory() as tmp:
    for i, js in enumerate(re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", html, re.S)):
        f = os.path.join(tmp, f"inline{i}.js")
        open(f, "w", encoding="utf-8").write(js)
        node_check(f, f"index.html script {i}")
for f in ["sw.js", "score.js"] + sorted(glob.glob(os.path.join(ROOT, "api", "*.js"))):
    node_check(os.path.join(ROOT, f), os.path.relpath(os.path.join(ROOT, f), ROOT))
for f in sorted(glob.glob(os.path.join(ROOT, "collector", "*.py")) + glob.glob(os.path.join(ROOT, "api", "*.py")) + glob.glob(os.path.join(ROOT, "tests", "*.py"))):
    try:
        py_compile.compile(f, doraise=True, cfile=os.path.join(tempfile.gettempdir(), "parcours_check.pyc"))
    except py_compile.PyCompileError as e:
        failed.append(f"{os.path.relpath(f, ROOT)}: {str(e)[:300]}")
r = subprocess.run(["node", os.path.join(ROOT, "tests", "score.test.js")], capture_output=True, text=True)
print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "score tests: no output")
if r.returncode:
    failed.append("scoring cases:\n" + "\n".join(l for l in r.stdout.splitlines() if not l.startswith("PASS")))

print("\n".join(failed) if failed else "all checks passed")
sys.exit(1 if failed else 0)
