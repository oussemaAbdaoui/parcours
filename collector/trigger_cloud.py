"""Starts the scheduled GitHub Actions workflows from the PC when GitHub's own schedule has skipped them: it is
best-effort and drops many runs (on 11 Oct: reminders 2 of 7, offers 3 of 8, companies 2 of 2 but 6 hours late).
Each workflow is started only when no run is queued or running and none started within its gap, so this only fills
the gaps. Needs the GitHub CLI (gh) logged in with the workflow scope.
Run by the PC task "Parcours collector" (daily at 11:00, or when the PC is next on): python collector/trigger_cloud.py"""
import json
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

REPO = "oussemaAbdaoui/parcours"
# workflow, minutes since the last run before it is due, hours (Tunis) it may start in
WORKFLOWS = [
    ("collect.yml", 1200, range(0, 24)),  # daily: started only if none ran in the last 20 hours
    ("remind.yml", 110, range(9, 21)),    # every 2 hours, 09:05 to 21:05 (remind.py sends at most one per 90 min)
    ("companies.yml", 660, range(0, 24)),  # twice a day
    ("academia.yml", 1380, range(0, 24)),  # daily
]


def gh(*args):
    return subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True, timeout=60)


now = datetime.now(timezone.utc)
hour = now.astimezone(ZoneInfo("Africa/Tunis")).hour
for workflow, gap, hours in WORKFLOWS:
    if hour not in hours:
        continue
    last = gh("run", "list", "--workflow", workflow, "--limit", "1", "--json", "status,createdAt")
    if last.returncode:
        print(f"{now:%Y-%m-%d %H:%M} {workflow}: could not list runs: {(last.stderr or '').strip()[:200]}")
        continue
    runs = json.loads(last.stdout or "[]")
    if runs:
        r = runs[0]
        age = (now - datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))).total_seconds() / 60
        if r["status"] in ("queued", "in_progress", "waiting", "pending") or age < gap:
            print(f"{now:%Y-%m-%d %H:%M} {workflow}: not needed (last: {r['status']}, {age:.0f} min ago)")
            continue
    started = gh("workflow", "run", workflow, "--ref", "main")
    print(f"{now:%Y-%m-%d %H:%M} {workflow}: " + ("started" if started.returncode == 0 else "failed: " + (started.stderr or "").strip()[:200]))
