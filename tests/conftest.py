"""Shared fixtures: synthetic Laps data so analysis tests run offline and
fast, without hitting the FastF1 API.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastf1.core import Laps


def _td(seconds: float | None) -> pd.Timedelta:
    return pd.NaT if seconds is None else pd.to_timedelta(seconds, unit="s")


def make_laps(rows: list[dict]) -> Laps:
    """Build a minimal, well-formed Laps object from plain dicts.

    Each row may omit any column; sensible defaults are filled in so the
    pick_* quality-filter methods (which expect these columns to exist)
    work correctly.
    """
    defaults = {
        "Time": pd.NaT,
        "Driver": "XXX",
        "DriverNumber": "0",
        "LapTime": None,
        "LapNumber": 1,
        "Stint": 1,
        "PitInTime": None,
        "PitOutTime": None,
        "Compound": "MEDIUM",
        "TyreLife": 1,
        "Team": "Test Team",
        "TrackStatus": "1",
        "Position": None,
        "Deleted": False,
        "DeletedReason": "",
        "IsAccurate": True,
    }

    built_rows = []
    for row in rows:
        merged = {**defaults, **row}
        merged["LapTime"] = _td(merged["LapTime"])
        merged["PitInTime"] = _td(merged["PitInTime"])
        merged["PitOutTime"] = _td(merged["PitOutTime"])
        built_rows.append(merged)

    # Explicit columns so an empty `rows` list still yields a DataFrame
    # with the columns pick_*() methods expect, instead of a zero-column
    # frame that raises KeyError on first access.
    df = pd.DataFrame(built_rows, columns=list(defaults.keys()))
    return Laps(df)


@pytest.fixture
def two_driver_race_laps() -> Laps:
    """Ten green-flag racing laps each for two drivers, VER slightly
    faster than HAM, with one pit stop each and one deleted lap for HAM.
    """
    rows = []
    for lap in range(1, 11):
        rows.append(
            {
                "Driver": "VER",
                "DriverNumber": "1",
                "LapNumber": lap,
                "LapTime": 90.0 + (lap * 0.01),
                "Stint": 1 if lap <= 5 else 2,
                "Compound": "SOFT" if lap <= 5 else "HARD",
                "TyreLife": lap if lap <= 5 else lap - 5,
                "PitInTime": 90.0 * lap if lap == 5 else None,
                "PitOutTime": 90.0 * lap + 24 if lap == 6 else None,
                "Position": 1,
            }
        )
    for lap in range(1, 11):
        rows.append(
            {
                "Driver": "HAM",
                "DriverNumber": "44",
                "LapNumber": lap,
                "LapTime": 91.0 + (lap * 0.01),
                "Stint": 1 if lap <= 6 else 2,
                "Compound": "SOFT" if lap <= 6 else "HARD",
                "TyreLife": lap if lap <= 6 else lap - 6,
                "PitInTime": 91.0 * lap if lap == 6 else None,
                "PitOutTime": 91.0 * lap + 25 if lap == 7 else None,
                "Position": 2,
                "Deleted": lap == 3,
                "DeletedReason": "TRACK LIMITS" if lap == 3 else "",
            }
        )
    return make_laps(rows)
