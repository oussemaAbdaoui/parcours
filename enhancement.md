# Parcours enhancements

The app is split into engines. Each one is inspected on real data, fixed, and given a test or a check so it stays fixed; this file is updated after every round. Status: ✅ done and verified · 🔧 in progress · ⏳ not started · ⛔ blocked (reason given).

## Engines

| # | Engine | What it does | Status | Check that guards it |
|---|---|---|---|---|
| 1 | Scoring | Ranks offers against the profile, drops dealbreakers | ✅ | `node tests/score.test.js` (23 cases) |
| 2 | Sources | Fetches offers from job boards | ✅ | `python tests/sources_check.py [--home]` |
| 3 | Enrichment | Full descriptions, applicants, company ratings | ✅ | coverage figures below |
| 4 | Data model | How records are stored and linked | 🔧 | [data map](https://claude.ai/artifact/LUUtbQKuCtYYH5AbEeXqVD) |
| 5 | Requirements (AI) | Claude reads what each offer asks, and the salary | ✅ | part of the scoring cases |
| 6 | Scheduling | PC tasks, GitHub cron, interview stories | ✅ | `python collector/insights.py "Company" "Role"` |
| 7 | Sync and storage | Your data across devices | ✅ | `python tests/sync_test.py` (sandboxed) |
| 8 | App pages and UX | Offers, queue, tracker, profile | 🔧 | screenshots of every page, sandboxed |
| 9 | Alerts | Notifications and weekly digest | ✅ | |
| 10 | Academia and masters | Professors, PhDs, master's, scholarships | 🔧 | `python collector/academia.py --dry-run --only=se` |
| 11 | Letters | Cover letters with AI | ✅ | sandboxed letter test |

## 1. Scoring ✅

Done (commits `bff675d`, `c5ade87`, `c754778`):
- Missing information no longer counts as half marks: an offer whose full text is unread is capped at 65 and says so.
- Seniority comes from the title and stated years only ("mission principale" was read as a lead role).
- Pre-hire and SIVP internships count as graduate jobs.
- One clearly unmet requirement (level above yours, degree below the one asked) caps the score at 70.
- "Agent" alone is not AI, "apprentissage" alone is an apprenticeship; sales, HR and marketing titles are out unless they name a technical role.
- Before an offer's text is read, it is dropped only for reasons certain from its title.
- Every required language counts (Swedish, Danish, Dutch were ignored), and an offer written in one of them asks for it.
- The UK is a target country.

Open:
- [ ] Calibrate the strong band once most offers have their text (today a third of read offers score 75+).

## 2. Sources ✅

Done (commits `5e582c6`, `c5ade87`, `8cff067`, `0b19cda`):
- The store keeps the best offers, not the newest (good offers vanished after about two days).
- New: Platsbanken (SE), Jobindex (DK), EURAXESS (EU research, R1), Duunitori (FI), Emploi.ma (MA).
- Welcome to the Jungle, the best source, reads 50 offers a run.
- Retired 7 sources that never produced a match.
- Health check for every source.

Open:
- [ ] ⛔ APEC, IrishJobs, Moovijob refuse even the stealth browser.
- [ ] ICTjob (BE) and Nationale Vacaturebank (NL) load their jobs by script: find their data calls.
- [ ] ⛔ Bundesagentur (DE): public API key withdrawn (403).
- [ ] ReKrute (MA): find its offer links.
- [ ] Belgium, Netherlands, Canada and Ireland still have no local board and no strong match.
- [ ] LinkedIn posts need a Serper key.

## 3. Enrichment ✅

Done (commits `034fd7e`, `41abe3f`, `c3dd48c`, `e6a6caf`, `dc60461`):
- The PC fills LinkedIn descriptions; the cloud run does it through the rotating proxy (800 MB a month cap).
- A refused LinkedIn page through the proxy is skipped, not the end of the run.
- Collectors never write an older, emptier copy over a richer one (the cloud run was erasing the PC's descriptions: 10 of 258 LinkedIn offers kept theirs).
- Most promising offers are opened first; the PC opens 40 pages a run.

Verified on the cloud run of 11 Oct, 04:21 UTC:
- [x] Cloud offers with their full text: 126 of 482, then 200, now 362 of 491.
- [x] LinkedIn through the proxy: 400 pages of 400, no stop (19.5 MB; 22 MB of 800 this month).
- [x] Applicant counts: 10, now 113.

Open:
- [x] "Over 150 applicants" stays a dealbreaker: those offers are hidden (your decision, 11 Oct; 93 dropped in the first run with applicant counts).
- [ ] Duunitori descriptions through the stealth details step: check on the next PC runs.

Coverage before the fixes (11 Oct): 249 of 541 offers with full text; LinkedIn 10 of 258.

## 4. Data model 🔧

Found while drawing the [data map](https://claude.ai/artifact/LUUtbQKuCtYYH5AbEeXqVD).

Done:
- [x] Poli data protected before the Pro account ends: merged, never deleted; snapshot in `parcours:poli:archive:*` and on the PC; jobs feed archived (commit `40254f7`).
- [x] Company matching (commits `d967ea9`, `6f596c9`): measured first, 13 of 412 companies split under two names, and offers reached 29 Poli sponsors. Legal forms and country words (plc, LLP, BV, AB, Maroc, Nederland, UK...) are now dropped on both sides, and company pages use the same key: KPMG Nederland, AXA and GlobalLogic now reach their sponsor. A looser prefix rule was tested and rejected: 6 of its 7 extra matches were wrong companies ("Board Intelligence" to "Board").
- [x] `parcours:applylog` (removed auto-apply) backed up to the PC (`backups/applylog-2026-10-11.json`) and deleted.

Audit on real data (11 Oct, 735 offers):
- [x] **Claude's readings stopped**: the 11:40 cloud run read 0 of 400 offers, the run before failed 29. Cause: Anthropic credits used up (the API answers "credit balance too low"; the collector only logged "HTTP 400" and tried all 400). 174 offers with full text have no reading, so they are scored with caution. Fixed: the collector stops at the first credit or key error and the offers page says so plainly (commit after `82e6ede`). **Your step: top up credits at console.anthropic.com.** Cover letters and Improve with AI need it too.
- [x] Cost: a cloud run read 400 offers for about 1.27 M input tokens ($0.19 on Haiku 5.5). About 2,500 of the ~3,200 tokens of each call are the fixed instructions and schema: now cached (billed at a tenth after the first call). The run log shows "+N from cache" to prove it on the first run after the top-up.
- [x] Sending Claude only the mission and profile parts was tried again (your request, 11 Oct), with section headings found inside flat text and requirement sentences rescued: it cut only 9% of the text and dropped 57 required skills and 11 of 361 evidence quotes (LinkedIn mixes skills into "about us" and "what we offer"). Rejected; caching saves far more with no loss.
- [x] **App scores ignored Claude's reading**: `matchOf` never passed `req` to score.js, so the app scored from raw text while the collector used the reading. 360 of 491 read offers scored differently; 15 were wrongly blocked for "Required language missing" (German only a plus) and 3 for degree field. Fixed (commit `ad60c0d`).
- [x] Applicant counts were read once: an offer seen at 141 could pass 150 unseen. Each cloud run now re-counts LinkedIn offers counted at 50 to 150 more than 2 days ago (109 today, 44 of them at 100+), counts only, so the description and Claude's reading stay; up to 120 pages (about 5 MB of proxy). Offline test: 141 re-counted "over 200" and dropped.
- Duplicates: 6 extra copies of the same job across sources (Telavox on Platsbanken and LinkedIn). Low.
- Missing basics: 60 offers with no text, 53 with no date, 11 with no company.
- Company links: 512 companies in offers; 379 have a rating, 44 are Poli sponsors, 11 have interview stories.
- Links hold: 16 of 17 applications point to a stored offer; 4 of 18 queue items point to offers that aged out (the queue keeps its own copy).
- [x] Poli export: the full raw data saved to the PC (`poli-archive/2026-10-11/full/`, JSON and CSV): 2,531 sponsors, 20,023 people (the whole network; the old collector stopped at 534), 99 jobs.
- [x] **Move to Postgres, phase 1 (Poli)**: tables `poli_companies`, `poli_people`, `poli_jobs` (merged, never deleted, empty fields never blank stored ones); export and older Redis copies imported; collector runs write Postgres. The People tab searches all 20,023 on the server (likely sponsored first, 50 at a time). Sandboxed: search "machine learning" 173, likely sponsored 19, Show more, companies 2,531, no page errors.
- [x] CI (`.github/workflows/ci.yml` + `tests/check.py`): every push runs the scoring cases and checks every script parses and every Python file compiles; deploys only when they pass, once the `VERCEL_TOKEN` secret is added (your step). A deliberately broken file was caught.
- [x] **Phase 2 (offers and companies)**: tables `companies` (one per normalised name, rating, UK sponsor link by trading or registered name), `offers` (with `company_id`), `company_seen` (hiring log) and `insights` (stories). Every collector run writes both stores; the backfill copied 691 offers, 1,087 ratings, 4,724 hiring-log rows and 20 stories. Checked identical to Redis before the switch (691 offers, no difference). The app reads offers and the hiring log from Postgres; each offer carries `companyId` and `sponsorId`.
  - Found on the way: 149 companies were stored twice because the old hiring log kept keys from an older name normaliser ("lovable labs sweden ab"); folded, and keys are normalised again on every write. Their hiring patterns had never shown in the app. Now all 494 companies in your offers have one.
  - Sponsor links: the database link and name matching agree on all 125 offers at UK sponsors (ASOS, Lovable and GlobalLogic needed the registered name).
- [x] **Phase 3** (commit `9ad8758`): collectors read and write everything collected in Postgres only (offers, ratings, hiring log, stories, Poli, and master's and academia in a new `datasets` table), and read your profile from the same rows the app saves (the Redis state mirror is gone). The API serves them from Postgres with no Redis fallback. Redis keeps only run reports, queues, sessions and counters. Every Redis copy archived on the PC first (`redis-archive-2026-10-12.json`, 7.5 MB); 509 master's, 2,385 schools and 359 professors copied.
  - Found on the way: **the PC's Python environment had no Postgres driver**, so its offers, interview stories and ratings never reached Postgres (8 offers, 5 stories, 30 ratings missing; the log said "No module named 'psycopg'"). Installed, the missing rows copied. After phase 3 it would have stopped the PC collector outright.
  - [ ] Your step: deploy (the auto mode refused a production deploy): `npx vercel@63.1.2 deploy --prod --yes`, or add the `VERCEL_TOKEN` secret so CI deploys. Then the old Redis copies are deleted (`parcours:opps:items`, `parcours:masters:items`, `parcours:academia:*` hashes, `parcours:poli:*` hashes, `parcours:companies`, `parcours:companies:history`, `parcours:insights`, `parcours:state`); until then the live app still reads master's, academia and stories from Redis.

Open:
- [ ] The `autoApply` field on one queue item and the recommendation letters in the profile are unused, but they sit in your synced data; changed only through the app, never from outside (that is how the data was once wiped).
- [ ] An offer's state lives in four places (hidden setting, queue, saved, applications) that can disagree. One state per offer id. Moved to App pages.
- [ ] Applications keep only role, company and link: the offer's text, requirements and salary are lost when it ages out. Keep a copy on the application. Moved to App pages.

## 5. Requirements (AI) ✅

- Salary is read for new offers; old readings are kept (no re-read cost).
- Only offers with their full text are read.
- Trimming the text before sending it was tested and rejected: 10% saved, requirements lost in 14 of 175 offers.

## 6. Scheduling ✅

Inspected:
- GitHub's cron is set for every 3 hours but runs 3 to 4 times a day, with gaps up to 9 hours. The PC trigger fills the gaps while the laptop is on (it started the 02:40 run, and skips when a run is recent). Accepted: what only the PC can do is the Tunisian boards.
- "Stories" was wrongly listed as broken: it fetches only what is requested, and 12 companies had stories. But their content was wrong, see below.

Done (commit `2882aa8`):
- [x] Interview stories matched the wrong company: Glassdoor took the first search result when the name did not match (the Tunisian TNT got TNT Express delivery drivers, Dev Digital an Indian DevDigital), accented names never matched (Société Générale got its insurance arm), and Reddit returned any AI interview thread. Now: the company itself or "no page", related roles only, Reddit threads that name the company. Checked on TNT, Société Générale and Capgemini.
- [x] The 12 stored records are queued to be fetched again (6 every 30 minutes).
- [x] The stories task runs with `--auto`: open applications get their stories refreshed every 14 days.

Open:
- [ ] The cloud run's schedule could move off minute 17 of the hour (GitHub drops more runs at busy times); low value while the PC trigger covers.

## 7. Sync and storage ✅

Inspected (sandboxed, every write captured and never sent; commit `930093d`):
- [x] A fresh device adopts the server's data and sends no deletion (12 of 12 applications, 0 writes).
- [x] When the server comes back empty and the device still has data, the device sends its copy back (12 adds, 0 deletions).
- [x] The Redis mirror the collectors read matches Neon exactly (every list, the profile, the last update).
- [x] Daily backup of your synced data on the PC, 30 days kept (`parcours-collector/backups/state-YYYY-MM-DD.json`). Before this there was no copy outside the devices.

Open:
- [x] The server's mass-deletion refusal is proven by `tests/state_guard.test.js` (round 4).

## 8. App pages and UX 🔧

UX audit (11 Oct): Home, Discover, Track, Profile, Companies, Sponsors, Academia, Master's and Notes screenshotted at desktop (1366 px) and phone (390 px) width with your real data, writes captured. No page errors, no horizontal scrolling.

Fixed (commit `a37f99f`, checked on new screenshots):
- [x] Offers were not listed in the order of their score (79 above 81): a hidden confidence rank decided. Now the score shown, confidence only between equal scores.
- [x] Phone: the last offer button (Hide) was cut off. The row wraps.
- [x] "failed: LinkedIn posts, LinkedIn details" showed on every run for normal states (no Serper key, rate limit). Only real errors show now.
- [x] Home said "29 close soon", counting off-field PhDs (fusion engineering, earthquakes). Now the strong matches only: 11.
- [x] Home showed the same five offers twice (New strong matches, Best matches right now). The second list continues after the first.
- [x] "Where you applied" had 12 empty country rows out of 15. Only countries with applications.
- [x] Home's "Apply queue · 18" counted sent and skipped offers; the header said 3. Both count what is left to do.
- [x] The board did not show duplicates: Université Gustave Eiffel, Rosenberger Tunisia and TNT are each logged twice (17 applications, 14 real). Marked "Logged twice".

- [x] Applications keep the offer (commit `f577c7e`): logging from an offer or from the apply queue saves its text, requirements and salary on the application, shown in the dialog under "The offer as you applied". Editing an application used to drop every field the form does not show; it keeps them now. Sandboxed test on a real offer: logged, saved with 3117 characters of text and its requirements, edited, still there.

Open:
- [ ] Delete the 3 duplicate applications (your call, from the board).
- [ ] ⛔ All 17 applications are stuck at "applied". "Scan Gmail" exists but cannot run: the server has no Google sign-in (`GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` missing). Your step: create an OAuth client in Google Cloud Console (Web application, redirect `https://parcours-swart.vercel.app/api/gmail-callback`), add both values in Vercel, then Connect Gmail in the app.
- [ ] An offer's state lives in four places (hidden setting, queue, saved, applications) that could disagree. Measured: no conflict in your data today. Low priority.
- [x] Offer rows had six buttons plus Why and Offer details. Now Apply, Save, Queue and a "⋯" menu (Log as applied, Interview stories, Hide); fits one row on a phone. Sandboxed: menu opens, Log still opens its dialog, menu closes after.
- [x] The daily goal showed up to three times (top-bar pill, goal bar, Home's goal card). The top-bar pill is gone; checked on phone screenshots of Home and Discover.
- [x] Desktop filters took three rows of twelve controls. Now search, sort, match, kind and country on one row; topic, source, experience, date and the four checkboxes behind "Filters" (as on phones). Screenshots closed and open.
- [x] "Lead, AI Engineering" at Bain scored 77 as entry level. Cause: the text says "mentoring more junior team members", and "junior" anywhere made the offer entry level, overriding the "Lead" title. Now juniors you would mentor, coach or manage do not count, and an entry-level guess from words never overrides a senior or lead title. 9 of 735 offers changed, each checked: Bain, ClearRoute, DoubleVerify "Sr" are now too senior (40); IKEA, Booking.com, La Fosse, Metsä, Harmattan, Storyteller lose 6 to 9 points (all "mentor junior engineers"). 2 new test cases, 23/23 pass.

## 9. Alerts ✅

Done:
- [x] Offers whose description arrives in a later run were never announced: an alert fired only for offers found in the same run, and LinkedIn offers arrive capped at 65 until their text is read. Now an offer from the last 7 days is announced the first time it reaches your threshold (85), and announced offers are remembered (`parcours:push:alerted`) so nothing repeats; the first run only records today's strong offers. Tested over three simulated runs.
- [x] The weekly digest counted deadlines from score 60; it counts strong matches (75+) like the app.

## 10. Academia and masters 🔧

Inspected: 539 master's programmes and scholarships, 299 professors.

Done:
- [x] 37 duplicate master's programmes: Mon Master lists a programme once per variant (work-study, another session). One entry now, marked work-study if any variant is; a fresh fetch gives 196 programmes and no duplicate (commit `2c75e42`).
- [x] Professors covered 5 fixed countries while you target 15: they now follow your profile (the UK included). Dry run for Sweden: relevant explainable-AI professors with emails; about 2 minutes a country, within the weekly job's limit (commit `e3b49a4`).
- Expired deadlines (138 of 539) are hidden by the app's default filter: fine as is.

- [x] Master's sources follow the profile's countries (Italy kept on purpose: your choice; EU-wide always). National scholarships added for Switzerland (ETH ESOP: full costs, window 1-30 Nov 2026), Ireland (GOI-IES: EUR 10,000 + fee waiver), Netherlands (NL Scholarship: EUR 5,000) and Belgium (Master Mind: EUR 10,225 + fee waiver), each checked on its official page. Left out after checking: Chevening (two years of work needed) and the Swedish Institute (Tunisia off recent lists, 3,000 work hours).

Open:
- [ ] Master's cover France, Germany, Italy and Erasmus Mundus only: no source yet for the Nordics, the Netherlands, Belgium, the UK or Canada.
- [ ] Some institutions are a sub-unit ("Formation Continue UNIL-EPFL" for an EPFL professor): prefer the parent institution.

## 11. Letters ✅

- [x] Improve with AI (commit `ad60c0d`): gets a brief (what the offer asks from Claude's reading, the skills the CV matches, those it lacks, the strongest CV evidence) and rules for a strong letter (lead with real matches backed by CV facts, no stock openings, never claim a missing skill). Runs on Sonnet 5.5 (about 2 cents a letter) instead of Haiku. Prompt checked in the sandbox; a real letter waits for the credit top-up.

Inspected: "Improve with AI" run on a real queued offer (IFP Energies nouvelles PhD), sandboxed; only the AI call went out.
- Good: the offer's specifics (Méso-NH simulations, diffusion and transformer approaches) tied to real CV facts; every name (Sayadi, Noël, Enchéry) is in the offer; no placeholder; nothing invented.
- [x] The date line kept the draft's old date (10 October on the 11th): Claude is now given today's date. Checked: "11 October 2026".
- [x] The 220-word limit now counts the body only; the letter's body is about 240 words because the PhD draft is long. Accepted.

## Weak-spot rounds (12 Oct)

Five rounds: each one audits every engine on the real data in Postgres (read-only), takes the weakest spots, fixes them at the root and adds a check.

### Round 1
Audit: 879 offers; UK 127 offers but 6 strong; 21 Academic Positions offers and 10 ETH/academics.de offers never had their text; about 110 offers in store had been dropped before and found again.
- [x] **Scoring, UK visa**: a UK job needs an employer licensed for the Skilled Worker visa, and only Poli's 2,500 sponsors were known. The official Home Office register (about 128,000 names, gov.uk CSV) is now loaded weekly into `uk_sponsors` (`collector/uk_register.py`) and every company marked `uk_sponsor`. Matching: same name, same name without spaces (ElevenLabs), registered name without generic endings (Wayve Technologies, PA Consulting Services), trading names ("Roofoods t/a Deliveroo"), or listed by Poli (Meta, WTW). A looser prefix rule was measured and rejected ("Meta" matched "Meta Data Systems", "Prima" fourteen companies). UK offers at a licensed sponsor: 39 known before, 77 of 127 now. Scoring: on the register, a visa boost; not on it, capped at 70 ("employer not on the UK visa sponsor register"), not dropped since a name can be registered under another; agencies hiring for "our client" are left alone. Real effect: JPMorgan, Southampton, Citi, ElevenLabs up 1-2; PATH, Pyramid Consulting, MBZUAI down to 70. 3 new test cases (26).
- [x] **Enrichment, Academic Positions**: its pages hold a 180-character summary in their structured data, which was taken as the whole text; the page body (`.ck-content`) is read now (3,953 characters on the test page). Offers still short after an attempt are tried once more whenever the page reader improves (`READER_V`), so the 21 stored ones get read.
- [x] **Enrichment, order**: about 70 pages are opened per run for about 400 new offers, in listing order. Now the offers whose listing promises most are opened first (the score before the "unread" cap: up to 84 today), and the store cap ranks unread offers by that too.
- [x] **Sources, re-work**: offers read and dropped as dealbreakers (236 and 434 in the last two cloud runs) were found again as new, and opened, proxied and read by Claude again. They are remembered with a fingerprint of the profile that judged them (`offers_dropped`) and skipped for 30 days unless the profile changes.

### Round 2
Audit: professors for 11 of your 16 countries were missing; master's only for France, Germany, Italy and Erasmus Mundus; some professors' first email was at a university they left.
- [x] **Academia, OpenAlex allowance**: OpenAlex now allows 1,000 requests a day without a key and a country takes 130-200; the weekly run stopped at the sixth country with HTTP 429, so NL, LU, SE, DK, TN, NO, FI, MA, IE and the UK never had professors. Now daily, stalest countries first, stopping cleanly before the allowance runs out and keeping what is stored; a dropped connection is retried. Optional: a free OpenAlex key as the `OPENALEX_API_KEY` secret makes it faster.
- [x] **Academia, emails**: ORCID often lists an address at a former university (a Chalmers professor with an @fau.de one). Addresses at the current school's domain now come first, the homepage and arXiv are tried when ORCID has none there, and the app marks the others "not at their current school, maybe an old address".
- [x] **Master's, Finland**: Studyinfo (opintopolku.fi) through its public API: 30 English-taught university master's in your fields (Aalto, Helsinki, Tampere, Oulu, Jyväskylä...), with the application window (mostly 7 Dec 2026 to 5-21 Jan 2027), the tuition fee and the scholarship range (up to 100% at most). Universities of applied sciences left out: their master's need two years of work.

### Round 3
Audit: 102 of 104 company-board readings, all 10 Jobindex and all 5 We Work Remotely found no requirement; 5 jobs stored twice.
- [x] **Enrichment and requirements, listing excerpts**: about twenty sources keep the listing's excerpt cut at 600 characters and count on the details step to open the page, but that step only opened offers under 400 characters. So a 400-600 character excerpt passed for the whole offer: scored as read (Free-Work "Développeur Python IA" at 87 on 600 characters), read by Claude on a company blurb, and its page never opened. Now an excerpt is a teaser until its page is tried (190 offers: company boards 115, HN 22, Free-Work 15, ETH 7...; Jobindex cards always), opened in order of promise, scored as unread (capped at 65), not read by Claude; when the page brings the full text, the excerpt's reading is dropped and Claude reads the whole offer. New test case (27).
- [x] **Sources, duplicates**: copies of one job were compared by the raw company name ("Odido" and "Odido Nederland", "Telavox AB" and "Telavox", "ALTEN" and "ALTEN MAROC"), so 5 jobs were stored twice. Now the normalised company key everyone else uses; the stored copies fold into the one with the longer text on the next run.
- Checked, fine: proxy pacing (5.4 MB in the last run, 161 of 800 MB this month); alerts fire (1-2 a run); Poli's failing step was a timeout before the retry was pushed.

### Round 4
- [x] **App, UK offers**: each UK offer row says "UK visa sponsor" (on the Home Office register) or "no UK sponsor licence found" (with a hint that the employer may be registered under another name), instead of only a line in the score breakdown.
- [x] **Sync, wipe guards proven**: the server's refusals were checked by reading the code only. `tests/state_guard.test.js` runs the real `api/state.js` against an in-memory stand-in for Postgres (nothing real touched): deleting 12 of 20 items at once is refused and nothing is written, 3 of 20 and 10 of 100 go through, blanking a filled profile is refused, an old client sending an empty whole state deletes nothing, older edits never overwrite newer ones. Part of CI now (6/6).

## Log

- 11 Oct: scoring, sources, requirements and part of enrichment done; Poli protected; UK added; this file started.
- 11 Oct: letters (date fixed); enrichment verified on the cloud run: 362 of 491 offers with full text, 113 with applicants.
- 11 Oct: academia and masters: duplicates merged, professors in all your countries.
- 11 Oct: applications keep the offer; alerts reach offers read later.
- 11 Oct: UX audit, first round: 8 fixes on Discover, Home and Track; 8 items open.
- 11 Oct: sync round: both wipe scenarios pass in the sandbox, mirror matches Neon, daily PC backup added.
- 11 Oct: scheduling round: cron gaps covered by the PC; interview stories fixed (wrong companies).
- 11 Oct: data model round: company matching, apply log cleanup. PC run with the new sources: Welcome to the Jungle 26, Duunitori 22, Emploi.ma 14; 63 of 70 PC offers with full text.
- 11 Oct: Bain "Lead" scored as entry level fixed at the root (mentoring juniors); data map updated with 11 Oct counts, PC backups and alert markers; Poli jobs confirmed stored (99, merged).
- 11 Oct: Claude credits ran out (0 of 400 offers read): the collector now stops and says so; reading calls cached; app scores now use Claude's reading (18 offers wrongly blocked); better Improve with AI; Poli full export (5,000 network people, raw fields) saved to the PC, bigger run going.
