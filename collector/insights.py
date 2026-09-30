"""Interview stories from people who went through a company's hiring for a similar role.

Glassdoor interview reviews (job title, outcome such as "Accepted offer", experience, difficulty, how they applied,
how the interview went, questions asked) and Reddit threads. Both block datacenter IPs, so this runs on the PC
collector (home connection) with Scrapling's StealthyFetcher.

  python collector/insights.py --env=upstash.env           # process requests queued from the app
  python collector/insights.py "Capgemini" "ML Engineer"   # one lookup, printed (test)
"""
import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import quote_plus

QUEUE, STORE = "parcours:insights:queue", "parcours:insights"
MAX_STORIES = 15


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def key(company, role):
    return norm(company).replace(" ", "-") + "|" + norm(role).replace(" ", "-")


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "-", unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()).strip("-")


def _tokens(html):
    """(class stem, text) pairs in page order, icons and scripts removed."""
    h = re.sub(r"<svg\b[\s\S]*?</svg>", "", html)
    h = re.sub(r"<(script|style)\b[\s\S]*?</\1>", "", h)
    out = []
    for m in re.finditer(r"<(\w+)([^>]*)>([^<]*)", h):
        cls = re.search(r'class="([^"]*)"', m.group(2))
        stem = re.sub(r"__[A-Za-z0-9]+$", "", cls.group(1).split()[0]) if cls and cls.group(1).split() else m.group(1)
        txt = re.sub(r"\s+", " ", m.group(3).replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"')).strip()
        if txt:
            out.append((stem, txt))
    return out


def parse_glassdoor(html, summary=None):
    """Interview stories; fills `summary` with the role-level facts at the bottom of the page when given."""
    stories, cur, section = [], None, None
    for stem, txt in _tokens(html):
        rated = re.search(r"rated the interview process at .+? with ([\d.]+) out of 5", txt)
        days = re.search(r"take an average of (\d+) days? to get hired", txt)
        stage = re.match(r"([A-Z][A-Za-z /-]{3,40}): (\d{1,3})%$", txt)
        if rated or days or stage or txt.startswith(("Common stages of the interview", "Here are the most commonly", "Related searches", "Copyright")):
            cur, section = None, None
            if summary is not None:
                if rated:
                    summary["rating"] = float(rated.group(1))
                if days:
                    summary["daysToHire"] = int(days.group(1))
                if stage:
                    summary.setdefault("stages", {})[stage.group(1)] = int(stage.group(2))
            continue
        if txt.endswith(" response") and len(txt) < 60:  # the employer's reply to the review, not the candidate's
            section = None
            continue
        if stem.startswith("heading_Heading") and txt.endswith(" Interview"):
            cur = {"title": txt[:-10].strip(), "date": "", "location": "", "outcome": "", "experience": "", "difficulty": "",
                   "application": "", "interview": "", "questions": []}
            stories.append(cur)
            section = None
        elif cur is None:
            continue
        elif stem.startswith("Timestamp_reviewDate"):
            cur["date"] = txt
        elif stem.startswith("text-with-icon_LabelContainer") and not cur["location"]:
            cur["location"] = txt
        elif stem.startswith("ExperienceRating_label"):
            low = txt.lower()
            if "offer" in low:
                cur["outcome"] = txt
            elif "experience" in low:
                cur["experience"] = txt
            elif "interview" in low:
                cur["difficulty"] = txt
        elif stem.startswith("InterviewDetail_subHeader"):
            low = txt.lower()
            section = "questions" if "question" in low else "application" if "application" in low else "interview" if "interview" in low else None
        elif section and (stem.startswith("InterviewDetail_textStyle") or stem.startswith("TruncatedText") or stem in ("li", "p", "span")):
            if txt.lower() in ("read more", "helpful", "share", "answer question") or stem == "span" and section != "questions":
                continue
            if section == "questions":
                if len(txt) > 12:
                    cur["questions"].append(txt[:300])
            elif not cur[section]:
                cur[section] = txt[:1200]
    return [s for s in stories if s["interview"] or s["application"] or s["outcome"]]


def glassdoor(session, company, role):
    page = session.fetch("https://www.glassdoor.com/Search/results.htm?keyword=" + quote_plus(company), network_idle=False, timeout=60000)
    links = re.findall(r'href="/Interview/([A-Za-z0-9-]+)-Interview-Questions-E(\d+)\.htm"', page.html_content)
    want = norm(company)
    match = next(((s, i) for s, i in links if norm(s.replace("-", " ")) == want), None) or (links[0] if links else None)
    if not match:
        return {"url": "", "stories": [], "note": "Company not found on Glassdoor"}
    cslug, cid = match
    base = f"https://www.glassdoor.com/Interview/{cslug}-Interview-Questions-E{cid}.htm"
    stories, url, summary = [], base, {}
    if role:
        rslug = slug(role)
        start = len(cslug) + 1
        url = f"https://www.glassdoor.com/Interview/{cslug}-{rslug}-Interview-Questions-EI_IE{cid}.0,{len(cslug)}_KO{start},{start + len(rslug)}.htm"
        for n in (1, 2):
            u = url if n == 1 else url.replace(".htm", f"_IP{n}.htm")
            p = session.fetch(u, network_idle=False, timeout=60000)
            if p.status != 200:
                break
            got = parse_glassdoor(p.html_content, summary)
            if not got:
                break
            stories += got
            time.sleep(2)
    if len(stories) < 3:  # few or no reviews for that exact title: company-wide, keep the closest roles first
        p = session.fetch(base, network_idle=False, timeout=60000)
        extra = parse_glassdoor(p.html_content) if p.status == 200 else []
        words = set(norm(role).split())
        extra.sort(key=lambda s: -len(words & set(norm(s["title"]).split())))
        seen = {(s["title"], s["date"]) for s in stories}
        stories += [s for s in extra if (s["title"], s["date"]) not in seen]
        if not stories:
            url = base
    return {"url": url, "stories": stories[:MAX_STORIES], "summary": summary}


def reddit(session, company, role):
    q = f'"{company}" {role} interview' if role else f'"{company}" interview'
    page = session.fetch("https://www.reddit.com/search/?q=" + quote_plus(q) + "&sort=relevance&t=all", network_idle=False, timeout=60000)
    out = []
    for a in page.css('a[data-testid="post-title"]')[:8]:
        href = a.attrib.get("href", "")
        title = re.sub(r"\s+", " ", a.get_all_text()).strip()
        if not href or not title:
            continue
        sub = re.search(r"/r/([^/]+)/", href)
        out.append({"title": title[:200], "url": page.urljoin(href), "sub": sub.group(1) if sub else ""})
    return out


def lookup(company, role):
    from scrapling.fetchers import StealthySession
    res = {"company": company, "role": role, "fetchedAt": int(time.time() * 1000)}
    with StealthySession(headless=True, solve_cloudflare=True, timeout=60000, disable_resources=True) as session:
        try:
            res["glassdoor"] = glassdoor(session, company, role)
        except Exception as e:
            res["glassdoor"] = {"url": "", "stories": [], "note": f"Glassdoor failed: {str(e)[:100]}"}
        try:
            res["reddit"] = reddit(session, company, role)
        except Exception as e:
            res["reddit"], res["redditNote"] = [], f"Reddit failed: {str(e)[:100]}"
    return res


def process_queue(store, limit=6):
    done = 0
    while done < limit:
        raw = store.cmd("RPOP", QUEUE)
        if not raw:
            break
        req = json.loads(raw)
        k = key(req["company"], req.get("role", ""))
        print(f"  stories: {req['company']} / {req.get('role', '')}")
        res = lookup(req["company"], req.get("role", ""))
        store.cmd("HSET", STORE, k, json.dumps(res, ensure_ascii=False))
        store.cmd("SREM", QUEUE + ":pending", k)
        done += 1
    return done


def auto_requests(store, state, limit=4):
    """Queue stories for companies where you have an application in progress, when missing or older than 14 days."""
    have = store.cmd("HKEYS", STORE) or []
    fresh = set()
    for k in have:
        rec = json.loads(store.cmd("HGET", STORE, k) or "{}")
        if time.time() * 1000 - rec.get("fetchedAt", 0) < 14 * 86400 * 1000:
            fresh.add(k)
    n = 0
    for a in state.get("apps", []):
        if a.get("result") != "open" or not a.get("org") or a.get("d") == "phd":
            continue
        k = key(a["org"], a.get("role", ""))
        if k in fresh or not store.cmd("SADD", QUEUE + ":pending", k):
            continue
        store.cmd("LPUSH", QUEUE, json.dumps({"company": a["org"], "role": a.get("role", "")}))
        n += 1
        if n >= limit:
            break
    return n


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        print(json.dumps(lookup(args[0], args[1] if len(args) > 1 else ""), ensure_ascii=False))
        sys.exit()
    sys.path.insert(0, os.path.dirname(__file__))
    from collect import STATE_KEY, Store, load_env
    env = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--env=")), "")
    if env:
        load_env(env)
    store = Store()
    state = store.get_json(STATE_KEY) or {}
    queued = auto_requests(store, state) if "--auto" in sys.argv else 0
    n = process_queue(store)
    print(f"stories: {queued} auto-queued, {n} fetched")
