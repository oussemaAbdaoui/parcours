# Parcours enhancements

The app is split into engines. Each one is inspected on real data, fixed, and given a test or a check so it stays fixed; this file is updated after every round. Status: ✅ done and verified · 🔧 in progress · ⏳ not started · ⛔ blocked (reason given).

## Engines

| # | Engine | What it does | Status | Check that guards it |
|---|---|---|---|---|
| 1 | Scoring | Ranks offers against the profile, drops dealbreakers | ✅ | `node tests/score.test.js` (21 cases) |
| 2 | Sources | Fetches offers from job boards | ✅ | `python tests/sources_check.py [--home]` |
| 3 | Enrichment | Full descriptions, applicants, company ratings | 🔧 | coverage table below |
| 4 | Data model | How records are stored and linked | ✅ | [data map](https://claude.ai/artifact/LUUtbQKuCtYYH5AbEeXqVD) |
| 5 | Requirements (AI) | Claude reads what each offer asks, and the salary | ✅ | part of the scoring cases |
| 6 | Scheduling | PC tasks, GitHub cron, interview stories | ✅ | `python collector/insights.py "Company" "Role"` |
| 7 | Sync and storage | Your data across devices | ✅ | `python tests/sync_test.py` (sandboxed) |
| 8 | App pages and UX | Offers, queue, tracker, profile | ⏳ | |
| 9 | Alerts | Notifications and weekly digest | ⏳ | |
| 10 | Academia and masters | Professors, PhDs, master's, scholarships | ⏳ | |
| 11 | Letters | Cover letters with AI | ⏳ | |

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

## 3. Enrichment 🔧

Done (commits `034fd7e`, `41abe3f`, `c3dd48c`, `e6a6caf`, `dc60461`):
- The PC fills LinkedIn descriptions; the cloud run does it through the rotating proxy (800 MB a month cap).
- A refused LinkedIn page through the proxy is skipped, not the end of the run.
- Collectors never write an older, emptier copy over a richer one (the cloud run was erasing the PC's descriptions: 10 of 258 LinkedIn offers kept theirs).
- Most promising offers are opened first; the PC opens 40 pages a run.

Open:
- [ ] Verify on the next runs: LinkedIn offers with a description should climb from 10.
- [ ] Applicant counts: only read when a LinkedIn page is opened; check they stick.
- [ ] Duunitori descriptions through the stealth details step.

Coverage (11 Oct, before the fixes): 249 of 541 offers with full text; LinkedIn 10 of 258.

## 4. Data model 🔧

Found while drawing the [data map](https://claude.ai/artifact/LUUtbQKuCtYYH5AbEeXqVD).

Done:
- [x] Poli data protected before the Pro account ends: merged, never deleted; snapshot in `parcours:poli:archive:*` and on the PC; jobs feed archived (commit `40254f7`).
- [x] Company matching (commits `d967ea9`, `6f596c9`): measured first, 13 of 412 companies split under two names, and offers reached 29 Poli sponsors. Legal forms and country words (plc, LLP, BV, AB, Maroc, Nederland, UK...) are now dropped on both sides, and company pages use the same key: KPMG Nederland, AXA and GlobalLogic now reach their sponsor. A looser prefix rule was tested and rejected: 6 of its 7 extra matches were wrong companies ("Board Intelligence" to "Board").
- [x] `parcours:applylog` (removed auto-apply) backed up to the PC (`backups/applylog-2026-10-11.json`) and deleted.

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
- [ ] The server's mass-deletion refusal is checked by reading the code only; a test against a throwaway database would prove it.

## 8. App pages and UX ⏳

Known:
- [ ] All 17 applications are stuck at "applied": match Gmail replies to applications, and remind to follow up.

UX audit: to do (pages walked through with your data in a sandbox, writes intercepted).

## 9. Alerts ⏳

## 10. Academia and masters ⏳

## 11. Letters ⏳

## Log

- 11 Oct: scoring, sources, requirements and part of enrichment done; Poli protected; UK added; this file started.
- 11 Oct: sync round: both wipe scenarios pass in the sandbox, mirror matches Neon, daily PC backup added.
- 11 Oct: scheduling round: cron gaps covered by the PC; interview stories fixed (wrong companies).
- 11 Oct: data model round: company matching, apply log cleanup. PC run with the new sources: Welcome to the Jungle 26, Duunitori 22, Emploi.ma 14; 63 of 70 PC offers with full text.
