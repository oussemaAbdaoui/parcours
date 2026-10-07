# Parcours

Your personal planner for job, master's and PhD searches: countries, platforms, applications, graphs, notes, and live listings from several job sources.

It is a static page (`index.html`) plus a few small Vercel functions in `api/`. Your data lives in your browser, and optionally syncs between devices.

## Deploy on Vercel (about 10 minutes)

1. Create a new GitHub repository and upload everything in this folder to it.
2. On vercel.com choose **Add New, Project**, import the repository, and keep the default settings (no build step).
3. Open **Settings, Environment Variables** and add at least `APP_PASSWORD` (see below).
4. **Redeploy** so the variables apply, then open your Vercel URL and sign in with that password.

To test locally first: `npx vercel dev`, with your variables in a `.env.local` file (copy `.env.example`).

## Environment variables

| Variable | Required | What it enables | Where to get it |
|---|---|---|---|
| `APP_PASSWORD` | Yes | Protects the whole app and your API quotas. Without it the API stays closed. | Choose a long password. |
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | No | Adzuna listings for France, Germany, Canada, Switzerland | developer.adzuna.com (free) |
| `FRANCE_TRAVAIL_ID`, `FRANCE_TRAVAIL_SECRET` | No | Official France Travail offers | francetravail.io: create an application and subscribe to "Offres d'emploi" |
| `JOOBLE_KEY` | No | Jooble listings, including Tunisia and Switzerland | jooble.org/api/about (free, on request) |
| `ANTHROPIC_API_KEY` | No | "Paste an email" import and "Analyse my search" | console.anthropic.com |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | No | Sync between your devices, and storage for the Gmail connection | Upstash Redis (free tier), or add it from the Vercel Marketplace |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | No | "Scan Gmail" (also needs Upstash) | Google Cloud console, see below |

Optional: `ANTHROPIC_MODEL` and `ANTHROPIC_MODEL_FAST` to change the Claude models (defaults: `claude-sonnet-5` and `claude-haiku-4-5-20251001`).

## Job sources

| Source | Key needed | Coverage | Status |
|---|---|---|---|
| Arbeitsagentur | No | Germany | Public but unofficial API, could change |
| Arbeitnow | No | Germany, Switzerland, remote, visa-sponsorship filter | Public API |
| Remotive | No | Remote | Public API, results cached 6 hours |
| RemoteOK | No | Remote | Public API |
| Adzuna | Yes | FR, DE, CA, CH | Official API |
| France Travail | Yes | France | Official API |
| Jooble | Yes | Many countries, including TN and CH | Official API |
| Indeed, LinkedIn, Glassdoor | No | Indeed/Glassdoor: FR, DE, CA, CH, remote. LinkedIn: all, including TN | Via [JobSpy](https://github.com/speedyapply/JobSpy) (MIT) in `api/boards.py`. Reads public search pages, so it is slower and can be rate-limited |

Sources without a key work as soon as you deploy. Others appear in the search form once you add their keys.

**Not fetchable:** Welcome to the Jungle, APEC and similar sites have no public search API and block automated access. Indeed, LinkedIn and Glassdoor are read through JobSpy; this goes against their terms of use, so use it for your own searches only and expect the occasional block. For those, the search page builds ready-made search links that open each site in a new tab. For academic positions the radar page links to Inria, ABG, Euraxess, DAAD, Academic Positions, jobs.ac.uk and ELLIS.

**Your feeds:** paste any RSS or Atom feed address and its latest items appear in Opportunities.

## Gmail scan

**Scan Gmail** on the Applications page reads recent emails that look job-related, sorts them with free keyword rules (English, French, German; `api/_classify.js`) into opportunities, interviews, offers, rejections and other updates, and matches them to your logged applications. You tick what to apply; nothing changes on its own. Access is read-only, and the Google token stays on the server (in Upstash), never in the browser.

Setup, once:

1. In [console.cloud.google.com](https://console.cloud.google.com) create a project, then enable the **Gmail API** (APIs and services, Library).
2. **OAuth consent screen**: choose External, fill in the app name and your email, add the scope `https://www.googleapis.com/auth/gmail.readonly`, and add your Gmail address under **Test users**.
3. **Credentials, Create credentials, OAuth client ID**: type Web application, authorised redirect URI `https://<your-app>.vercel.app/api/gmail-callback`.
4. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in Vercel (plus Upstash if not done yet), then redeploy.
5. Open Applications, Scan Gmail, Connect Gmail.

While the Google app stays in "Testing" mode, Google expires the connection after 7 days; the app then asks you to connect again. Emails already reviewed are remembered and not shown twice. Each scan reads up to 80 new emails. The rules can misread unusual wording, which is why you confirm each change.

## Collected opportunities (scheduled)

`collector/collect.py` runs on GitHub Actions every 6 hours (`.github/workflows/collect.yml`) and saves new offers to Upstash. They appear under **Opportunities, Collected for you**, with details, deadline and an **Apply** link.

Your saved searches drive the job boards (4 defaults until you save your own); academic and remote boards are filtered on your keywords and AI topics.

| Area | Platforms | How |
|---|---|---|
| Job boards | LinkedIn, Indeed | JobSpy |
| France | HelloWork, CNRS, Inria, ABG | Scrapling (ABG in stealth mode) |
| Germany | StepStone, Max Planck | Scrapling (StepStone in stealth mode) |
| Switzerland, Canada | jobs.ch, Job Bank | Scrapling |
| Tunisia | Keejob, Farojob | Scrapling |
| PhD and research | jobs.ac.uk, ELLIS, jobRxiv, Academic Positions, ScholarshipDB | Scrapling (the last two in stealth mode) |
| UK visa sponsorship | Poli (withpoli.com) | Its JSON API: the signed-in feed with a Poli account, else the visitor feed (10 offers per category and level) |
| Remote | We Work Remotely (RSS), Himalayas, Jobicy, Working Nomads (APIs) | Public feeds |

**Stealth mode.** ABG, Academic Positions, ScholarshipDB and StepStone sit behind Cloudflare or similar bot protection, so they are read with Scrapling's `StealthyFetcher`, a real browser that passes those challenges (the workflow installs it with `scrapling install`). This goes against those sites' terms; it reads a few listing pages per run and a failure only marks that source as failed.

**Not reachable from GitHub:** FindAPhD, Tanitjobs, MastersPortal, PhDPortal, DAAD, ZipRecruiter, Glassdoor and Bayt block GitHub's IP addresses outright, and Google Jobs returns nothing to servers. Euraxess disallows its search in robots.txt. Subscribe to their email alerts; Scan Gmail picks them up. No master's programme catalogue is reachable yet.

Setup: add `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` as repository secrets on GitHub. Without them the workflow runs in dry-run mode and only prints what it found. Run it by hand from the Actions tab (**Collect opportunities, Run workflow**). Items older than 45 days or past their deadline are dropped.

**Poli.** With `POLI_EMAIL` and `POLI_PASSWORD` (a Poli Pro account) as repository secrets, the collector signs in to Poli and reads, besides up to 300 offers from its personalised feed (it follows the preferences saved in the Poli account), the whole UK sponsor directory and the employees likely sponsored there (each company's list plus the account's network), on every 6-hourly run (`collector/poli.py`, `--poli` forces a refresh). The app reads them from `/api/opps?set=poli`. For the live Poli page (every job in the account's feed with all its details, each company's open jobs and sponsored employees, and the job preferences), add the same `POLI_EMAIL` and `POLI_PASSWORD` in Vercel too: `api/poli.js` signs in to Poli from the server and keeps the session in Redis.

## Updating the radar

`radar.json` holds the PhD and master's radar. Edit it in your repository (or ask Claude to refresh it) and redeploy. Deadlines in the past hide automatically.

## Notes

- I could not call the live job APIs while building this, so they are tested against mock responses only. After deploying, run one search per source. The status line under the results shows exactly which source failed and why.
- Data is stored in your browser (local storage). Use **Export backup** in the footer now and then. With Upstash configured, the newest copy wins between devices.
- Keep the password private. Anyone who has it can use your API keys.
