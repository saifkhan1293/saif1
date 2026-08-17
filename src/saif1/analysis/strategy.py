"""Strategy analysis: pit stops and position changes."""

from __future__ import annotations

import logging

import pandas as pd
from fastf1.core import Laps, Session

from saif1.config import normalize_compound
from saif1.exceptions import DriverNotFoundError

logger = logging.getLogger(__name__)


def extract_pit_stops(laps: Laps) -> list[dict]:
    """Extract pit stops from lap data.

    A pit stop is identified by a lap with a non-null PitInTime, matched
    to the same driver's next lap (by LapNumber) with a non-null
    PitOutTime.

    Note: `pit_lane_time_s` measures time from crossing the pit entry line
    to crossing the pit exit line (PitOutTime - PitInTime). This includes
    pit lane travel time, not just the stationary "box" time - FastF1's
    basic timing data does not expose stationary time separately. Treat it
    as an approximation of total time lost, not a precise stop duration.

    `compound_before`/`compound_after` are validated via
    config.normalize_compound: a real compound name, "UNKNOWN" (FastF1
    itself doesn't know, or the value was missing), "UNRECOGNIZED" (a
    non-null value present but not in FastF1's known vocabulary - e.g.
    corrupted data), or None only when there's no next/out lap at all to
    read a compound from.

    Returns:
        List of dicts ordered by driver then lap:
        {
            "driver": str,
            "in_lap": int,
            "compound_before": str | None,
            "compound_after": str | None,
            "pit_lane_time_s": float | None,
        }
    """
    pit_stops: list[dict] = []
    in_laps = laps[laps["PitInTime"].notna()].sort_values(["Driver", "LapNumber"])

    for _, in_lap in in_laps.iterrows():
        driver = in_lap["Driver"]
        driver_laps = laps[laps["Driver"] == driver].sort_values("LapNumber")
        next_laps = driver_laps[driver_laps["LapNumber"] > in_lap["LapNumber"]]
        out_lap = next_laps.iloc[0] if not next_laps.empty else None

        pit_lane_time_s = None
        compound_after = None
        if out_lap is not None and pd.notna(out_lap.get("PitOutTime")):
            pit_lane_time_s = (out_lap["PitOutTime"] - in_lap["PitInTime"]).total_seconds()
            compound_after = normalize_compound(out_lap.get("Compound"))

        pit_stops.append(
            {
                "driver": driver,
                "in_lap": int(in_lap["LapNumber"]),
                "compound_before": normalize_compound(in_lap.get("Compound")),
                "compound_after": compound_after,
                "pit_lane_time_s": pit_lane_time_s,
            }
        )

    return pit_stops


def position_changes(session: Session) -> list[dict]:
    """Calculate grid-to-finish position changes for every driver.

    Uses session.results (official classification), not lap-by-lap
    Position data, since grid/finish position is the standard definition
    of "positions gained or lost" in F1.

    Returns:
        List of dicts sorted by positions gained, most gained first:
        {
            "driver": str,
            "start_position": int | None,
            "finish_position": int | None,
            "positions_gained": int | None,  # positive = gained places
            "status": str,
        }
    """
    results = session.results
    changes: list[dict] = []

    for _, row in results.iterrows():
        grid = row.get("GridPosition")
        finish = row.get("Position")

        gained = None
        if pd.notna(grid) and pd.notna(finish):
            gained = int(grid) - int(finish)

        changes.append(
            {
                "driver": row.get("Abbreviation"),
                "start_position": int(grid) if pd.notna(grid) else None,
                "finish_position": int(finish) if pd.notna(finish) else None,
                "positions_gained": gained,
                "status": row.get("Status"),
            }
        )

    changes.sort(key=lambda c: (c["positions_gained"] is None, -(c["positions_gained"] or 0)))
    return changes


def position_progression(laps: Laps, driver: str) -> list[dict]:
    """Lap-by-lap track position for one driver across the session.

    Returns:
        List of {"lap": int, "position": int | None}, ordered by lap.

    Raises:
        DriverNotFoundError: If the driver has no laps in the session.
    """
    driver_laps = laps.pick_drivers([driver]).sort_values("LapNumber")
    if driver_laps.empty:
        raise DriverNotFoundError(f"No lap data found for driver '{driver}'.")

    return [
        {
            "lap": int(row["LapNumber"]),
            "position": int(row["Position"]) if pd.notna(row["Position"]) else None,
        }
        for _, row in driver_laps.iterrows()
    ]
