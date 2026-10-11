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
| 6 | Scheduling | PC tasks and GitHub cron | ⏳ | |
| 7 | Sync and storage | Your data across devices | ⏳ | |
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

## 6. Scheduling ⏳

Known:
- [ ] GitHub's cron skips runs (the PC trigger covers the gaps; verify it still does).
- [ ] "Stories" fetched nothing in about 150 runs: fix or turn off.

## 7. Sync and storage ⏳

## 8. App pages and UX ⏳

Known:
- [ ] All 17 applications are stuck at "applied": match Gmail replies to applications, and remind to follow up.

UX audit: to do (pages walked through with your data in a sandbox, writes intercepted).

## 9. Alerts ⏳

## 10. Academia and masters ⏳

## 11. Letters ⏳

## Log

- 11 Oct: scoring, sources, requirements and part of enrichment done; Poli protected; UK added; this file started.
- 11 Oct: data model round: company matching, apply log cleanup. PC run with the new sources: Welcome to the Jungle 26, Duunitori 22, Emploi.ma 14; 63 of 70 PC offers with full text.
