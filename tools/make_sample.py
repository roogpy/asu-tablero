"""Build sample/ from the test fixtures, so the PWA can be reviewed offline.

The PWA reads data/ first and only falls back to sample/ when no real day has
been collected yet; in that case it shows a visible "datos de muestra" badge.
Sample data never lands in data/.

    python tools/make_sample.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asu  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
SAMPLE_DIR = ROOT / "sample"
DATE = "2026-11-10"


def main() -> int:
    day = asu.build_day(
        asu.read_json(FIXTURES / "arrivals.json"),
        asu.read_json(FIXTURES / "departures.json"),
        DATE,
        "2026-11-11T02:30:00Z",
    )
    day["sample"] = True
    day["source"] = "sample built from tests/fixtures (not real data)"
    asu.write_json(SAMPLE_DIR / (DATE + ".json"), day)

    index = asu.build_index(SAMPLE_DIR)
    index["sample"] = True
    asu.write_json(SAMPLE_DIR / "index.json", index)
    print("wrote sample/" + DATE + ".json and sample/index.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
