# Tablero ASU

Daily dashboard of arrivals and departures at Silvio Pettirossi International
Airport (`ASU` / `SGAS`, Luque, Paraguay), installable on Android as a PWA.

One snapshot per day is collected in the cloud by GitHub Actions and committed
to this repository; GitHub Pages serves a static page that reads those JSON
files. No server, no build step, and the phone never calls the flight API.

```
GitHub Actions (23:30 Paraguay)  ->  collect.py  ->  data/YYYY-MM-DD.json + data/index.json  ->  git commit
GitHub Pages (HTTPS)             ->  index.html + app.js + sw.js  ->  reads data/*.json
Android                          ->  opens the Pages URL, "Add to Home screen"
```

## Layout

| Path | What it is |
|---|---|
| `asu.py` | Pure data helpers: normalization, codeshare dedup, summaries, index, budget |
| `collect.py` | Daily collector (2 API requests), writes `data/` |
| `probe.py` | Phase 0 probe: 2 requests, raw dump plus a coverage report |
| `tests/` | pytest suite over `tests/fixtures/`, never calls the API |
| `index.html`, `styles.css`, `app.js` | The PWA |
| `sw.js`, `manifest.webmanifest`, `icons/` | Installable app shell, offline cache |
| `sample/` | One sample day built from the fixtures, used only when `data/` is empty |
| `tools/` | `make_icons.py` (PNG icons), `make_sample.py` (sample day) |
| `.github/workflows/` | `collect.yml` (nightly), `tests.yml` (push / PR) |

## Local setup (Windows, PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Put the API key in a `.env` file at the project root (it is gitignored):

```
AVIATIONSTACK_KEY=your-key-here
```

Run the tests (no API calls, no key needed):

```powershell
python -m pytest
```

Preview the app locally — a plain file:// page cannot fetch the JSON, so serve
the folder over HTTP:

```powershell
python -m http.server 8123
```

Then open <http://localhost:8123>. With no collected day yet, the app loads
`sample/` and shows a "DATOS DE MUESTRA" badge.

## Collecting data

```powershell
python collect.py              # 2 requests: today's snapshot + index
python collect.py --from-raw   # rebuild a day from data/raw, 0 requests
python collect.py --index-only # rebuild data/index.json, 0 requests
python collect.py --date 2026-11-10
python collect.py --from-raw --date 2026-11-10 --raw-date 2026-11-11
```

The last line rebuilds a different day from a response that was saved under
another date: the API window reaches back about a day and a half, so the day
before a snapshot can be rebuilt from it without spending a request.

`probe.py` (phase 0) answers whether one request per direction covers a whole
day at ASU:

```powershell
python probe.py                # 2 requests
```

### Request budget

The free AviationStack plan allows 100 requests per month. `data/budget.json`
tracks per-day and per-month counters and `collect.py` refuses to call the API
past **3 requests in a day** or **95 in a month**. A failed request still
consumes quota, so it is counted too. Normal use is 2 requests per day (~60 a
month), leaving room for manual runs.

The key is only ever read from the `AVIATIONSTACK_KEY` environment variable or
from `.env`. It is never logged, and neither is the request URL.

## Deploying (phase 3)

1. Create a **public** repository on GitHub and push this folder. Pages for a
   free personal account needs a public repository; the flight data is public
   information and the key stays in the repository secrets.
2. *Settings → Secrets and variables → Actions → New repository secret*:
   name `AVIATIONSTACK_KEY`, value your key.
3. *Settings → Pages*: source **Deploy from a branch**, branch `main`, folder
   `/ (root)`. The `.nojekyll` file keeps Pages from running Jekyll.
4. *Actions*: enable workflows, then run **Daily ASU snapshot** once by hand
   (`workflow_dispatch`) to check the whole chain. That run spends 2 requests.

The workflow needs write permission to push the data commit: *Settings →
Actions → General → Workflow permissions → Read and write permissions*.

GitHub disables scheduled workflows in public repositories after 60 days
without activity; the daily data commit counts as activity. GitHub may also
delay a scheduled run by some minutes, which is fine for a daily snapshot.

## Installing on Android

Open the Pages URL in Chrome, then menu → **Add to Home screen**. The service
worker caches the app shell and the last loaded day, so it opens offline
showing the last snapshot you viewed.

## Data model

`data/YYYY-MM-DD.json` holds the clean day:

```jsonc
{
  "date": "2026-11-10",
  "collected_at": "2026-11-11T02:30:00Z",
  "summary": { "arrivals": 7, "departures": 6, "cancelled": 2, "delayed": 2, "...": "..." },
  "arrivals": [ /* flights */ ],
  "departures": [ /* flights */ ]
}
```

Each flight keeps the ASU side under `asu` and the other airport under `other`:

```jsonc
{
  "direction": "arrival",
  "flight": { "iata": "AR1234", "icao": "ARG1234", "number": "1234" },
  "airline": { "name": "Aerolineas Argentinas", "iata": "AR", "icao": "ARG" },
  "status": "landed",
  "marketing": ["LA7658"],
  "codeshare_of": null,
  "asu":   { "iata": "ASU", "gate": "3", "baggage": "1", "scheduled_utc": "...", "...": "..." },
  "other": { "iata": "AEP", "airport": "Jorge Newbery", "...": "..." },
  "scheduled_utc": "2026-11-10T13:20:00Z",
  "estimated_utc": null,
  "actual_utc": "2026-11-10T13:32:00Z",
  "delay_minutes": 12
}
```

Rules that the tests pin down:

- Times are stored in UTC and displayed in `America/Asuncion`.
- `local_date` is the ASU calendar day of the operation, derived from the
  scheduled time in Asuncion, **not** from the UTC date: a flight at 21:35 on
  the 10th is 00:35 UTC on the 11th and still belongs to the 10th.
- One API response covers a rolling window of roughly a day and a half, so it
  mixes dates. A snapshot keeps only the flights of its own `local_date`;
  `outside_day` counts what was left out, and `data/raw` keeps all of it.
- Deduplication is scoped by day. The same flight number appears once per date
  in a single response, and those are different operations.
- A record with `flight.codeshared` is a marketing copy: it is merged into the
  operating flight and its number lands in `marketing`. If the operating flight
  is missing from the response, the copy is kept and `codeshare_of` names it.
- Missing values stay empty (`null`); nothing is invented or interpolated.
- Statuses: `scheduled`, `active`, `landed`, `cancelled`, `incident`,
  `diverted`. A flight counts as delayed from 15 minutes on.
- `data/index.json` lists every collected day with its totals, which is what
  the Historial tab charts.

Raw API responses are kept in `data/raw/YYYY-MM-DD_{arr|dep}.json` so a day can
be rebuilt without spending requests.

### One thing to keep an eye on

The free plan caps a response at 100 records and does not paginate for free.
The first real snapshot returned 71 arrival and 79 departure records for a
window of about a day and a half, which fits — but not by much. `collect.py`
prints a `WARNING` when `pagination.total` reaches the limit, and the value is
stored in every day file under `pagination`. If that warning ever shows up,
the day is truncated and the snapshot is missing flights.

## Regenerating assets

```powershell
python tools/make_icons.py    # icons/*.png
python tools/make_sample.py   # sample/ from tests/fixtures
```

Data source: [AviationStack](https://aviationstack.com) free plan, personal
non-commercial use.
