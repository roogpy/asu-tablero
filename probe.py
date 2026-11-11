"""Phase 0 probe: find out whether the free plan covers a full day at ASU.

Exactly two requests (arrivals and departures), raw responses saved under
data/raw/, then a report per direction. On any failure it stops: no retries.
The API key and the request URL are never printed.

    python probe.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import asu
from collect import (
    BUDGET_PATH,
    DIRECTIONS,
    CollectError,
    fetch,
    raw_path,
    read_key,
)

ROOT = Path(__file__).resolve().parent


def local_stamp(value) -> str:
    if not value:
        return "sin dato"
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment.astimezone(asu.local_timezone()).strftime("%Y-%m-%d %H:%M")


def describe(payload: dict, direction: str) -> None:
    rows = payload.get("data") or []
    pagination = payload.get("pagination") or {}
    normalized = [asu.normalize_flight(row, direction) for row in rows]
    codeshares = [r for r in normalized if r.get("_is_marketing")]
    unique = asu.dedupe([dict(r) for r in normalized])
    scheduled = sorted(r["scheduled_utc"] for r in unique if r["scheduled_utc"])

    print("")
    print("== " + direction + "s ==")
    print("  records returned     : " + str(len(rows)))
    print("  pagination.total     : " + str(pagination.get("total")))
    print("  pagination.count     : " + str(pagination.get("count")))
    print("  codeshare copies     : " + str(len(codeshares)))
    print("  unique flights       : " + str(len(unique)))
    print("  by flight_status     : " + ", ".join(
        name + "=" + str(count) for name, count in asu.status_counts(unique).items()
    ))
    print("  first scheduled (PY) : " + local_stamp(scheduled[0] if scheduled else None))
    print("  last scheduled (PY)  : " + local_stamp(scheduled[-1] if scheduled else None))
    dates = sorted({r["flight_date"] for r in unique if r["flight_date"]})
    print("  flight_date values   : " + (", ".join(dates) if dates else "sin dato"))


def main() -> int:
    now = datetime.now(timezone.utc)
    date = asu.local_date(now)

    budget = asu.roll_budget(asu.load_budget(BUDGET_PATH), now)
    allowed, reason = asu.budget_allows(budget, len(DIRECTIONS))
    if not allowed:
        print("Refusing to call the API: " + reason, file=sys.stderr)
        return 2

    sent = 0
    payloads = {}
    try:
        try:
            for short in DIRECTIONS:
                sent += 1
                payloads[short] = fetch(short, read_key())
                asu.write_json(raw_path(date, short), payloads[short])
                print("saved data/raw/" + raw_path(date, short).name)
        finally:
            if sent:
                asu.write_json(BUDGET_PATH, asu.register_requests(budget, sent, now))
    except CollectError as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1

    for short, direction in DIRECTIONS.items():
        describe(payloads[short], direction)

    print("")
    print("Compare the first and last scheduled times above with a full day")
    print("(roughly 05:00-23:59 Paraguay time) to judge the coverage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
