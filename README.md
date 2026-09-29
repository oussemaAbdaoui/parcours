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
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | No | "Scan Gmail" (also needs `ANTHROPIC_API_KEY` and Upstash) | Google Cloud console, see below |

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

Sources without a key work as soon as you deploy. Others appear in the search form once you add their keys.

**Not fetchable:** LinkedIn, Indeed, Welcome to the Jungle, APEC, Glassdoor and similar sites have no public search API, and scraping them breaks their terms and gets blocked. For those, the search page builds ready-made search links that open each site in a new tab. For academic positions the radar page links to Inria, ABG, Euraxess, DAAD, Academic Positions, jobs.ac.uk and ELLIS.

**Your feeds:** paste any RSS or Atom feed address and its latest items appear in Opportunities.

## Gmail scan

**Scan Gmail** on the Applications page reads recent emails that look job-related, has Claude sort them into opportunities, interviews, offers, rejections and other updates, and matches them to your logged applications. You tick what to apply; nothing changes on its own. Access is read-only, and the Google token stays on the server (in Upstash), never in the browser.

Setup, once:

1. In [console.cloud.google.com](https://console.cloud.google.com) create a project, then enable the **Gmail API** (APIs and services, Library).
2. **OAuth consent screen**: choose External, fill in the app name and your email, add the scope `https://www.googleapis.com/auth/gmail.readonly`, and add your Gmail address under **Test users**.
3. **Credentials, Create credentials, OAuth client ID**: type Web application, authorised redirect URI `https://<your-app>.vercel.app/api/gmail-callback`.
4. Add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in Vercel (plus `ANTHROPIC_API_KEY` and Upstash if not done yet), then redeploy.
5. Open Applications, Scan Gmail, Connect Gmail.

While the Google app stays in "Testing" mode, Google expires the connection after 7 days; the app then asks you to connect again. Emails already reviewed are remembered and not sent to Claude twice. Each scan reads up to 40 new emails.

## Updating the radar

`radar.json` holds the PhD and master's radar. Edit it in your repository (or ask Claude to refresh it) and redeploy. Deadlines in the past hide automatically.

## Notes

- I could not call the live job APIs while building this, so they are tested against mock responses only. After deploying, run one search per source. The status line under the results shows exactly which source failed and why.
- Data is stored in your browser (local storage). Use **Export backup** in the footer now and then. With Upstash configured, the newest copy wins between devices.
- Keep the password private. Anyone who has it can use your API keys.
