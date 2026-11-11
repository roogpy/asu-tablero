"""Pure data helpers for the ASU daily snapshot.

No network access and no hidden state, so the whole normalization pipeline can
be tested with the fixtures under tests/fixtures.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

AIRPORT = {
    "iata": "ASU",
    "icao": "SGAS",
    "name": "Silvio Pettirossi International Airport",
    "city": "Luque",
    "country": "Paraguay",
    "timezone": "America/Asuncion",
}

# Paraguay dropped DST in 2024 and stays on UTC-3 all year.
LOCAL_UTC_OFFSET = timedelta(hours=-3)

KNOWN_STATUSES = (
    "scheduled",
    "active",
    "landed",
    "cancelled",
    "incident",
    "diverted",
)

# A flight counts as delayed from this many minutes on.
DELAY_THRESHOLD_MINUTES = 15


# --------------------------------------------------------------------------- #
# time helpers
# --------------------------------------------------------------------------- #
def local_timezone():
    """America/Asuncion when the tz database is available, else a fixed UTC-3."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(AIRPORT["timezone"])
    except Exception:  # pragma: no cover - depends on the host tz database
        return timezone(LOCAL_UTC_OFFSET)


def local_date(now: datetime | None = None) -> str:
    """The calendar date in Asuncion, which is the day a snapshot belongs to."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(local_timezone()).date().isoformat()


def to_utc(value):
    """Normalize an AviationStack timestamp to an ISO string ending in Z."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        # The API always sends an offset. Without one we cannot guess a shift,
        # so the value is taken as UTC rather than invented.
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now_iso(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# field cleaning
# --------------------------------------------------------------------------- #
def clean(value):
    """Blank strings become None. Missing values are never filled in."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return value


def title(value):
    text = clean(value)
    if not isinstance(text, str):
        return text
    if text.isupper() or text.islower():
        return text.title()
    return text


def upper(value):
    text = clean(value)
    if isinstance(text, str):
        return text.upper()
    return text


def as_int(value):
    value = clean(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def endpoint(block: dict | None) -> dict:
    block = block or {}
    return {
        "airport": title(block.get("airport")),
        "iata": upper(block.get("iata")),
        "icao": upper(block.get("icao")),
        "timezone": clean(block.get("timezone")),
        "terminal": upper(block.get("terminal")),
        "gate": upper(block.get("gate")),
        "baggage": upper(block.get("baggage")),
        "delay_minutes": as_int(block.get("delay")),
        "scheduled_utc": to_utc(block.get("scheduled")),
        "estimated_utc": to_utc(block.get("estimated")),
        "actual_utc": to_utc(block.get("actual")),
    }


# --------------------------------------------------------------------------- #
# normalization
# --------------------------------------------------------------------------- #
def flight_key(record: dict) -> str:
    """Stable identity for an operating flight."""
    flight = record.get("flight") or {}
    airline = record.get("airline") or {}
    for candidate in (flight.get("iata"), flight.get("icao")):
        if candidate:
            return str(candidate).upper()
    airline_code = airline.get("iata") or airline.get("icao") or "??"
    number = flight.get("number") or "?"
    return str(airline_code).upper() + str(number)


def normalize_flight(raw: dict, direction: str) -> dict:
    """Turn one AviationStack record into our own shape.

    `direction` is "arrival" or "departure" and says which endpoint is ASU.
    """
    if direction not in ("arrival", "departure"):
        raise ValueError("unknown direction: " + str(direction))

    departure = endpoint(raw.get("departure"))
    arrival = endpoint(raw.get("arrival"))
    flight = raw.get("flight") or {}
    airline = raw.get("airline") or {}
    codeshared = flight.get("codeshared") or raw.get("codeshared") or None

    own = arrival if direction == "arrival" else departure
    other = departure if direction == "arrival" else arrival

    record = {
        "direction": direction,
        "flight": {
            "iata": upper(flight.get("iata")),
            "icao": upper(flight.get("icao")),
            "number": clean(flight.get("number")),
        },
        "airline": {
            "name": title(airline.get("name")),
            "iata": upper(airline.get("iata")),
            "icao": upper(airline.get("icao")),
        },
        "status": clean(raw.get("flight_status")),
        "flight_date": clean(raw.get("flight_date")),
        "marketing": [],
        "codeshare_of": None,
        "asu": own,
        "other": other,
        "scheduled_utc": own["scheduled_utc"],
        "estimated_utc": own["estimated_utc"],
        "actual_utc": own["actual_utc"],
        "delay_minutes": own["delay_minutes"],
    }
    if codeshared:
        operating = upper(codeshared.get("flight_iata") or codeshared.get("flight_icao"))
        record["_operating_key"] = operating or flight_key(record)
        record["_is_marketing"] = True
    else:
        record["_operating_key"] = flight_key(record)
        record["_is_marketing"] = False
    return record


def add_marketing_number(target: dict, number) -> None:
    number = upper(number)
    if not number:
        return
    if number == target["flight"]["iata"]:
        return
    if number in target["marketing"]:
        return
    target["marketing"].append(number)
    target["marketing"].sort()


def dedupe(records: list) -> list:
    """Collapse codeshares onto the operating flight.

    A record carrying `flight.codeshared` is a marketing copy: its own number is
    attached to the operating flight's `marketing` list. When the operating
    flight is absent from the response the first marketing copy is kept instead
    and `codeshare_of` names the operating number, so nothing is dropped.
    """
    operating: dict = {}
    order: list = []
    marketing_rows: list = []

    for record in records:
        if record.get("_is_marketing"):
            marketing_rows.append(record)
            continue
        key = record["_operating_key"]
        if key in operating:
            add_marketing_number(operating[key], record["flight"]["iata"])
            continue
        operating[key] = record
        order.append(key)

    for record in marketing_rows:
        key = record["_operating_key"]
        if key in operating:
            add_marketing_number(operating[key], record["flight"]["iata"])
            continue
        record["codeshare_of"] = key
        operating[key] = record
        order.append(key)

    result = []
    for key in order:
        record = operating[key]
        record.pop("_operating_key", None)
        record.pop("_is_marketing", None)
        result.append(record)

    result.sort(
        key=lambda r: (
            r["scheduled_utc"] is None,
            r["scheduled_utc"] or "",
            r["flight"]["iata"] or "",
        )
    )
    return result


def flights_from_payload(payload: dict, direction: str) -> list:
    rows = (payload or {}).get("data") or []
    return dedupe([normalize_flight(row, direction) for row in rows])


# --------------------------------------------------------------------------- #
# aggregation
# --------------------------------------------------------------------------- #
def is_delayed(record: dict) -> bool:
    delay = record.get("delay_minutes")
    return isinstance(delay, int) and delay >= DELAY_THRESHOLD_MINUTES


def status_counts(records: list) -> dict:
    counts: dict = {}
    for record in records:
        key = record.get("status") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def ranked(mapping: dict) -> list:
    return [
        {"name": name, "count": count}
        for name, count in sorted(mapping.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def summarize(arrivals: list, departures: list) -> dict:
    everything = arrivals + departures
    airlines: dict = {}
    places: dict = {}
    for record in everything:
        name = record["airline"]["name"] or record["airline"]["iata"] or "Sin dato"
        airlines[name] = airlines.get(name, 0) + 1
        place = record["other"]["iata"] or record["other"]["airport"] or "Sin dato"
        places[place] = places.get(place, 0) + 1

    return {
        "arrivals": len(arrivals),
        "departures": len(departures),
        "total": len(everything),
        "cancelled": sum(1 for r in everything if r.get("status") == "cancelled"),
        "delayed": sum(1 for r in everything if is_delayed(r)),
        "by_status": {
            "arrivals": status_counts(arrivals),
            "departures": status_counts(departures),
            "all": status_counts(everything),
        },
        "airlines": ranked(airlines),
        "places": ranked(places),
        "codeshares_merged": sum(len(r["marketing"]) for r in everything),
    }


def build_day(
    arrivals_payload: dict,
    departures_payload: dict,
    date: str,
    collected_at: str | None = None,
) -> dict:
    arrivals = flights_from_payload(arrivals_payload, "arrival")
    departures = flights_from_payload(departures_payload, "departure")
    return {
        "schema": 1,
        "date": date,
        "airport": AIRPORT,
        "collected_at": collected_at or utc_now_iso(),
        "source": "aviationstack /v1/flights",
        "pagination": {
            "arrivals": (arrivals_payload or {}).get("pagination") or {},
            "departures": (departures_payload or {}).get("pagination") or {},
        },
        "summary": summarize(arrivals, departures),
        "arrivals": arrivals,
        "departures": departures,
    }


def index_entry(day: dict) -> dict:
    summary = day["summary"]
    return {
        "date": day["date"],
        "file": day["date"] + ".json",
        "arrivals": summary["arrivals"],
        "departures": summary["departures"],
        "total": summary["total"],
        "cancelled": summary["cancelled"],
        "delayed": summary["delayed"],
        "collected_at": day.get("collected_at"),
    }


DAY_FILE_GLOB = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].json"


def build_index(data_dir) -> dict:
    days = []
    for path in sorted(Path(data_dir).glob(DAY_FILE_GLOB)):
        try:
            day = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(day, dict) and "summary" in day and "date" in day:
            days.append(index_entry(day))
    days.sort(key=lambda entry: entry["date"])
    return {
        "schema": 1,
        "airport": AIRPORT,
        "updated_at": utc_now_iso(),
        "latest": days[-1]["date"] if days else None,
        "days": days,
    }


# --------------------------------------------------------------------------- #
# request budget
# --------------------------------------------------------------------------- #
DEFAULT_BUDGET = {
    "schema": 1,
    "limits": {"per_day": 3, "per_month": 95},
    "day": None,
    "day_count": 0,
    "month": None,
    "month_count": 0,
    "total": 0,
    "last_run": None,
}


def load_budget(path) -> dict:
    path = Path(path)
    budget = json.loads(json.dumps(DEFAULT_BUDGET))
    if not path.exists():
        return budget
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return budget
    if not isinstance(stored, dict):
        return budget
    for key, value in stored.items():
        if key != "limits":
            budget[key] = value
    limits = stored.get("limits")
    if isinstance(limits, dict):
        for key, value in limits.items():
            if isinstance(value, int):
                budget["limits"][key] = value
    return budget


def roll_budget(budget: dict, now: datetime) -> dict:
    """Reset the day and month counters when the period changes."""
    day = local_date(now)
    month = day[:7]
    if budget.get("day") != day:
        budget["day"] = day
        budget["day_count"] = 0
    if budget.get("month") != month:
        budget["month"] = month
        budget["month_count"] = 0
    return budget


def budget_allows(budget: dict, requests_wanted: int):
    """(allowed, reason). The limits are hard: no call is made past them."""
    limits = budget["limits"]
    if budget["day_count"] + requests_wanted > limits["per_day"]:
        return False, (
            "daily budget reached: "
            + str(budget["day_count"])
            + "/"
            + str(limits["per_day"])
            + " requests already made on "
            + str(budget["day"])
        )
    if budget["month_count"] + requests_wanted > limits["per_month"]:
        return False, (
            "monthly budget reached: "
            + str(budget["month_count"])
            + "/"
            + str(limits["per_month"])
            + " requests already made in "
            + str(budget["month"])
        )
    return True, "ok"


def register_requests(budget: dict, count: int, now: datetime) -> dict:
    budget["day_count"] = budget.get("day_count", 0) + count
    budget["month_count"] = budget.get("month_count", 0) + count
    budget["total"] = budget.get("total", 0) + count
    budget["last_run"] = utc_now_iso(now)
    return budget


def write_json(path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
