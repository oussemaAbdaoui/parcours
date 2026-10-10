"""Fills company application forms (Greenhouse, Lever, Ashby, Workable) on your PC, for the offers you marked with
"Fill on my PC" in the apply queue. Each form opens in a visible browser, filled with your answers (Profile, Applying),
your CV file and the letter you reviewed; fields it could not fill are outlined in red. YOU check it and press Submit:
this script never submits anything, and it only reads your data (it never writes to your synced state).

  python collector/fill_forms.py --env=PATH                    # every offer marked "Fill on my PC"
  python collector/fill_forms.py --env=PATH --url=URL --test   # one form, headless, screenshot, for testing
The env file needs UPSTASH_REDIS_REST_URL/TOKEN (your state), PARCOURS_URL and PARCOURS_PW (your documents).
"""
import base64
import json
import os
import re
import sys
import tempfile

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect  # noqa: E402  (Store, load_env)

ATS = [(re.compile(r"(^|\.)greenhouse\.io$"), "Greenhouse"), (re.compile(r"(^|\.)lever\.co$"), "Lever"),
       (re.compile(r"(^|\.)ashbyhq\.com$"), "Ashby"), (re.compile(r"(^|\.)workable\.com$"), "Workable")]
HERE = os.path.dirname(os.path.abspath(__file__))


def ats_of(url):
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    return next((name for re_, name in ATS if re_.search(host)), None)


def apply_url(url, ats):
    base = url.split("?")[0].rstrip("/")
    return {"Lever": base + "/apply", "Ashby": base + "/application", "Workable": base + "/apply/"}.get(ats, url)


def fetch_doc(doc_id):
    """A document from your documents store (api/state.js ?doc=), saved to a temp file under its own name."""
    r = requests.get(os.environ["PARCOURS_URL"].rstrip("/") + "/api/state?doc=" + doc_id,
                     headers={"x-app-password": os.environ["PARCOURS_PW"]}, timeout=60)
    if r.status_code != 200:
        return None
    d = r.json()
    path = os.path.join(tempfile.gettempdir(), "parcours-" + re.sub(r"[^\w. -]", "_", d["name"]))
    with open(path, "wb") as f:
        f.write(base64.b64decode(d["data"]))
    return path


def answers(profile):
    a = profile.get("apply") or {}
    full = (profile.get("name") or "").strip()
    first, _, last = full.partition(" ")
    return {"first": first, "last": last, "full": full, "email": a.get("email", ""), "phone": a.get("phone", ""),
            "linkedin": a.get("linkedin", ""), "github": a.get("github", ""), "city": a.get("city", ""),
            "salary": a.get("salary", ""), "start": a.get("start", "")}


# Field label -> answer key. Checked in order; the first matching empty field gets the value.
LABELS = [
    (r"first\s*name|pr[ée]nom|given name", "first"), (r"last\s*name|surname|family name|nom de famille", "last"),
    (r"^\s*(full\s*)?name\s*\*?$|^nom\s*\*?$|your name", "full"), (r"e-?mail", "email"), (r"phone|mobile|t[ée]l[ée]phone", "phone"),
    (r"linkedin", "linkedin"), (r"github|portfolio|website|personal site|site web", "github"),
    (r"current location|^location|city|ville|where are you based", "city"),
    (r"salary|compensation|r[ée]mun[ée]ration|pr[ée]tentions", "salary"), (r"start date|availability|notice period|disponibilit", "start"),
]
# Lever's fixed field names (its labels are not always tied to the inputs).
LEVER = {"name": "full", "email": "email", "phone": "phone", "location": "city", "urls[LinkedIn]": "linkedin",
         "urls[GitHub]": "github", "urls[Portfolio]": "github", "urls[Other]": "github"}


def attr(el, name):
    try:
        return el.get_attribute(name, timeout=3000) or ""
    except Exception:  # the field left the page
        return ""


def label_of(el):
    try:
        return _label(el)
    except Exception:  # the field changed or left the page while it was read
        return ""


def _label(el):
    return el.evaluate("""e => {
      const byFor = e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]');
      const t = (byFor && byFor.innerText) || (e.closest('label') && e.closest('label').innerText)
        || e.getAttribute('aria-label') || e.getAttribute('placeholder') || e.name || '';
      return t.replace(/\\s+/g, ' ').trim(); }""", timeout=3000)


def fill(page, ans, letter, cv_path):
    done, letter_done = [], False
    # Forms built by script (Ashby, Greenhouse) appear after the page: wait for an email field or an upload.
    try:
        page.wait_for_selector("input[type=email], input[name*=email i], input[id*=email i], input[type=file]", state="attached", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(2000)
    for el in page.locator("input[name], textarea[name]").all():
        name = attr(el, "name")
        try:
            if name in LEVER and ans.get(LEVER[name]) and el.is_visible() and not el.input_value(timeout=3000):
                el.fill(ans[LEVER[name]], timeout=5000); done.append(name)
        except Exception:  # the field left the page
            continue
    for el in page.locator("input:not([type=hidden]):not([type=file]):not([type=checkbox]):not([type=radio]), textarea").all():
        try:
            if not el.is_visible() or not el.is_editable(timeout=3000) or el.input_value(timeout=3000):
                continue
            lab = label_of(el).lower()
            tag = el.evaluate("e => e.tagName")
            if tag == "TEXTAREA" and letter and not letter_done and re.search(r"cover|letter|lettre|motivation|additional|comments|anything else|message", lab):
                el.fill(letter); letter_done = True; done.append("cover letter"); continue
            for pat, key in LABELS:
                if re.search(pat, lab) and ans.get(key):
                    el.fill(ans[key]); done.append(key); break
        except Exception:
            continue
    files = page.locator("input[type=file]").all()
    for el in files:
        try:
            # Upload fields rarely have a label of their own: the text of the block around them says what they take.
            around = el.evaluate("""e => { let n = e; for (let i = 0; i < 4 && n; i++) { n = n.parentElement;
              if (n && n.innerText && n.innerText.trim().length > 3) return n.innerText.slice(0, 120); } return ''; }""", timeout=3000)
        except Exception:
            around = ""
        lab = (label_of(el) + " " + attr(el, "id") + " " + attr(el, "name") + " " + around).lower()
        cover = bool(re.search(r"cover|lettre|motivation", lab))
        try:
            if cv_path and not cover and re.search(r"resume|r[ée]sum[ée]|\bcv\b|curriculum", lab):
                el.set_input_files(cv_path); done.append("CV file")
            elif letter and not letter_done and cover:
                path = os.path.join(tempfile.gettempdir(), "parcours-cover-letter.txt")
                open(path, "w", encoding="utf8").write(letter)
                el.set_input_files(path); letter_done = True; done.append("cover letter file")
        except Exception:
            continue
    if cv_path and "CV file" not in done and len(files) == 1:  # one upload on the page: it is the resume
        try:
            files[0].set_input_files(cv_path); done.append("CV file")
        except Exception:
            pass
    # Required fields still empty: outlined in red so you see what is left.
    left = page.evaluate("""() => { const out = [];
      for (const e of document.querySelectorAll('input, textarea, select')) {
        const req = e.required || e.getAttribute('aria-required') === 'true';
        const empty = e.type === 'file' ? !e.files.length : (e.type === 'checkbox' || e.type === 'radio') ? false : !e.value;
        if (req && empty && e.type !== 'hidden') { e.style.outline = '3px solid #e63946';
          const l = (e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]')) || e.closest('label');
          out.push(((l && l.innerText) || e.name || e.id || e.type).replace(/\\s+/g, ' ').trim().slice(0, 60)); } }
      return out; }""")
    return done, left, letter_done


def main():
    args = dict(a.split("=", 1) if "=" in a else (a, True) for a in sys.argv[1:])
    collect.load_env(args.get("--env") or os.path.join(os.path.expanduser("~"), "parcours-collector", "upstash.env"))
    test = bool(args.get("--test"))
    if test:
        # Tests type made-up details only, so nothing personal ever reaches a real form.
        state, ans = {}, {"first": "Test", "last": "Candidate", "full": "Test Candidate", "email": "test.candidate@example.com",
                          "phone": "+33 6 00 00 00 00", "linkedin": "https://www.linkedin.com/in/test-candidate", "github": "https://github.com/test-candidate",
                          "city": "Paris, France", "salary": "", "start": ""}
        cv_path = os.path.join(tempfile.gettempdir(), "parcours-test-cv.pdf")
        open(cv_path, "wb").write(b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
                                  b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
    else:
        state = collect.Store().get_json(collect.STATE_KEY) or {}
        profile = state.get("profile") or {}
        ans = answers(profile)
        cv_path = fetch_doc("cv") if profile.get("cvDoc") else None
    if args.get("--url"):
        targets = [{"title": "test", "url": args["--url"], "letter": args.get("--letter", "Test letter, not sent.")}]
    else:
        targets = [q for q in state.get("queue") or [] if q.get("status") == "todo" and q.get("fillAt") and ats_of(q.get("url"))]
    if not targets:
        print('Nothing to fill: press "Fill on my PC" on a company-form offer in the apply queue first.')
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(os.path.join(os.path.expanduser("~"), "parcours-collector", "fill-browser"), headless=test, viewport={"width": 1280, "height": 900})
        for q in targets:
            ats = ats_of(q["url"])
            page = ctx.new_page()
            page.goto(apply_url(q["url"], ats), wait_until="domcontentloaded", timeout=60000)
            done, left, _ = fill(page, ans, q.get("letter") or "", cv_path)
            print(f"\n{q.get('title', '')[:70]} ({ats})\n  filled: {', '.join(done) or 'nothing'}\n  still to fill: {', '.join(left) or 'nothing'}")
            if test:
                shot = args.get("--shot") or os.path.join(tempfile.gettempdir(), "parcours-fill.png")
                page.screenshot(path=shot, full_page=True)
                print("  screenshot:", shot)
        if not test:
            print("\nCheck each form, finish what is outlined in red, and press Submit yourself. Then press Sent in the apply queue.")
            print("Close the browser window when you are done.")
            ctx.pages[0].wait_for_event("close", timeout=0)
        ctx.close()


if __name__ == "__main__":
    main()
