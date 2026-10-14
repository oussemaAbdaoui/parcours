"""Public app (app.html), sandboxed end to end: tests/public_server.js serves the page and the real accounts handler
over an in-memory Postgres; a real browser signs up, chooses a path, reloads, signs out and in, and deletes the account.
Run: python tests/public_app_test.py
"""
import os
import subprocess
from playwright.sync_api import sync_playwright, expect

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PORT = 4179
URL = f"http://localhost:{PORT}/app"
server = subprocess.Popen(["node", os.path.join(ROOT, "tests", "public_server.js"), str(PORT)], stdout=subprocess.PIPE, text=True)
assert server.stdout.readline().strip() == "ready"
results = []


def check(name, fn):
    try:
        fn()
        results.append(True)
        print("PASS", name)
    except Exception as e:
        results.append(False)
        print("FAIL", name, "->", str(e).splitlines()[0][:200])


try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 390, "height": 844})
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL)
        check("first visit shows the sign-up form", lambda: expect(page.locator("#authBtn")).to_have_text("Create my account"))
        page.fill("#name", "Amel Ben Salah")
        page.fill("#email", "amel@example.tn")
        page.fill("#password", "short")
        page.click("#authBtn")
        check("short password explained", lambda: expect(page.locator("#authMsg")).to_contain_text("at least 8"))
        page.fill("#password", "long-enough-1")
        page.click("#authBtn")
        check("sign-up opens the app on Profile", lambda: expect(page.locator("main h2")).to_have_text("Profile"))
        check("the four sections are there", lambda: expect(page.locator("nav.tabs a")).to_have_count(4))
        page.locator("input[value=study]").check()
        page.wait_for_timeout(300)
        page.reload()
        check("still signed in after reload", lambda: expect(page.locator("#app")).to_be_visible())
        page.goto(URL + "#profile")
        check("chosen path saved on the server", lambda: expect(page.locator("input[value=study]")).to_be_checked())
        page.goto(URL + "#home")
        check("home greets by first name", lambda: expect(page.locator("main h2")).to_have_text("Hello Amel"))
        page.goto(URL + "#discover")
        page.click("[data-tab=alternance]")
        check("discover has an Alternance tab", lambda: expect(page.locator(".empty b")).to_have_text("Alternance"))
        page.goto(URL + "#profile")
        page.click("#logout")
        check("sign out returns to Sign in", lambda: expect(page.locator("#authBtn")).to_have_text("Sign in"))
        page.reload()
        check("signed out for good after reload", lambda: expect(page.locator("#auth")).to_be_visible())
        page.click("#tabIn")
        page.fill("#email", "amel@example.tn")
        page.fill("#password", "wrong-password")
        page.click("#authBtn")
        check("wrong password explained", lambda: expect(page.locator("#authMsg")).to_have_text("Wrong email or password."))
        page.fill("#password", "long-enough-1")
        page.click("#authBtn")
        check("sign in works", lambda: expect(page.locator("main h2")).to_have_text("Hello Amel"))
        page.screenshot(path=os.path.join(os.environ.get("SHOTS", ROOT), "public-home.png"))
        page.goto(URL + "#profile")
        page.click("#delete")
        page.fill("#delPw", "long-enough-1")
        page.click("#delBtn")
        check("account deleted, back to sign-up", lambda: expect(page.locator("#authBtn")).to_have_text("Create my account"))
        page.click("#tabIn")
        page.fill("#email", "amel@example.tn")
        page.fill("#password", "long-enough-1")
        page.click("#authBtn")
        check("deleted account cannot sign in", lambda: expect(page.locator("#authMsg")).to_have_text("Wrong email or password."))
        check("no script errors", lambda: (_ for _ in ()).throw(AssertionError(errors)) if errors else None)
        wide = b.new_page(viewport={"width": 1280, "height": 800})
        wide.goto(URL)
        wide.screenshot(path=os.path.join(os.environ.get("SHOTS", ROOT), "public-signup.png"))
        b.close()
finally:
    server.terminate()

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
