"""Lap-level data quality filtering and named filtering policies.

F1 timing data contains laps that are not representative of true race
pace: in/out laps, laps deleted by race control (e.g. track limits), laps
FastF1 itself flags as inaccurate (missing or inconsistent sector
timing), and laps run under yellow flags, Safety Car, Virtual Safety Car,
or a red flag. None of this data is arbitrarily discarded - this module
provides one general filtering mechanism (`filter_usable_laps`) plus
three named, documented policies built on top of it
(`all_usable_laps`, `representative_race_pace_laps`, `green_flag_laps`),
each with an explicit, different definition of what "usable" means for a
particular kind of analysis. Every other analysis module picks one of
these three by name rather than reimplementing ad-hoc filters.
"""

from __future__ import annotations

import logging

import pandas as pd
from fastf1.core import Laps

logger = logging.getLogger(__name__)

# FastF1 track status codes and their meaning. A lap's TrackStatus column
# is a string that concatenates every code active at any point during the
# lap (e.g. "12" means status 1 and 2 both occurred), so membership checks
# below test each character rather than the whole string.
TRACK_STATUS_MEANINGS = {
    "1": "AllClear",
    "2": "Yellow",
    "3": "Unused",  # reserved by FastF1/F1, not currently emitted
    "4": "SafetyCar",
    "5": "Red",
    "6": "VSCDeployed",
    "7": "VSCEnding",
}

# Conditions severe enough to affect the entire lap's pace, not just a
# localized portion of it: full-course Safety Car, Virtual Safety Car
# (deployed or ending), and a red flag (session stopped outright).
SEVERE_TRACK_STATUS_CODES = {"4", "5", "6", "7"}

# All conditions that mean the lap wasn't run entirely under green-flag
# racing, including yellow flags (which are typically localized to one
# sector and often barely affect overall lap time).
NON_GREEN_TRACK_STATUS_CODES = {"2", *SEVERE_TRACK_STATUS_CODES}


def has_severe_track_condition(track_status: str) -> bool:
    """True if Safety Car, VSC, or a red flag was active at any point
    during the lap. Does not flag a plain yellow flag - see
    `is_green_flag_lap` for the stricter, all-flags check.
    """
    if not track_status:
        return False
    return any(code in SEVERE_TRACK_STATUS_CODES for code in str(track_status))


def is_green_flag_lap(track_status: str) -> bool:
    """True if no status code active during the lap indicates yellow
    flags, Safety Car, VSC, or a red flag - i.e. the lap was run entirely
    under green-flag racing conditions.
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
    exclude_severe_conditions: bool = False,
    green_flag_only: bool = False,
) -> Laps:
    """General-purpose lap quality filter. Prefer the named policies
    below (`all_usable_laps`, `representative_race_pace_laps`,
    `green_flag_laps`) in analysis code; this function is their shared
    mechanism and is kept flexible for cases those three don't cover.

    Args:
        laps: A FastF1 Laps object (e.g. session.laps or a driver subset).
        require_accurate: Drop laps where FastF1's IsAccurate flag is
            False (laps with missing/inconsistent sector timing).
        exclude_pit_laps: Drop in-laps and out-laps, which are slower for
            reasons unrelated to race pace.
        exclude_deleted: Drop laps deleted by race control (e.g. track
            limits) - these did not count for official timing.
        exclude_severe_conditions: Drop laps run under Safety Car, VSC, or
            a red flag - conditions that affect the whole lap. Off by
            default.
        green_flag_only: Drop laps run under *any* flag at all, including
            yellow. Off by default because a localized yellow flag often
            barely affects overall lap time, and excluding every
            yellow-flagged lap would remove a lot of otherwise-legitimate
            data. Its exclusion set is a strict superset of
            exclude_severe_conditions's (deleted/inaccurate/pit exclusions
            are unaffected either way), so when both are true only
            green_flag_only's stricter check is applied - the result is
            identical to green_flag_only alone.

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
    elif exclude_severe_conditions and "TrackStatus" in usable.columns:
        mask = ~usable["TrackStatus"].apply(has_severe_track_condition)
        usable = usable.loc[mask]

    dropped = len(laps) - len(usable)
    if dropped:
        logger.debug("filter_usable_laps: dropped %d/%d laps", dropped, len(laps))

    return usable


def all_usable_laps(laps: Laps) -> Laps:
    """Policy: every timed, non-pit, non-deleted, accurate lap - includes
    laps affected by yellow flags, Safety Car, and VSC.

    Use for analyses that need full structural lap coverage regardless of
    flag conditions: tyre stint extraction, pit stop extraction, position
    changes/progression. A stint's lap range or a pit stop's timing
    doesn't become invalid because a flag was out.
    """
    return filter_usable_laps(laps)


def representative_race_pace_laps(laps: Laps) -> Laps:
    """Policy: `all_usable_laps`, additionally excluding laps run under
    Safety Car, VSC, or a red flag. Yellow-flagged laps are kept.

    This is the default policy for race-pace metrics
    (`pace.calculate_race_pace`, `tyres.compound_performance`): SC/VSC/red
    conditions slow the entire lap by an amount unrelated to genuine
    driver/car pace, so including them would materially distort a
    "representative pace" statistic. A localized yellow flag is judged
    close enough to normal racing, and common enough, that excluding
    every yellow-affected lap by default would discard too much
    legitimate data for too little benefit - see `green_flag_laps` for
    the stricter alternative.
    """
    return filter_usable_laps(laps, exclude_severe_conditions=True)


def green_flag_laps(laps: Laps) -> Laps:
    """Policy: the strictest tier. Starting from `all_usable_laps` (which
    includes laps affected by any flag), this additionally excludes every
    lap that carries a yellow flag, Safety Car, VSC, or red flag status
    anywhere on the lap - i.e. only laps run entirely under green-flag
    conditions remain. This is a superset of what
    `representative_race_pace_laps` excludes (that policy already drops
    Safety Car/VSC/red flag laps; this one additionally drops
    yellow-flagged laps on top of that).

    This is a deliberately strict analytical policy, not a claim that
    every yellow-affected lap is inherently invalid - a yellow is often
    localized to one sector and may barely change overall lap time. It
    exists for cases where any flag interference at all should be
    excluded, even at the cost of a smaller usable sample: e.g.
    `tyres.stint_degradation`, where a single stint already has few data
    points and any non-green-flag noise disproportionately distorts a
    linear fit, or `pace.calculate_green_flag_pace` for callers who
    explicitly want the strictest possible pace comparison.
    """
    return filter_usable_laps(laps, green_flag_only=True)


# Single source of truth for human-readable policy descriptions. Anything
# that needs to describe these policies in prose (persisted JSON output,
# reports) must import and use this dict rather than writing its own copy -
# duplicated hand-written prose is exactly how the three docstrings above
# and this dict would silently drift apart over time. Keep this in sync
# with the docstrings on all_usable_laps/representative_race_pace_laps/
# green_flag_laps whenever either changes.
POLICY_DEFINITIONS = {
    "all_usable_laps": (
        "Excludes deleted, inaccurate, and pit in/out laps only. Includes "
        "laps affected by yellow flags, Safety Car, and VSC."
    ),
    "representative_race_pace": (
        "As all_usable_laps, additionally excludes laps run under Safety "
        "Car, VSC, or a red flag. Yellow-flagged laps are kept."
    ),
    "green_flag_pace": (
        "As all_usable_laps, additionally excludes any lap affected by a "
        "yellow flag, Safety Car, VSC, or red flag - only laps run "
        "entirely under green-flag conditions remain. A deliberately "
        "strict policy, not a claim that every yellow-affected lap is "
        "inherently invalid."
    ),
}


# --- Lap exclusion accounting -----------------------------------------
#
# The three policy functions above decide retained-vs-excluded by chaining
# FastF1's pick_*() methods and boolean TrackStatus masks. The functions
# below independently classify *why* a given lap would be excluded, for
# persisted, auditable output. Because this is a second implementation of
# overlapping logic, every consumer of this classification must be
# cross-checked against the real filter functions above in tests - see
# tests/test_quality.py's cross-check invariant tests. Do not treat
# agreement between this classifier and the real filters as guaranteed by
# construction; it is only guaranteed by testing.

# Precedence order for labeling an excluded lap with a single reason, first
# match wins. Structural reasons (deleted/pit/inaccurate) outrank flag
# conditions because a lap invalid for a structural reason is excluded
# regardless of what flag was active - labeling it by the flag instead
# would be misleading. pit_in/pit_out outrank inaccurate specifically
# because pit laps are very often *also* flagged inaccurate by FastF1 (the
# pit lane speed limit distorts sector timing); "pit_in"/"pit_out" is a far
# more meaningful label to a reader than "inaccurate" even though both are
# technically true. Flag conditions are ordered by severity: red flag (
# session stopped) > safety car > VSC > yellow (most localized).
EXCLUSION_PRECEDENCE = (
    "deleted",
    "pit_in",
    "pit_out",
    "inaccurate",
    "red_flag",
    "safety_car",
    "virtual_safety_car",
    "yellow_flag",
)

# Which exclusion-reason labels each named policy actually treats as
# "excluded". Must stay consistent with what filter_usable_laps() does for
# the corresponding policy call - this mapping is exactly what the
# cross-check tests verify.
_POLICY_EXCLUDED_REASONS = {
    "all_usable_laps": {"deleted", "pit_in", "pit_out", "inaccurate"},
    "representative_race_pace": {
        "deleted", "pit_in", "pit_out", "inaccurate",
        "red_flag", "safety_car", "virtual_safety_car",
    },
    "green_flag_pace": set(EXCLUSION_PRECEDENCE),
}


def classify_all_exclusion_reasons(lap_row: pd.Series) -> list[str]:
    """Every exclusion reason applicable to `lap_row`, in
    EXCLUSION_PRECEDENCE order - not just the highest-precedence one.

    A lap can be both e.g. under Safety Car *and* flagged inaccurate; this
    returns ["inaccurate", "safety_car"] for such a lap (precedence order),
    so no information about which conditions were genuinely present on
    this specific lap is lost. See classify_lap_exclusion_reason() for the
    single-label (first-only) version used for display/labeling.

    Missing columns are treated the same way filter_usable_laps() treats
    them (as "no exclusion from that check"), so this agrees with the real
    filter chain when optional data (e.g. TrackStatus) wasn't loaded.
    """
    reasons: list[str] = []

    if bool(lap_row.get("Deleted", False)):
        reasons.append("deleted")
    if pd.notna(lap_row.get("PitInTime")):
        reasons.append("pit_in")
    if pd.notna(lap_row.get("PitOutTime")):
        reasons.append("pit_out")
    if not bool(lap_row.get("IsAccurate", True)):
        reasons.append("inaccurate")

    track_status = str(lap_row.get("TrackStatus") or "")
    if "5" in track_status:
        reasons.append("red_flag")
    if "4" in track_status:
        reasons.append("safety_car")
    if "6" in track_status or "7" in track_status:
        reasons.append("virtual_safety_car")
    if "2" in track_status:
        reasons.append("yellow_flag")

    return reasons


def classify_lap_exclusion_reason(lap_row: pd.Series) -> str | None:
    """Single, highest-precedence reason `lap_row` would be excluded by at
    least the strictest policy (green_flag_pace), or None if the lap is
    entirely clean. A thin wrapper over classify_all_exclusion_reasons()
    for callers that only want the primary/display label - see that
    function if you need every applicable reason, not just the first.
    """
    reasons = classify_all_exclusion_reasons(lap_row)
    return reasons[0] if reasons else None


def summarize_exclusions_by_policy(driver_laps: Laps) -> dict:
    """Per-policy retained/excluded lap accounting for one driver's laps,
    built from a single multi-label classification pass over
    `driver_laps` (classify_all_exclusion_reasons).

    `excluded_by_reason` counts are **multi-label tallies**: a lap that is
    both under Safety Car *and* flagged inaccurate counts under *both* the
    "inaccurate" and "safety_car" buckets (for policies that exclude both
    reasons) - no condition genuinely present on a lap is masked by a
    higher-precedence one. Because of this, summing every reason bucket's
    count can legitimately exceed `excluded_laps` (one lap can be counted
    under more than one reason) - that sum is not a validity check.
    `excluded_laps_detail` carries the full picture per lap, including a
    `primary_reason` (the single highest-precedence label, via
    EXCLUSION_PRECEDENCE) for display purposes only.

    This still does NOT make `excluded_by_reason["safety_car"]` a complete
    census of laps run under Safety Car - a lap that FastF1 doesn't flag
    as inaccurate/pit/deleted AND was under Safety Car will correctly show
    up here, but this is still per-driver/per-lap, not a substitute for
    `summarize_track_conditions`'s session-level, field-wide view. In
    practice (see README), SC/VSC/red-flag-affected laps have so far
    always coincided with an independent inaccurate/pit flag too, so
    reading `track_conditions` for "did a Safety Car occur" remains the
    more reliable question to ask; this function now at least *can*
    reflect it per-driver when it's present.

    Returns:
        {
            "laps_recorded": int,  # lap rows present for this driver
                                    # before any filtering - see module
                                    # docs for what counts as a lap row
            "excluded_laps_detail": [
                {"lap_number": int, "reasons": [str, ...], "primary_reason": str},
                ...  # one entry per excluded lap, sorted by lap_number
            ],
            "policies": {
                "all_usable_laps": {
                    "retained_laps": int,
                    "excluded_laps": int,  # count of DISTINCT excluded laps
                    "excluded_by_reason": {
                        "deleted": {"count": int, "lap_numbers": [int, ...]},
                        ... one entry per EXCLUSION_PRECEDENCE reason,
                        ... multi-label tally, may double-count vs excluded_laps ...
                    },
                },
                "representative_race_pace": {...same shape...},
                "green_flag_pace": {...same shape...},
            },
        }

    Invariant (asserted in tests, not just by inspection): for every
    policy, retained_laps + excluded_laps == laps_recorded, where
    excluded_laps counts each excluded lap once regardless of how many
    reasons applied to it. This is now the only arithmetic invariant -
    the reason-bucket counts are allowed to sum to more than excluded_laps
    by design. The PRIMARY correctness check remains the cross-check
    against the real all_usable_laps/representative_race_pace_laps/
    green_flag_laps filter functions (see tests/test_quality.py), which
    this multi-label change does not affect: because the three policies'
    excluded-reason sets are each a prefix of EXCLUSION_PRECEDENCE, "is
    the primary (highest-precedence) reason in this policy's set" and "is
    any applicable reason in this policy's set" give identical
    retained/excluded results for every lap - verified by test, not just
    asserted here.
    """
    laps_recorded = len(driver_laps)

    excluded_laps_detail: list[dict] = []
    reason_tally: dict[str, dict] = {
        reason: {"count": 0, "lap_numbers": []} for reason in EXCLUSION_PRECEDENCE
    }

    if laps_recorded:
        for _, row in driver_laps.iterrows():
            reasons = classify_all_exclusion_reasons(row)
            if not reasons:
                continue

            lap_number = row.get("LapNumber")
            lap_number_int = int(lap_number) if pd.notna(lap_number) else None

            excluded_laps_detail.append(
                {"lap_number": lap_number_int, "reasons": reasons, "primary_reason": reasons[0]}
            )
            for reason in reasons:
                reason_tally[reason]["count"] += 1
                if lap_number_int is not None:
                    reason_tally[reason]["lap_numbers"].append(lap_number_int)

    excluded_laps_detail.sort(key=lambda d: (d["lap_number"] is None, d["lap_number"]))

    policies = {}
    for policy_name, excluded_reasons in _POLICY_EXCLUDED_REASONS.items():
        # Count matching ROWS in excluded_laps_detail directly (one entry
        # per originally-excluded row, already 1:1 with driver_laps rows -
        # see the iterrows() loop above), not a set of lap numbers: a set
        # would silently collapse/undercount any rows with a missing
        # LapNumber, since every such row's lap_number is None and sets
        # only keep one None.
        excluded_count = sum(
            1 for d in excluded_laps_detail if any(r in excluded_reasons for r in d["reasons"])
        )
        policies[policy_name] = {
            "retained_laps": laps_recorded - excluded_count,
            "excluded_laps": excluded_count,
            "excluded_by_reason": {
                reason: (
                    reason_tally[reason]
                    if reason in excluded_reasons
                    else {"count": 0, "lap_numbers": []}
                )
                for reason in EXCLUSION_PRECEDENCE
            },
        }

    return {
        "laps_recorded": laps_recorded,
        "excluded_laps_detail": excluded_laps_detail,
        "policies": policies,
    }


# Track-status codes summarized at session level (a Safety Car or red flag
# is a field-wide condition, not something specific to one driver).
_TRACK_CONDITION_LABELS = {
    "5": "red_flag",
    "4": "safety_car",
    "2": "yellow_flag",
}


def summarize_track_conditions(laps: Laps) -> list[dict]:
    """Session-level (not per-driver) lap ranges during which Safety Car,
    VSC, red flag, or yellow flag conditions were active anywhere in the
    field.

    IMPORTANT - this is a UNION ACROSS ALL DRIVERS, not a claim about any
    individual driver's laps. It's built by taking, for each lap number,
    the union of every driver's own TrackStatus value for that lap number
    - so a condition can appear here for lap N even if a *specific*
    driver's own lap N never carried that status code, simply because
    another driver's lap N (or N's boundary, given drivers don't cross the
    line at the same wall-clock time) did. Concretely observed: at the
    2023 Canadian GP, this reports VSC active for lap range 7-8, but
    VER's own TrackStatus for lap 7 is "12" (yellow only, no VSC code) -
    both facts are correct simultaneously, because they're answering
    different questions ("was VSC active anywhere in the field during lap
    7-8" vs. "was VER's own lap 7 run under VSC"). Do not read an entry
    here as "every driver's lap in this range was under this condition" -
    for the per-driver, per-lap answer, use
    `summarize_exclusions_by_policy`'s `excluded_laps_detail[].reasons`
    instead (each entry lists every condition genuinely present on that
    specific driver's specific lap, not just the highest-precedence one).

    This answers "was condition X present anywhere during lap range Y"
    completely at the field level - it does not lose information to
    precedence masking the way a single-label per-driver classification
    would.

    Args:
        laps: Full session Laps (e.g. session.laps, all drivers).

    Returns:
        List of {"condition": str, "code": str, "start_lap": int,
        "end_lap": int}, sorted by start_lap. Empty if TrackStatus/
        LapNumber aren't available or no such condition occurred.
    """
    if laps.empty or "TrackStatus" not in laps.columns or "LapNumber" not in laps.columns:
        return []

    codes_by_lap: dict[int, set[str]] = {}
    for _, row in laps.iterrows():
        lap_number = row.get("LapNumber")
        track_status = row.get("TrackStatus")
        if pd.isna(lap_number) or not track_status:
            continue
        codes_by_lap.setdefault(int(lap_number), set()).update(str(track_status))

    summary: list[dict] = []
    for code, label in _TRACK_CONDITION_LABELS.items():
        lap_numbers = sorted(lap for lap, codes in codes_by_lap.items() if code in codes)
        summary.extend(_lap_ranges(lap_numbers, label, code))

    # VSC combines "deployed" (6) and "ending" (7) into one condition.
    vsc_laps = sorted(lap for lap, codes in codes_by_lap.items() if codes & {"6", "7"})
    summary.extend(_lap_ranges(vsc_laps, "virtual_safety_car", "6/7"))

    summary.sort(key=lambda item: item["start_lap"])
    return summary


def _lap_ranges(lap_numbers: list[int], label: str, code: str) -> list[dict]:
    """Collapse a sorted list of lap numbers into contiguous ranges."""
    if not lap_numbers:
        return []

    ranges = []
    start = prev = lap_numbers[0]
    for lap in lap_numbers[1:]:
        if lap == prev + 1:
            prev = lap
            continue
        ranges.append({"condition": label, "code": code, "start_lap": start, "end_lap": prev})
        start = prev = lap
    ranges.append({"condition": label, "code": code, "start_lap": start, "end_lap": prev})
    return ranges
