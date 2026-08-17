"""Lap-level data quality filtering.

F1 timing data contains laps that are not representative of true race
pace: in/out laps, safety car / VSC periods, laps deleted by race control
(e.g. track limits), and laps FastF1 itself flags as inaccurate (missing
or inconsistent sector timing). This module centralizes that filtering so
every analysis function applies the same, documented rules instead of each
reimplementing ad-hoc filters.
"""

from __future__ import annotations

import logging

from fastf1.core import Laps

logger = logging.getLogger(__name__)

# Track status codes that indicate conditions which distort pace and
# shouldn't be compared to green-flag racing.
# Per FastF1: 1=AllClear, 2=Yellow, 4=SafetyCar, 5=Red, 6=VSC, 7=VSCEnding.
NON_GREEN_TRACK_STATUS_CODES = {"2", "4", "5", "6", "7"}


def is_green_flag_lap(track_status: str) -> bool:
    """True if no status code active during the lap indicates yellow
    flags, safety car, VSC, or a red flag.

    FastF1 concatenates codes when multiple statuses applied during a
    single lap (e.g. "12" means status 1 and 2 both occurred), so this
    checks each character rather than the whole string.
    """
    if not track_status:
        return True
    return not any(code in NON_GREEN_TRACK_STATUS_CODES for code in str(track_status))


def filter_usable_laps(
    laps: Laps,
    *,
    require_accurate: bool = True,
    exclude_pit_laps: bool = True,
    exclude_deleted: bool = True,
    green_flag_only: bool = False,
) -> Laps:
    """Filter laps down to those usable for race-pace analysis.

    Args:
        laps: A FastF1 Laps object (e.g. session.laps or a driver subset).
        require_accurate: Drop laps where FastF1's IsAccurate flag is
            False (laps with missing/inconsistent sector timing).
        exclude_pit_laps: Drop in-laps and out-laps, which are slower for
            reasons unrelated to race pace.
        exclude_deleted: Drop laps deleted by race control (e.g. track
            limits) - these did not count for official timing.
        green_flag_only: Additionally drop laps run under yellow, safety
            car, VSC, or red flag conditions. Off by default because it
            also removes legitimate slow-but-valid laps (e.g. traffic);
            enable when pure green-flag pace is required.

    Returns:
        A filtered Laps object. The input is never mutated.
    """
    if laps.empty:
        # FastF1's pick_*() methods boolean-index the frame (e.g.
        # self[~self['Deleted']]); on a zero-row frame this collapses the
        # result to zero columns as well, which breaks every subsequent
        # pick_*() call in the chain. Short-circuit instead of relying on
        # that chain to handle an empty frame correctly.
        return laps

    usable = laps

    if exclude_deleted and "Deleted" in usable.columns:
        usable = usable.pick_not_deleted()

    if require_accurate and "IsAccurate" in usable.columns:
        usable = usable.pick_accurate()

    if exclude_pit_laps:
        usable = usable.pick_wo_box()

    if green_flag_only and "TrackStatus" in usable.columns:
        mask = usable["TrackStatus"].apply(is_green_flag_lap)
        usable = usable.loc[mask]

    dropped = len(laps) - len(usable)
    if dropped:
        logger.debug("filter_usable_laps: dropped %d/%d laps", dropped, len(laps))

    return usable
