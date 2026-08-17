"""Tyre degradation and compound performance analysis.

Degradation is estimated with a simple linear fit (lap time vs. tyre age)
per stint - a deterministic calculation, not a predictive model. It is a
rough signal, since pace also drifts with fuel load, traffic, and track
evolution, so read it as trend direction and magnitude, not a precise
physical degradation rate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from fastf1.core import Laps

from saif1.analysis.quality import filter_usable_laps

MIN_LAPS_FOR_DEGRADATION_FIT = 3


def stint_degradation(stint_laps: Laps) -> dict:
    """Estimate the lap-time trend across a single stint via linear
    regression of lap time against tyre age.

    Args:
        stint_laps: Laps belonging to a single driver's single stint.

    Returns:
        {
            "slope_s_per_lap": float | None,  # positive = getting slower
            "usable_laps": int,
        }
        slope_s_per_lap is None when fewer than
        MIN_LAPS_FOR_DEGRADATION_FIT usable laps are available, since a
        linear fit isn't meaningful on that few points.
    """
    usable = filter_usable_laps(stint_laps)
    valid = usable.dropna(subset=["LapTime", "TyreLife"])

    if len(valid) < MIN_LAPS_FOR_DEGRADATION_FIT:
        return {"slope_s_per_lap": None, "usable_laps": int(len(valid))}

    x = valid["TyreLife"].to_numpy(dtype=float)
    y = valid["LapTime"].dt.total_seconds().to_numpy(dtype=float)
    slope, _intercept = np.polyfit(x, y, 1)

    return {"slope_s_per_lap": float(slope), "usable_laps": int(len(valid))}


def compound_performance(laps: Laps) -> list[dict]:
    """Summarize representative pace per tyre compound across a session.

    Returns:
        List of dicts sorted by median pace, fastest first:
        {
            "compound": str,
            "median_lap_time_s": float,
            "usable_laps": int,
        }
    """
    usable = filter_usable_laps(laps)
    results: list[dict] = []

    for compound, group in usable.groupby("Compound"):
        if pd.isna(compound):
            continue
        lap_times = group["LapTime"].dropna().dt.total_seconds()
        if lap_times.empty:
            continue
        results.append(
            {
                "compound": compound,
                "median_lap_time_s": float(lap_times.median()),
                "usable_laps": int(len(lap_times)),
            }
        )

    results.sort(key=lambda r: r["median_lap_time_s"])
    return results
