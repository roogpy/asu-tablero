"""Tests for the collector. No test ever touches the network.

Everything runs against the fixtures in tests/fixtures, which mirror the shape
of an AviationStack /v1/flights response.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

import asu
import collect

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any attempt to call the API during a test fails loudly."""

    def forbidden(*args, **kwargs):
        raise AssertionError("tests must not call the API")

    monkeypatch.setattr(collect, "fetch", forbidden)


@pytest.fixture
def arrivals_payload():
    return json.loads((FIXTURES / "arrivals.json").read_text(encoding="utf-8"))


@pytest.fixture
def departures_payload():
    return json.loads((FIXTURES / "departures.json").read_text(encoding="utf-8"))


@pytest.fixture
def day(arrivals_payload, departures_payload):
    return asu.build_day(
        arrivals_payload, departures_payload, "2026-11-10", "2026-11-11T02:30:00Z"
    )


# --------------------------------------------------------------------------- #
# field cleaning and time handling
# --------------------------------------------------------------------------- #
def test_blank_values_become_none():
    assert asu.clean("") is None
    assert asu.clean("   ") is None
    assert asu.clean(None) is None
    assert asu.clean(" ASU ") == "ASU"
    assert asu.as_int(None) is None
    assert asu.as_int("12") == 12
    assert asu.as_int("abc") is None


def test_to_utc_normalizes_offsets():
    assert asu.to_utc("2026-11-10T10:20:00-03:00") == "2026-11-10T13:20:00Z"
    assert asu.to_utc("2026-11-10T11:50:00+01:00") == "2026-11-10T10:50:00Z"
    assert asu.to_utc("2026-11-10T13:20:00Z") == "2026-11-10T13:20:00Z"


def test_to_utc_rejects_junk():
    assert asu.to_utc(None) is None
    assert asu.to_utc("") is None
    assert asu.to_utc("not a date") is None


def test_local_date_uses_asuncion():
    # 02:30 UTC is still the previous day in Paraguay (UTC-3).
    moment = datetime(2026, 11, 11, 2, 30, tzinfo=timezone.utc)
    assert asu.local_date(moment) == "2026-11-10"


# --------------------------------------------------------------------------- #
# normalization
# --------------------------------------------------------------------------- #
def test_arrival_puts_asu_on_the_asu_side(arrivals_payload):
    record = asu.normalize_flight(arrivals_payload["data"][0], "arrival")
    assert record["asu"]["iata"] == "ASU"
    assert record["other"]["iata"] == "AEP"
    assert record["scheduled_utc"] == "2026-11-10T13:20:00Z"
    assert record["actual_utc"] == "2026-11-10T13:32:00Z"
    assert record["delay_minutes"] == 12
    assert record["airline"]["name"] == "Aerolineas Argentinas"


def test_departure_puts_asu_on_the_asu_side(departures_payload):
    record = asu.normalize_flight(departures_payload["data"][0], "departure")
    assert record["asu"]["iata"] == "ASU"
    assert record["other"]["iata"] == "GRU"
    assert record["scheduled_utc"] == "2026-11-10T09:00:00Z"


def test_unknown_direction_is_rejected(arrivals_payload):
    with pytest.raises(ValueError):
        asu.normalize_flight(arrivals_payload["data"][0], "sideways")


def test_missing_values_stay_empty(day):
    diverted = [f for f in day["departures"] if f["flight"]["iata"] == "ZP801"][0]
    assert diverted["scheduled_utc"] is None
    assert diverted["estimated_utc"] is None
    assert diverted["delay_minutes"] is None
    assert diverted["asu"]["gate"] is None

    local = [f for f in day["arrivals"] if f["flight"]["icao"] == "PRY604"][0]
    assert local["flight"]["iata"] is None
    assert local["asu"]["terminal"] is None  # was "" in the response
    assert local["asu"]["gate"] is None


# --------------------------------------------------------------------------- #
# codeshare deduplication
# --------------------------------------------------------------------------- #
def test_codeshares_are_merged_into_the_operating_flight(day):
    numbers = [f["flight"]["iata"] for f in day["arrivals"]]
    assert "LA7658" not in numbers  # marketing copy of AR1234
    assert "AV6291" not in numbers  # marketing copy of CM441

    operating = {f["flight"]["iata"]: f for f in day["arrivals"]}
    assert operating["AR1234"]["marketing"] == ["LA7658"]
    assert operating["CM441"]["marketing"] == ["AV6291"]


def test_orphan_codeshare_is_kept_and_labelled(day):
    orphan = [f for f in day["arrivals"] if f["flight"]["iata"] == "AF2834"][0]
    assert orphan["codeshare_of"] == "LA8092"
    assert orphan["marketing"] == []


def test_dedupe_counts(day):
    assert len(day["arrivals"]) == 7  # 9 records - 2 merged codeshares
    assert len(day["departures"]) == 6  # 7 records - 1 merged codeshare


def test_repeated_operating_record_is_merged():
    rows = [
        {
            "flight_status": "landed",
            "arrival": {"iata": "ASU", "scheduled": "2026-11-10T10:00:00-03:00"},
            "departure": {"iata": "AEP"},
            "airline": {"name": "test air", "iata": "TT"},
            "flight": {"number": "1", "iata": "TT1", "icao": "TST1", "codeshared": None},
        },
        {
            "flight_status": "landed",
            "arrival": {"iata": "ASU", "scheduled": "2026-11-10T10:00:00-03:00"},
            "departure": {"iata": "AEP"},
            "airline": {"name": "test air", "iata": "TT"},
            "flight": {"number": "1", "iata": "TT1", "icao": "TST1", "codeshared": None},
        },
    ]
    flights = asu.flights_from_payload({"data": rows}, "arrival")
    assert len(flights) == 1
    assert flights[0]["marketing"] == []


def test_flights_are_sorted_by_scheduled_time_with_unknowns_last(day):
    times = [f["scheduled_utc"] for f in day["departures"]]
    known = [t for t in times if t]
    assert known == sorted(known)
    assert times[-1] is None


def test_internal_keys_are_not_written_out(day):
    for flight in day["arrivals"] + day["departures"]:
        assert not any(key.startswith("_") for key in flight)


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #
def test_summary_totals(day):
    summary = day["summary"]
    assert summary["arrivals"] == 7
    assert summary["departures"] == 6
    assert summary["total"] == 13
    assert summary["cancelled"] == 2
    assert summary["delayed"] == 2  # LA1458 (35 min) and CM442 (45 min)
    assert summary["codeshares_merged"] == 3


def test_summary_totals_match_the_lists(day):
    summary = day["summary"]
    assert summary["arrivals"] == len(day["arrivals"])
    assert summary["departures"] == len(day["departures"])
    assert sum(summary["by_status"]["all"].values()) == summary["total"]
    assert sum(entry["count"] for entry in summary["airlines"]) == summary["total"]
    assert sum(entry["count"] for entry in summary["places"]) == summary["total"]


def test_status_counts(day):
    assert day["summary"]["by_status"]["arrivals"] == {
        "active": 1,
        "cancelled": 1,
        "landed": 3,
        "scheduled": 2,
    }


def test_rankings_are_ordered_by_count(day):
    counts = [entry["count"] for entry in day["summary"]["airlines"]]
    assert counts == sorted(counts, reverse=True)


# --------------------------------------------------------------------------- #
# index
# --------------------------------------------------------------------------- #
def test_build_index(tmp_path, day):
    asu.write_json(tmp_path / "2026-11-10.json", day)
    other = dict(day)
    other["date"] = "2026-11-09"
    asu.write_json(tmp_path / "2026-11-09.json", other)
    asu.write_json(tmp_path / "budget.json", {"not": "a day"})
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    index = asu.build_index(tmp_path)
    assert [entry["date"] for entry in index["days"]] == ["2026-11-09", "2026-11-10"]
    assert index["latest"] == "2026-11-10"
    assert index["days"][1]["arrivals"] == 7
    assert index["days"][1]["file"] == "2026-11-10.json"


def test_build_index_on_empty_folder(tmp_path):
    index = asu.build_index(tmp_path)
    assert index["days"] == []
    assert index["latest"] is None


# --------------------------------------------------------------------------- #
# request budget
# --------------------------------------------------------------------------- #
def test_budget_defaults_when_file_is_missing(tmp_path):
    budget = asu.load_budget(tmp_path / "nope.json")
    assert budget["limits"] == {"per_day": 3, "per_month": 95}
    assert budget["day_count"] == 0


def test_budget_resets_on_a_new_day(tmp_path):
    path = tmp_path / "budget.json"
    asu.write_json(path, {"day": "2026-11-09", "day_count": 2, "month": "2026-11", "month_count": 40})
    now = datetime(2026, 11, 11, 2, 30, tzinfo=timezone.utc)  # 2026-11-10 in Asuncion
    budget = asu.roll_budget(asu.load_budget(path), now)
    assert budget["day"] == "2026-11-10"
    assert budget["day_count"] == 0
    assert budget["month_count"] == 40  # same month, kept


def test_budget_resets_on_a_new_month(tmp_path):
    path = tmp_path / "budget.json"
    asu.write_json(path, {"day": "2026-10-31", "day_count": 2, "month": "2026-10", "month_count": 90})
    now = datetime(2026, 11, 2, 2, 30, tzinfo=timezone.utc)
    budget = asu.roll_budget(asu.load_budget(path), now)
    assert budget["month"] == "2026-11"
    assert budget["month_count"] == 0


def test_budget_blocks_the_third_pair_of_requests():
    budget = asu.load_budget(Path("nope.json"))
    budget["day"] = "2026-11-10"
    budget["month"] = "2026-11"
    budget["day_count"] = 2
    allowed, reason = asu.budget_allows(budget, 2)
    assert allowed is False
    assert "daily budget" in reason


def test_budget_blocks_at_the_monthly_limit():
    budget = asu.load_budget(Path("nope.json"))
    budget["day_count"] = 0
    budget["month_count"] = 94
    allowed, reason = asu.budget_allows(budget, 2)
    assert allowed is False
    assert "monthly budget" in reason


def test_budget_allows_a_normal_run():
    budget = asu.load_budget(Path("nope.json"))
    allowed, reason = asu.budget_allows(budget, 2)
    assert allowed is True
    assert reason == "ok"


def test_register_requests_counts_both_periods():
    budget = asu.load_budget(Path("nope.json"))
    now = datetime(2026, 11, 11, 2, 30, tzinfo=timezone.utc)
    asu.register_requests(budget, 2, now)
    assert budget["day_count"] == 2
    assert budget["month_count"] == 2
    assert budget["total"] == 2
    assert budget["last_run"] == "2026-11-11T02:30:00Z"


def test_corrupt_budget_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "budget.json"
    path.write_text("not json", encoding="utf-8")
    budget = asu.load_budget(path)
    assert budget["day_count"] == 0
    assert budget["limits"]["per_day"] == 3


# --------------------------------------------------------------------------- #
# collector entry point, offline
# --------------------------------------------------------------------------- #
@pytest.fixture
def offline_tree(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True)
    shutil.copy(FIXTURES / "arrivals.json", raw_dir / "2026-11-10_arr.json")
    shutil.copy(FIXTURES / "departures.json", raw_dir / "2026-11-10_dep.json")
    monkeypatch.setattr(collect, "DATA_DIR", data_dir)
    monkeypatch.setattr(collect, "RAW_DIR", raw_dir)
    monkeypatch.setattr(collect, "BUDGET_PATH", data_dir / "budget.json")
    return data_dir


def test_from_raw_builds_day_and_index_without_requests(offline_tree):
    assert collect.main(["--from-raw", "--date", "2026-11-10"]) == 0
    day = asu.read_json(offline_tree / "2026-11-10.json")
    index = asu.read_json(offline_tree / "index.json")
    assert day["summary"]["total"] == 13
    assert index["latest"] == "2026-11-10"
    assert not (offline_tree / "budget.json").exists()  # no request was made


def test_from_raw_reports_a_missing_raw_file(offline_tree, capsys):
    assert collect.main(["--from-raw", "--date", "2026-11-09"]) == 1
    assert "missing raw file" in capsys.readouterr().err


def test_index_only_rebuilds_the_index(offline_tree):
    collect.main(["--from-raw", "--date", "2026-11-10"])
    (offline_tree / "index.json").unlink()
    assert collect.main(["--index-only"]) == 0
    assert asu.read_json(offline_tree / "index.json")["latest"] == "2026-11-10"


def test_exhausted_budget_stops_before_any_request(offline_tree, capsys):
    asu.write_json(
        offline_tree / "budget.json",
        {"day": asu.local_date(), "day_count": 3, "month": asu.local_date()[:7], "month_count": 3},
    )
    assert collect.main([]) == 2
    assert "Refusing to call the API" in capsys.readouterr().err


def test_missing_key_is_reported(monkeypatch, tmp_path):
    monkeypatch.delenv("AVIATIONSTACK_KEY", raising=False)
    monkeypatch.setattr(collect, "ROOT", tmp_path)  # no .env there
    with pytest.raises(collect.CollectError) as error:
        collect.read_key()
    assert "AVIATIONSTACK_KEY" in str(error.value)


def test_key_is_read_from_env_file(monkeypatch, tmp_path):
    monkeypatch.delenv("AVIATIONSTACK_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "# comment\nAVIATIONSTACK_KEY='secret-value'\n", encoding="utf-8"
    )
    monkeypatch.setattr(collect, "ROOT", tmp_path)
    assert collect.read_key() == "secret-value"
