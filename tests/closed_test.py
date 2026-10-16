"""Cases for enrich.page_closed: how a stored offer's page shows the offer is closed, from pages seen on the real
boards (16 Oct 2026). Run: python tests/closed_test.py (also run by tests/check.py)."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "collector"))
try:
    import scrapling.fetchers  # noqa: F401
except ImportError:  # the checks run without the collector's packages: the cases need no network
    sys.modules["scrapling"] = types.ModuleType("scrapling")
    sys.modules["scrapling.fetchers"] = types.SimpleNamespace(Fetcher=None)
from enrich import page_closed  # noqa: E402


class Page:
    def __init__(self, status, url, html):
        self.status, self.url, self.html_content = status, url, html

    def css(self, _):
        return []


TANIT_OPEN = {"offre expiree", "candidatures sont closes"}  # what a listed (open) Tanitjobs offer page carries
CASES = [
    # (label, offer url, status, final url, html, closed?[, wordings an open page of the site carries])
    ("LinkedIn closed", "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4477145422", 200,
     "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4477145422", "<body><h2>ML Engineer</h2><span>No longer accepting applications</span></body>", True),
    ("LinkedIn open", "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4462919906", 200,
     "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4462919906", "<body><h2>ML Engineer</h2><p>Be among the first 25 applicants</p></body>", False),
    ("jobs.ch text in a script only", "https://www.jobs.ch/en/vacancies/detail/dc02406c-b9f2-4bd4-863f-08cc4dfa4e75/", 200,
     "https://www.jobs.ch/en/vacancies/detail/dc02406c-b9f2-4bd4-863f-08cc4dfa4e75/",
     '<body><h1>Data Scientist</h1><script>{"meta.not_found.user_document":"this document is no longer available"}</script></body>', False),
    ("jobs.ch sent to the category", "https://www.jobs.ch/en/vacancies/detail/e99aa060-1d6c-4f90-a111-222233334444/", 200,
     "https://www.jobs.ch/en/vacancies/information-technology-telecom/network/", "<body><h1>Network jobs</h1></body>", True),
    ("Tanitjobs text in CSS only", "https://www.tanitjobs.com/job/2062970/full-stack-engineer", 200,
     "https://www.tanitjobs.com/job/2062970/full-stack-engineer",
     "<body><style>/* offre cloturee : gris */ .x{color:#999}</style><h1>Full stack engineer</h1></body>", False),
    ("Tanitjobs closed", "https://www.tanitjobs.com/job/2049494/développeur-informatique/", 200,
     "https://www.tanitjobs.com/job/2049494/d%C3%A9veloppeur-informatique/", "<body><h1>Développeur</h1><div>Offre clôturée</div></body>", True),
    ("Tanitjobs open, hidden expired badge", "https://www.tanitjobs.com/job/2063430/delegue-medical/", 200,
     "https://www.tanitjobs.com/job/2063430/delegue-medical/",
     '<body><span class="tj-expiree">Offre expirée · les candidatures sont closes</span><a>Postuler</a></body>', False, TANIT_OPEN),
    ("Tanitjobs closed, footer", "https://www.tanitjobs.com/job/2049494/developpeur/", 200, "https://www.tanitjobs.com/job/2049494/developpeur/",
     "<body><span class=\"tj-expiree\">Offre expirée · les candidatures sont closes</span><b>Désolé, cette offre n'est plus disponible.</b></body>", True, TANIT_OPEN),
    ("No open page to compare: wording alone does not count", "https://www.tanitjobs.com/job/2049494/developpeur/", 200,
     "https://www.tanitjobs.com/job/2049494/developpeur/", "<body><b>Désolé, cette offre n'est plus disponible.</b></body>", False, None),
    ("Employment Hero 404", "https://jobs.employmenthero.com/FR/job/abc-123456", 404, "https://jobs.employmenthero.com/FR/job/abc-123456", "<body>Not found</body>", True),
    ("Job Bank expired", "https://www.jobbank.gc.ca/jobsearch/jobposting/50388795", 410,
     "https://www.jobbank.gc.ca/jobsearch/jobpostingexpired;jsessionid=751D9", "<body>This job posting is no longer available</body>", True),
    ("Free-Work sent to search", "https://www.free-work.com/fr/tech-it/job-mission/developpeur-ia", 200,
     "https://www.free-work.com/fr/tech-it/jobs?expire=1&query=Developpeur", "<body>Offres</body>", True),
    ("EURAXESS sent to search", "https://euraxess.ec.europa.eu/jobs/472059", 200, "https://euraxess.ec.europa.eu/jobs/search", "<body>Search</body>", True),
    ("Indeed to the employer's site", "https://proqrtherapeuticsbv.teamtailor.com/jobs/8519603-machine-learning", 200,
     "https://www.proqr.com/careers/vacancies/jobs/8519603-machine-learning", "<body><h1>ML</h1></body>", False),
    ("Accenture, same id", "https://accenture.com/dk-en/careers/jobdetails?id=R00360953_en", 200,
     "https://www.accenture.com/dk-en/careers/jobdetails?id=R00360953_en", "<body><h1>AI Engineer</h1></body>", False),
    ("Refused: no answer", "https://www.stepstone.de/stellenangebote--ml-12345678.html", 403, "https://www.stepstone.de/stellenangebote--ml-12345678.html", "<body>Access denied, no longer available</body>", False),
]

fails = 0
for label, url, status, final, html, want, *ignore in CASES:
    got = page_closed(url, Page(status, final, html), ignore=ignore[0] if ignore else ())
    ok = bool(got) == want
    fails += not ok
    print(f"{'PASS' if ok else 'FAIL'} {label}: {got or 'open'}")
print(f"{len(CASES) - fails}/{len(CASES)} closed-page cases")
sys.exit(1 if fails else 0)
