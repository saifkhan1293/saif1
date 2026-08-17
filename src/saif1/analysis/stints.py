"""Tyre stint extraction: per-driver, per-stint compound and lap range."""

from __future__ import annotations

from typing import Optional

import pandas as pd
from fastf1.core import Laps

from saif1.exceptions import DriverNotFoundError


def extract_stints(laps: Laps, driver: Optional[str] = None) -> list[dict]:
    """Extract tyre stints (compound + lap range) from lap data.

    Args:
        laps: Full session Laps (e.g. session.laps).
        driver: If given, restrict to this driver only.

    Returns:
        List of dicts, one per stint, ordered by driver then stint number:
        {
            "driver": str,
            "stint_number": int,
            "compound": str,
            "start_lap": int,
            "end_lap": int,
            "stint_length": int,
            "lap_times_s": list[float],  # lap-number order, missing dropped
        }

    Raises:
        DriverNotFoundError: If `driver` is given but has no laps.
    """
    subset = laps
    if driver is not None:
        subset = laps.pick_drivers([driver])
        if subset.empty:
            raise DriverNotFoundError(f"No lap data found for driver '{driver}'.")

    stints: list[dict] = []
    for (drv, stint_num), stint_laps in subset.groupby(["Driver", "Stint"]):
        if pd.isna(stint_num):
            continue

        stint_laps = stint_laps.sort_values("LapNumber")
        compounds = stint_laps["Compound"].dropna().unique()
        lap_times_s = stint_laps["LapTime"].dropna().dt.total_seconds().tolist()

        stints.append(
            {
                "driver": drv,
                "stint_number": int(stint_num),
                "compound": compounds[0] if len(compounds) else "UNKNOWN",
                "start_lap": int(stint_laps["LapNumber"].min()),
                "end_lap": int(stint_laps["LapNumber"].max()),
                "stint_length": int(len(stint_laps)),
                "lap_times_s": lap_times_s,
            }
        )

    stints.sort(key=lambda s: (s["driver"], s["stint_number"]))
    return stints
