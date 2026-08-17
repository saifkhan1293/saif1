"""Race pace calculations: representative lap times per driver, and
driver-to-driver pace comparisons.

Median is used as the primary representative-pace statistic rather than
mean, since it is more robust to outlier laps (traffic, minor mistakes)
that survive the quality filter but still aren't representative of true
pace.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from fastf1.core import Laps

from saif1.analysis.quality import filter_usable_laps
from saif1.exceptions import DriverNotFoundError

logger = logging.getLogger(__name__)


def lap_time_to_seconds(lap_time: pd.Timedelta) -> Optional[float]:
    """Convert a FastF1 LapTime (Timedelta) to seconds, or None if missing."""
    if pd.isna(lap_time):
        return None
    return lap_time.total_seconds()


def calculate_race_pace(laps: Laps, driver: str) -> dict:
    """Calculate representative race-pace statistics for one driver.

    Args:
        laps: Full session Laps (e.g. session.laps).
        driver: Driver identifier as used by FastF1 (3-letter code, e.g.
            "VER", or driver number string).

    Returns:
        {
            "driver": str,
            "mean_lap_time_s": float | None,
            "median_lap_time_s": float | None,
            "best_lap_time_s": float | None,
            "usable_laps": int,
            "total_laps": int,
        }

    Raises:
        DriverNotFoundError: If the driver has no laps in the session.
    """
    driver_laps = laps.pick_drivers([driver])
    if driver_laps.empty:
        raise DriverNotFoundError(f"No lap data found for driver '{driver}'.")

    usable = filter_usable_laps(driver_laps)
    seconds = usable["LapTime"].dropna().dt.total_seconds()

    return {
        "driver": driver,
        "mean_lap_time_s": float(seconds.mean()) if not seconds.empty else None,
        "median_lap_time_s": float(seconds.median()) if not seconds.empty else None,
        "best_lap_time_s": float(seconds.min()) if not seconds.empty else None,
        "usable_laps": int(len(seconds)),
        "total_laps": int(len(driver_laps)),
    }


def compare_driver_pace(laps: Laps, driver_1: str, driver_2: str) -> dict:
    """Compare representative race pace between two drivers.

    Returns:
        {
            "driver_1": str,
            "driver_2": str,
            "median_pace_difference_s": float | None,
            "mean_pace_difference_s": float | None,
            "usable_laps_driver_1": int,
            "usable_laps_driver_2": int,
        }

    A positive *_pace_difference_s means driver_1 was slower (higher lap
    time) than driver_2.
    """
    stats_1 = calculate_race_pace(laps, driver_1)
    stats_2 = calculate_race_pace(laps, driver_2)

    median_diff = None
    if stats_1["median_lap_time_s"] is not None and stats_2["median_lap_time_s"] is not None:
        median_diff = stats_1["median_lap_time_s"] - stats_2["median_lap_time_s"]

    mean_diff = None
    if stats_1["mean_lap_time_s"] is not None and stats_2["mean_lap_time_s"] is not None:
        mean_diff = stats_1["mean_lap_time_s"] - stats_2["mean_lap_time_s"]

    return {
        "driver_1": driver_1,
        "driver_2": driver_2,
        "median_pace_difference_s": median_diff,
        "mean_pace_difference_s": mean_diff,
        "usable_laps_driver_1": stats_1["usable_laps"],
        "usable_laps_driver_2": stats_2["usable_laps"],
    }
