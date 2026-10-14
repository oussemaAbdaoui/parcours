"""Sync engine, sandboxed: the real page served locally, a fake server, every write captured and never sent.

Scenario A: fresh device (empty browser), server has data -> the device shows the server's data and sends no deletion.
Scenario B: server came back empty, device has data -> the device sends its own copy back (adds only, no deletion).
"""
import json
import os
import time
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
now = int(time.time() * 1000)


def full_state():
    return {"apps": [{"id": f"a{i}", "role": f"Role {i}", "org": f"Org {i}", "stage": "applied", "result": "open", "date": "2026-10-01"} for i in range(12)],
            "saved": [], "journal": [], "searches": [], "feeds": [], "contacts": [], "queue": [], "status": {"tn:job:1": "done"},
            "notes": {}, "profile": {"name": "Test", "skills": ["python"], "countries": ["fr"]}, "updatedAt": now}


def empty_state():
    return {"apps": [], "saved": [], "journal": [], "searches": [], "feeds": [], "contacts": [], "queue": [], "status": {}, "notes": {},
            "profile": {}, "updatedAt": now + 5000}


def run(server_state, local_state=None):
    writes = []

    def route(r):
        u, m = r.request.url, r.request.method
        if "://parcours.test" not in u:
            return r.abort()
        path = u.split("parcours.test", 1)[1].split("?")[0]
        if not path.startswith("/api/"):
            f = os.path.join(ROOT, "admin.html" if path in ("/", "/admin", "/admin.html") else path.lstrip("/"))
            if os.path.isfile(f):
                return r.fulfill(status=200, body=open(f, "rb").read(), content_type="text/html" if f.endswith(".html") else "application/javascript")
            return r.fulfill(status=404, body="")
        if m != "GET":
            writes.append({"path": path, "body": json.loads(r.request.post_data or "{}")})
            return r.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        if path == "/api/ping" or u.endswith("/api/state?ping=1"):
            return r.fulfill(status=200, content_type="application/json", body='{"ok":true,"sync":true,"ai":false,"sources":{}}')
        if path == "/api/state":
            return r.fulfill(status=200, content_type="application/json", body=json.dumps({"state": server_state, "version": now, "store": "neon"}))
        return r.fulfill(status=200, content_type="application/json", body="{}")

    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.route("**/*", route)
        # Seeded before any page script runs, on the one and only load (a first load would save its own empty state).
        page.add_init_script("localStorage.setItem('parcours-pw', 'x');"
                             + (f"localStorage.setItem('parcours-v1', {json.dumps(json.dumps(local_state))});" if local_state else ""))
        page.goto("http://parcours.test/", wait_until="networkidle")
        page.wait_for_timeout(4000)
        shown = page.evaluate("() => ({apps: state.apps.length, profile: Object.keys(state.profile || {}).length})")
        b.close()
    return shown, writes, errors


def summary(writes):
    adds = dels = 0
    for w in writes:
        ch = (w["body"].get("changes") or {})
        for it in ch.get("items") or []:
            if it.get("data") is None:
                dels += 1
            else:
                adds += 1
    return adds, dels


shown, writes, errors = run(full_state(), None)
a, d = summary(writes)
print(f"A fresh device: shows {shown['apps']} applications (server has 12), profile fields {shown['profile']}; writes: {a} adds, {d} deletions; errors: {errors or 'none'}")
print("   ", "PASS" if shown["apps"] == 12 and d == 0 else "FAIL")

shown, writes, errors = run(empty_state(), full_state())
a, d = summary(writes)
print(f"B empty server, device has data: keeps {shown['apps']} applications; writes: {a} adds, {d} deletions; errors: {errors or 'none'}")
print("   ", "PASS" if shown["apps"] == 12 and a >= 12 and d == 0 else "FAIL")
