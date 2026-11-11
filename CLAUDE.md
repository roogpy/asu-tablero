# CLAUDE.md — asu-tablero

## Goal
Mobile-first daily dashboard (installable PWA for Android) of arrivals and departures at Silvio Pettirossi International Airport (IATA `ASU`, ICAO `SGAS`, Luque, Paraguay). One data snapshot per day, collected in the cloud with no PC involved.

## Architecture
```
GitHub Actions (nightly cron)  ->  collect.py  ->  data/YYYY-MM-DD.json + data/index.json  ->  git commit
GitHub Pages (HTTPS)           ->  PWA (index.html + app.js + manifest + service worker) reads data/*.json
Android phone                  ->  opens the Pages URL, "Add to Home screen"
```
- The phone NEVER calls AviationStack. Reasons: the free plan is HTTP only (an HTTPS page cannot fetch HTTP: mixed content is blocked) and the API key would be exposed in the browser.
- The API key lives only in GitHub Actions secrets as `AVIATIONSTACK_KEY`.

## Data source
- AviationStack `/v1/flights` with `arr_iata=ASU` (arrivals) and `dep_iata=ASU` (departures), `limit=100`.
- Free plan: 100 requests/month, HTTP only, personal non-commercial use. Never print the full request URL in logs (it contains the key).
- Expected volume: ~60 operations/day (~30 per direction).

## Request budget (hard rule)
- Normal run: 2 requests/day (~60/month).
- `data/budget.json` (committed) keeps per-day and per-month counters; `collect.py` refuses to call the API if today >= 3 or month >= 95.
- Tests never hit the API: they use fixtures under `tests/fixtures/`.

## Schedule
- Cron `30 2 * * *` (UTC) = 23:30 America/Asuncion (UTC-3). GitHub may delay scheduled runs; this is acceptable for a daily snapshot.
- Also allow `workflow_dispatch` for manual runs (counts against the budget).

## Data rules
- Keep the raw API response for each run in `data/raw/YYYY-MM-DD_{arr|dep}.json`.
- Deduplicate codeshares: a record whose `flight.codeshared` is not null is a marketing copy of another flight. Keep the operating flight and attach marketing numbers as a list.
- Store times in UTC; display in America/Asuncion.
- Status values: scheduled, active, landed, cancelled, incident, diverted.
- Never invent or interpolate missing values: show them as empty.

## PWA rules
- Mobile first: designed for ~360–412 px wide Android screens; works offline with the last loaded day (service worker cache).
- Plain HTML/CSS/JS, no build step, no framework. Touch targets >= 44 px. Large readable times.
- Tabs: Llegadas / Salidas / Resumen / Historial. Date picker to browse past days from `data/index.json`.

## Stack
- Python 3.12 + `requests` + `pytest` (collector, runs on GitHub Actions ubuntu-latest)
- Static PWA on GitHub Pages
- Local development on Windows (PowerShell)

## Rules
- Code, comments, file names and commit messages in English. Explanations to the user in Spanish.
- Incremental: each phase ends with its check green before moving on.
- Do not modify files outside this folder.
