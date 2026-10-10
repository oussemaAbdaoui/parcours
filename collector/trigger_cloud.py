"""Starts the cloud collector (GitHub Actions "Collect opportunities") from the PC, because GitHub's own schedule
is best-effort and drops many runs. Skipped when a run is already queued or running, or started in the last
150 minutes, so it only fills the gaps. Needs the GitHub CLI (gh) logged in with the workflow scope.
Run by the PC task "Parcours collector": python collector/trigger_cloud.py"""
import json
import subprocess
from datetime import datetime, timezone

REPO, WORKFLOW, GAP_MIN = "oussemaAbdaoui/parcours", "collect.yml", 150


def gh(*args):
    return subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True, timeout=60)


last = gh("run", "list", "--workflow", WORKFLOW, "--limit", "1", "--json", "status,createdAt")
runs = json.loads(last.stdout or "[]") if last.returncode == 0 else []
now = datetime.now(timezone.utc)
if runs:
    r = runs[0]
    age = (now - datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))).total_seconds() / 60
    if r["status"] in ("queued", "in_progress", "waiting", "pending") or age < GAP_MIN:
        print(f"{now:%Y-%m-%d %H:%M} cloud run not needed (last: {r['status']}, {age:.0f} min ago)")
        raise SystemExit(0)
started = gh("workflow", "run", WORKFLOW, "--ref", "main")
print(f"{now:%Y-%m-%d %H:%M} cloud run " + ("started" if started.returncode == 0 else "failed: " + (started.stderr or "").strip()[:200]))
