"""Tyre degradation and compound performance analysis.

Degradation is estimated with a simple linear fit (lap time vs. tyre age)
per stint - a deterministic calculation, not a predictive model.

IMPORTANT LIMITATION: the fitted slope is a *net* lap-time trend, not pure
tyre degradation. Over a stint, lap time is simultaneously pulled in two
opposite directions by effects this fit cannot separate:
- Tyre wear tends to slow laps down as the stint progresses.
- Fuel burn-off tends to speed laps up as the stint progresses (a lighter
  car is faster), working directly against the wear signal.
- Track evolution (rubber laid down, changing temperature) can move lap
  times in either direction independently of both.
A shallow or even negative slope does not necessarily mean the tyre wasn't
degrading - it may mean fuel burn-off outweighed wear over that stint.
Read the slope as "net trend direction and rough magnitude", never as a
physical tyre-wear rate.

Uses the `green_flag_laps` policy (see saif1.analysis.quality) rather than
the looser `representative_race_pace_laps`: a single stint already has few
data points for a linear fit, so any flag-affected lap - even a localized
yellow - is disproportionate noise relative to the small underlying signal
being measured. compound_performance(), by contrast, aggregates across a
whole session and uses `representative_race_pace_laps`, consistent with
saif1.analysis.pace.calculate_race_pace().
"""

from __future__ import annotations

import numpy as np
from fastf1.core import Laps

from saif1.analysis.quality import green_flag_laps, representative_race_pace_laps
from saif1.config import RANKABLE_COMPOUNDS

MIN_LAPS_FOR_DEGRADATION_FIT = 3


def stint_degradation(stint_laps: Laps) -> dict:
    """Estimate the net lap-time trend across a single stint via linear
    regression of lap time against tyre age, using the `green_flag_laps`
    policy. See the module docstring for why this is net-of-fuel-burn-off,
    not pure tyre degradation.

    Args:
        stint_laps: Laps belonging to a single driver's single stint.

    Returns:
        {
            "slope_s_per_lap": float | None,  # positive = net getting slower
            "usable_laps": int,
        }
        slope_s_per_lap is None when fewer than
        MIN_LAPS_FOR_DEGRADATION_FIT usable laps are available, since a
        linear fit isn't meaningful on that few points.
    """
    usable = green_flag_laps(stint_laps)
    valid = usable.dropna(subset=["LapTime", "TyreLife"])

    if len(valid) < MIN_LAPS_FOR_DEGRADATION_FIT:
        return {"slope_s_per_lap": None, "usable_laps": int(len(valid))}

    x = valid["TyreLife"].to_numpy(dtype=float)
    y = valid["LapTime"].dt.total_seconds().to_numpy(dtype=float)
    slope, _intercept = np.polyfit(x, y, 1)

    return {"slope_s_per_lap": float(slope), "usable_laps": int(len(valid))}


def compound_performance(laps: Laps) -> list[dict]:
    """Summarize representative pace per tyre compound across a session,
    using the `representative_race_pace` policy (excludes Safety Car/VSC/
    red-flag laps; keeps yellow-flagged laps) - consistent with
    saif1.analysis.pace.calculate_race_pace().

    Only ranks real, physical compounds (config.RANKABLE_COMPOUNDS) -
    laps with a missing, FastF1-"UNKNOWN", or genuinely unrecognized
    Compound value are excluded from this ranking (see
    persistence.build_session_result for where the session-wide count of
    unrecognized-compound laps is reported instead of silently dropped;
    "UNKNOWN"/missing laps are not "unrecognized" - they're a legitimate,
    lower-frequency FastF1 state and aren't separately counted here).

    Returns:
        List of dicts sorted by median pace, fastest first:
        {
            "compound": str,
            "median_lap_time_s": float,
            "usable_laps": int,
        }
    """
    usable = representative_race_pace_laps(laps)
    results: list[dict] = []

    for compound, group in usable.groupby("Compound"):
        if compound not in RANKABLE_COMPOUNDS:
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
