"""Structured, deterministic persistence of analysis results to JSON.

This is the one place raw FastF1 Session/Laps objects get turned into
plain, JSON-serializable dicts for storage. It is pure assembly - every
number in the output comes from an existing saif1.analysis function; this
module adds no new analytical logic of its own.

Format decision (JSON, not SQLite/Parquet/a database): see README.md
"Persistence" section for the full reasoning. In short - the result is
naturally nested (session -> drivers -> stints/pace/exclusions), matches
JSON's shape directly, needs no schema migrations, is human-readable for a
public portfolio repo, and needs no new runtime dependency. SQLite is the
natural next step once there's real cross-race querying to justify it;
that need doesn't exist yet.

Raw FastF1 lap/telemetry data is never written here - only the outputs of
saif1.analysis functions (pace stats, stint summaries, exclusion counts,
etc). Raw data stays in the FastF1 cache (data/cache/), which this layer
never touches.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import fastf1
import pandas as pd
from fastf1.core import Session

from saif1.analysis.pace import calculate_green_flag_pace, calculate_race_pace
from saif1.analysis.quality import POLICY_DEFINITIONS, summarize_exclusions_by_policy, summarize_track_conditions
from saif1.analysis.strategy import extract_pit_stops, position_changes
from saif1.analysis.stints import extract_stints
from saif1.analysis.tyres import compound_performance, stint_degradation
from saif1.config import KNOWN_TYRE_COMPOUNDS, PROJECT_ROOT, SessionRequest
from saif1.exceptions import DriverNotFoundError

logger = logging.getLogger(__name__)

# schema_version: structural JSON shape. methodology_version: analytical
# logic/policy version. Bumped together here because both changed -
# lap_exclusions gained excluded_laps_detail (multi-label attribution),
# and compound validation/pit_stops/degradation logic changed.
SCHEMA_VERSION = "1.1"
METHODOLOGY_VERSION = "1.5.1"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "data" / "results"

# If unrecognized-compound laps make up at least this fraction of either
# the whole session or a single driver's own laps, log a warning
# unprompted - the unrecognized_compound_laps field only helps a reader
# who thinks to check it; a significant miss must announce itself.
_SESSION_UNRECOGNIZED_COMPOUND_WARNING_THRESHOLD = 0.05
_DRIVER_UNRECOGNIZED_COMPOUND_WARNING_THRESHOLD = 0.20


def _slugify(text: str) -> str:
    """Transliterate to ASCII (not strip) before slugifying, so an accented
    event name degrades gracefully - "São Paulo Grand Prix" becomes
    "sao-paulo-grand-prix", not "s-o-paulo-grand-prix". NFKD decomposition
    splits an accented character into its base letter plus a combining
    mark; encoding to ASCII with errors dropped then discards only the
    mark, keeping the base letter.

    This function determines part of a persisted result's filename (see
    result_filename below) - changing it changes what filename an event
    maps to. A change here requires regenerating and deleting the old
    file for any affected event, not leaving both on disk - see
    test_result_filename_is_stable_for_known_events for the regression
    net against exactly that.
    """
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = text.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _to_int_or_none(value) -> int | None:
    return int(value) if pd.notna(value) else None


def _build_provenance(request: SessionRequest, round_number: int) -> dict:
    return {
        "data_source": "FastF1",
        "fastf1_version": fastf1.__version__,
        "saif1_methodology_version": METHODOLOGY_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "session_identifier": f"{request.year}-{round_number:02d}-{request.session_type}",
    }


def _build_session_metadata(session: Session, request: SessionRequest) -> dict:
    event = session.event
    round_number = int(event["RoundNumber"])
    event_date = event.get("EventDate")
    return {
        "year": request.year,
        "event_name": event["EventName"],
        "round_number": round_number,
        "session_type": request.session_type,
        "location": event.get("Location", ""),
        "country": event.get("Country", ""),
        "event_date": event_date.date().isoformat() if pd.notna(event_date) else None,
        "session_date": session.date.isoformat() if pd.notna(session.date) else None,
    }, round_number


def _build_drivers(session: Session) -> list[dict]:
    """drivers[] schema - see README "Persisted result schema" for the
    FastF1 source field of each key. Missing GridPosition/Position are
    explicit `null`, never silently defaulted.
    """
    drivers = []
    for _, row in session.results.iterrows():
        drivers.append(
            {
                "driver": row.get("Abbreviation"),
                "driver_number": str(row.get("DriverNumber")),
                "full_name": row.get("FullName"),
                "team": row.get("TeamName"),
                "grid_position": _to_int_or_none(row.get("GridPosition")),
                "finish_position": _to_int_or_none(row.get("Position")),
                "status": row.get("Status"),
            }
        )
    return drivers


def _build_race_pace(laps, driver_codes: list[str]) -> dict:
    representative, green_flag = [], []
    for driver in driver_codes:
        try:
            representative.append(calculate_race_pace(laps, driver))
        except DriverNotFoundError:
            continue  # driver never completed a lap (e.g. did not start)
        try:
            green_flag.append(calculate_green_flag_pace(laps, driver))
        except DriverNotFoundError:
            continue
    return {"representative_race_pace": representative, "green_flag_pace": green_flag}


def _build_tyre_degradation(laps, stints: list[dict]) -> list[dict]:
    results = []
    for stint in stints:
        stint_laps = laps.pick_drivers([stint["driver"]])
        stint_laps = stint_laps[stint_laps["Stint"] == stint["stint_number"]]
        degradation = stint_degradation(stint_laps)
        results.append(
            {
                "driver": stint["driver"],
                "stint_number": stint["stint_number"],
                "compound": stint["compound"],
                "slope_s_per_lap": degradation["slope_s_per_lap"],
                "usable_laps": degradation["usable_laps"],
            }
        )
    return results


def _build_unrecognized_compound_summary(laps) -> dict:
    """Session-wide count of laps whose Compound value is present but not
    in KNOWN_TYRE_COMPOUNDS at all (e.g. the literal string "None",
    observed in real 2023 Canadian GP data) - genuinely missing (NaN)
    values are not counted here, and neither are FastF1's own legitimate
    "UNKNOWN"/"TEST-UNKNOWN" values (see config.normalize_compound). Never
    silently dropped from the output; if the rate is high enough to
    suggest a systemic problem rather than a one-off gap, logs a warning
    unprompted rather than relying on someone reading this field.
    """
    unrecognized = laps[laps["Compound"].notna() & ~laps["Compound"].isin(KNOWN_TYRE_COMPOUNDS)]

    by_driver: dict[str, list[int]] = {}
    for driver, group in unrecognized.groupby("Driver"):
        lap_numbers = sorted(int(n) for n in group["LapNumber"].dropna().tolist())
        if lap_numbers:
            by_driver[driver] = lap_numbers

    total_laps = len(laps)
    count = len(unrecognized)

    if total_laps and count / total_laps >= _SESSION_UNRECOGNIZED_COMPOUND_WARNING_THRESHOLD:
        logger.warning(
            "%d/%d laps (%.1f%%) in this session have an unrecognized Compound "
            "value - compound_performance and stint/pit-stop compound labeling "
            "may be significantly incomplete. Affected drivers: %s",
            count, total_laps, 100 * count / total_laps, sorted(by_driver.keys()),
        )
    for driver, lap_numbers in by_driver.items():
        driver_total = len(laps[laps["Driver"] == driver])
        if driver_total and len(lap_numbers) / driver_total >= _DRIVER_UNRECOGNIZED_COMPOUND_WARNING_THRESHOLD:
            logger.warning(
                "%s: %d/%d of their own laps (%.1f%%) have an unrecognized "
                "Compound value.",
                driver, len(lap_numbers), driver_total, 100 * len(lap_numbers) / driver_total,
            )

    return {"count": count, "by_driver": by_driver}


def _build_lap_exclusions(laps, driver_codes: list[str]) -> list[dict]:
    results = []
    for driver in driver_codes:
        driver_laps = laps.pick_drivers([driver])
        summary = summarize_exclusions_by_policy(driver_laps)
        results.append({"driver": driver, **summary})
    return results


def build_session_result(session: Session, request: SessionRequest) -> dict:
    """Assemble the full persisted-result dict for one session.

    Built for every driver present in session.results, independent of any
    display/CLI driver filter - this is meant to be a complete, reusable
    dataset for future consumers (API, frontend, agent), not just what one
    CLI invocation chose to print.

    Args:
        session: A loaded fastf1.core.Session (see data.loader.load_session).
        request: The SessionRequest that produced it (year/event/session_type).

    Returns:
        A JSON-serializable dict. See README.md "Persisted result schema"
        for the full shape.
    """
    laps = session.laps
    session_meta, round_number = _build_session_metadata(session, request)
    driver_codes = [d for d in session.results["Abbreviation"].tolist() if d]

    stints = extract_stints(laps)

    return {
        "schema_version": SCHEMA_VERSION,
        "provenance": _build_provenance(request, round_number),
        "session": session_meta,
        "drivers": _build_drivers(session),
        "race_pace": _build_race_pace(laps, driver_codes),
        "stints": stints,
        "tyre_degradation": _build_tyre_degradation(laps, stints),
        "compound_performance": compound_performance(laps),
        "pit_stops": extract_pit_stops(laps),
        "position_changes": position_changes(session),
        "lap_exclusions": _build_lap_exclusions(laps, driver_codes),
        "track_conditions": summarize_track_conditions(laps),
        "unrecognized_compound_laps": _build_unrecognized_compound_summary(laps),
        "quality_policy_definitions": dict(POLICY_DEFINITIONS),
    }


def result_filename(result: dict) -> str:
    session_meta = result["session"]
    slug = _slugify(session_meta["event_name"])
    return (
        f"{session_meta['year']}_{session_meta['round_number']:02d}_"
        f"{slug}_{session_meta['session_type']}.json"
    )


def save_result(result: dict, output_dir: Path = DEFAULT_RESULTS_DIR) -> Path:
    """Write `result` to a deterministically-named JSON file under
    `output_dir`, overwriting any existing file for the same session (see
    README for why regeneration overwrites in place rather than
    versioning filenames).

    `allow_nan=False` is deliberate: Python's `json` module otherwise
    writes a bare `NaN` token for a float NaN, which is invalid per strict
    RFC 8259 JSON (Python allows it as a non-standard extension, but a
    browser's `JSON.parse` - directly relevant to the planned frontend/API
    - rejects it outright). If a value that should have been explicitly
    normalized to `None` upstream (see the audit in the Phase 1.5 review
    report) ever reaches this call as a raw NaN instead, this raises
    `ValueError` immediately, at the moment the bad value appears, rather
    than silently writing a corrupt file that only breaks later, in a
    different program, long after the run that produced it.

    Returns:
        The path written to.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    path = output_dir / result_filename(result)
    path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    logger.info("Saved persisted result to %s", path)
    return path
