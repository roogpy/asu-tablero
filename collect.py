"""Collect one daily snapshot of ASU arrivals and departures.

Normal run: exactly two API requests (one per direction). The request budget in
data/budget.json is checked first and is a hard stop: no call is made past it.

    python collect.py                 # two requests, writes today's snapshot
    python collect.py --from-raw      # rebuild a day from data/raw, no requests
    python collect.py --index-only    # rebuild data/index.json only
    python collect.py --date 2026-11-10

The API key is read from the AVIATIONSTACK_KEY environment variable (GitHub
Actions secret) or from a local .env file. It is never printed, and neither is
the request URL.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import asu

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
BUDGET_PATH = DATA_DIR / "budget.json"

API_URL = "http://api.aviationstack.com/v1/flights"
REQUEST_TIMEOUT = 45
RESULT_LIMIT = 100
DIRECTIONS = {"arr": "arrival", "dep": "departure"}


class CollectError(RuntimeError):
    """Something went wrong. We report it and stop; we never retry."""


def read_key() -> str:
    key = os.environ.get("AVIATIONSTACK_KEY", "").strip()
    if key:
        return key
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            if name.strip() == "AVIATIONSTACK_KEY":
                return value.strip().strip("'\"")
    raise CollectError(
        "AVIATIONSTACK_KEY is not set (environment variable or .env file)"
    )


def fetch(short: str, key: str) -> dict:
    """One request to /v1/flights. No retries, and the URL is never logged."""
    import requests

    params = {
        "access_key": key,
        short + "_iata": asu.AIRPORT["iata"],
        "limit": RESULT_LIMIT,
    }
    try:
        response = requests.get(API_URL, params=params, timeout=REQUEST_TIMEOUT)
    except Exception as exc:  # network layer, message may not mention the URL
        raise CollectError(
            "request for " + DIRECTIONS[short] + "s failed: " + type(exc).__name__
        ) from None

    if response.status_code != 200:
        raise CollectError(
            "request for "
            + DIRECTIONS[short]
            + "s returned HTTP "
            + str(response.status_code)
        )
    try:
        payload = response.json()
    except ValueError:
        raise CollectError(
            "request for " + DIRECTIONS[short] + "s returned a non-JSON body"
        ) from None

    if isinstance(payload, dict) and payload.get("error"):
        error = payload["error"]
        code = error.get("code") if isinstance(error, dict) else error
        message = error.get("message") if isinstance(error, dict) else ""
        raise CollectError("API error for " + DIRECTIONS[short] + "s: " + str(code) + " " + str(message))
    if not isinstance(payload, dict) or "data" not in payload:
        raise CollectError(
            "unexpected response shape for " + DIRECTIONS[short] + "s"
        )
    return payload


def raw_path(date: str, short: str) -> Path:
    return RAW_DIR / (date + "_" + short + ".json")


def load_raw(date: str) -> tuple[dict, dict]:
    payloads = {}
    for short in DIRECTIONS:
        path = raw_path(date, short)
        if not path.exists():
            raise CollectError("missing raw file: " + path.name)
        payloads[short] = asu.read_json(path)
    return payloads["arr"], payloads["dep"]


def report(day: dict) -> None:
    summary = day["summary"]
    print("Snapshot " + day["date"])
    print("  arrivals   : " + str(summary["arrivals"]))
    print("  departures : " + str(summary["departures"]))
    print("  cancelled  : " + str(summary["cancelled"]))
    print("  delayed    : " + str(summary["delayed"]))
    print("  codeshares merged: " + str(summary["codeshares_merged"]))
    print("  by status  : " + ", ".join(
        name + "=" + str(count) for name, count in summary["by_status"]["all"].items()
    ))


def write_index() -> dict:
    index = asu.build_index(DATA_DIR)
    asu.write_json(DATA_DIR / "index.json", index)
    print("index.json: " + str(len(index["days"])) + " day(s), latest " + str(index["latest"]))
    return index


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collect the daily ASU snapshot.")
    parser.add_argument("--date", help="snapshot date (YYYY-MM-DD, default: today in Asuncion)")
    parser.add_argument(
        "--from-raw",
        action="store_true",
        help="rebuild the day from data/raw without calling the API",
    )
    parser.add_argument(
        "--index-only", action="store_true", help="rebuild data/index.json and exit"
    )
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    date = args.date or asu.local_date(now)

    try:
        if args.index_only:
            write_index()
            return 0

        if args.from_raw:
            arrivals, departures = load_raw(date)
            requests_sent = 0
        else:
            budget = asu.roll_budget(asu.load_budget(BUDGET_PATH), now)
            allowed, reason = asu.budget_allows(budget, len(DIRECTIONS))
            if not allowed:
                print("Refusing to call the API: " + reason, file=sys.stderr)
                return 2

            key = read_key()
            payloads = {}
            requests_sent = 0
            try:
                for short in DIRECTIONS:
                    requests_sent += 1
                    payloads[short] = fetch(short, key)
                    asu.write_json(raw_path(date, short), payloads[short])
            finally:
                # A failed request still consumes quota, so it is always recorded.
                if requests_sent:
                    asu.write_json(
                        BUDGET_PATH, asu.register_requests(budget, requests_sent, now)
                    )
            arrivals, departures = payloads["arr"], payloads["dep"]

        day = asu.build_day(arrivals, departures, date, asu.utc_now_iso(now))
        asu.write_json(DATA_DIR / (date + ".json"), day)
        report(day)
        write_index()
        if requests_sent:
            budget = asu.load_budget(BUDGET_PATH)
            print(
                "budget: "
                + str(budget["day_count"])
                + "/"
                + str(budget["limits"]["per_day"])
                + " today, "
                + str(budget["month_count"])
                + "/"
                + str(budget["limits"]["per_month"])
                + " this month"
            )
        return 0
    except CollectError as exc:
        print("Error: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
