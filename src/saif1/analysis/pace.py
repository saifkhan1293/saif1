"""Race pace calculations: representative lap times per driver, and
driver-to-driver pace comparisons.

Median is used as the primary representative-pace statistic rather than
mean, since it is more robust to outlier laps (traffic, minor mistakes)
that survive the quality filter but still aren't representative of true
pace.

Two named pace policies are provided (see saif1.analysis.quality for the
full definitions and saif1.analysis.quality.POLICY_DEFINITIONS for the
canonical prose descriptions) - and they are NOT two equally-valid
alternatives to pick between:

- calculate_race_pace() - built on quality.representative_race_pace_laps.
  Excludes Safety Car / VSC / red-flag laps, keeps yellow-flagged laps.
  This is THE ANSWER to "how fast was this driver" - the default,
  general-purpose pace metric, and the one any report or comparison
  should lead with.
- calculate_green_flag_pace() - built on quality.green_flag_laps.
  Additionally excludes any yellow-flagged lap. This is a SENSITIVITY
  CHECK on the answer above, not a competing answer: "does this pace gap
  survive the stricter policy too?" A season-scale check (2024, 33
  persisted sessions) found representative_race_pace and green_flag_pace
  identical in 42.4% of sessions - in practice, once laps are already
  excluded for being deleted/inaccurate/pit-related, very little is left
  for a stray yellow flag to additionally remove. A session where the two
  agree is itself informative (yellow flags didn't distort the picture);
  a session where they diverge is a signal to look closer before trusting
  the headline number, not evidence that the headline number is wrong.
  Do not present both side by side as if choosing between them - that
  invites "which one is right?" when the honest framing is "one is the
  answer, the other is the check."

Every returned dict includes a "policy" field naming which one produced
it, so downstream consumers (persisted output, reports, an agent) never
have to guess which definition of "pace" a number represents.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from fastf1.core import Laps

from saif1.analysis.quality import green_flag_laps, representative_race_pace_laps
from saif1.exceptions import DriverNotFoundError

logger = logging.getLogger(__name__)


def lap_time_to_seconds(lap_time: pd.Timedelta) -> Optional[float]:
    """Convert a FastF1 LapTime (Timedelta) to seconds, or None if missing."""
    if pd.isna(lap_time):
        return None
    return lap_time.total_seconds()


def _pace_stats(laps: Laps, driver: str, *, policy_name: str, filter_fn) -> dict:
    driver_laps = laps.pick_drivers([driver])
    if driver_laps.empty:
        raise DriverNotFoundError(f"No lap data found for driver '{driver}'.")

    usable = filter_fn(driver_laps)
    seconds = usable["LapTime"].dropna().dt.total_seconds()

    return {
        "driver": driver,
        "policy": policy_name,
        "mean_lap_time_s": float(seconds.mean()) if not seconds.empty else None,
        "median_lap_time_s": float(seconds.median()) if not seconds.empty else None,
        "best_lap_time_s": float(seconds.min()) if not seconds.empty else None,
        "usable_laps": int(len(seconds)),
        "total_laps": int(len(driver_laps)),
    }


def calculate_race_pace(laps: Laps, driver: str) -> dict:
    """Calculate representative race-pace statistics for one driver,
    using the `representative_race_pace` policy (excludes Safety Car,
    VSC, and red-flag laps; keeps yellow-flagged laps).

    Args:
        laps: Full session Laps (e.g. session.laps).
        driver: Driver identifier as used by FastF1 (3-letter code, e.g.
            "VER", or driver number string).

    Returns:
        {
            "driver": str,
            "policy": "representative_race_pace",
            "mean_lap_time_s": float | None,
            "median_lap_time_s": float | None,
            "best_lap_time_s": float | None,
            "usable_laps": int,
            "total_laps": int,
        }

    Raises:
        DriverNotFoundError: If the driver has no laps in the session.
    """
    return _pace_stats(
        laps, driver, policy_name="representative_race_pace", filter_fn=representative_race_pace_laps
    )


def calculate_green_flag_pace(laps: Laps, driver: str) -> dict:
    """Calculate race-pace statistics for one driver using the stricter
    `green_flag_pace` policy: excludes any lap carrying a yellow-flag
    status anywhere on the lap, in addition to Safety Car/VSC/red-flag
    laps. See quality.green_flag_laps for why this is a deliberately
    strict policy rather than a claim that yellow-affected laps are
    inherently invalid.

    Same return shape as calculate_race_pace, with
    "policy": "green_flag_pace".

    Raises:
        DriverNotFoundError: If the driver has no laps in the session.
    """
    return _pace_stats(laps, driver, policy_name="green_flag_pace", filter_fn=green_flag_laps)


def compare_driver_pace(laps: Laps, driver_1: str, driver_2: str) -> dict:
    """Compare representative race pace (the `representative_race_pace`
    policy) between two drivers.

    Returns:
        {
            "driver_1": str,
            "driver_2": str,
            "policy": "representative_race_pace",
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
        "policy": "representative_race_pace",
        "median_pace_difference_s": median_diff,
        "mean_pace_difference_s": mean_diff,
        "usable_laps_driver_1": stats_1["usable_laps"],
        "usable_laps_driver_2": stats_2["usable_laps"],
    }
