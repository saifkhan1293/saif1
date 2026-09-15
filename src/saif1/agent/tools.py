"""Framework-neutral tool surface over persisted SAIF1 results.

See docs/agent_tools.md for the full specification (every tool's inputs,
return shape, and the refusal contract they all follow) - this module
implements exactly what that document describes and should not drift from
it. Every tool here is a thin wrapper over an already-existing,
already-tested function or persisted field; no new analysis logic is
introduced in this module.

Reads ONLY persisted JSON (via saif1.aggregation), never a live FastF1
load. Same import discipline as aggregation.py, for the same reason and
more urgently: an agent calling these tools must never transitively
require fastf1 to be installed. See test_agent_tools.py's blocked-import
test.

No agent, no LLM, no framework coupling. TOOLS below is a plain dict of
plain dataclasses - a future adapter to a specific agent SDK's tool format
is a separate, later layer, not this one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from saif1.aggregation import SeasonIndex, load_season_index, teammate_pace_head_to_head
from saif1.config import VALID_SESSION_TYPES

# Fixed, small set of "no data" reason codes - see docs/agent_tools.md
# "The refusal contract" for exactly what each one covers and why.
#
# driver_not_in_session and driver_did_not_run were originally one code
# (driver_not_found), collapsed. Split after review found a real 2024
# case that made the collapse actively misleading: British GP round 12,
# Gasly (GAS) is on the grid in P19 with status "Did not start" - a real,
# reportable fact - but a query for his race pace and a query for a
# nonsense driver code ("ZZZ") returned byte-identical no_data results.
# "Gasly did not start" and "ZZZ is not a driver" are different facts an
# agent needs to tell apart, not the same refusal.
NO_DATA_REASONS = {
    "session_not_persisted": "No persisted result exists for this year/round_number/session_type.",
    "season_not_persisted": "No persisted results exist for this year/session_type at all.",
    "driver_not_in_session": "The driver code does not appear in this session's roster at all.",
    "driver_did_not_run": "The driver is in this session's roster but has zero laps recorded (e.g. did not start).",
}

_RACE_PACE_POLICIES = {"representative_race_pace", "green_flag_pace"}


@dataclass(frozen=True)
class ToolResult:
    """Every tool function returns this - never a bare value, never prose.

    status="ok": `data` holds the answer. May legitimately be an empty
        list, or contain a real zero/None field within it (e.g. a driver
        with usable_laps=0) - those are valid answers, not missing data.
    status="no_data": the query was well-formed but has no answer. `data`
        is always None; `reason` is one of NO_DATA_REASONS, never prose.

    Invalid input (e.g. an unrecognized session_type) raises ValueError
    instead of returning a ToolResult - a caller contract violation, not
    a legitimate "no answer" business outcome.
    """

    status: Literal["ok", "no_data"]
    data: Any = None
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.status == "no_data":
            if self.reason not in NO_DATA_REASONS:
                raise ValueError(
                    f"no_data reason must be one of {sorted(NO_DATA_REASONS)}, got {self.reason!r}"
                )
            if self.data is not None:
                raise ValueError("a no_data result must not carry data")
        elif self.reason is not None:
            raise ValueError("reason is only meaningful when status='no_data'")


def _validate_session_type(session_type: str) -> None:
    if session_type not in VALID_SESSION_TYPES:
        raise ValueError(
            f"Unknown session_type {session_type!r}. Expected one of {sorted(VALID_SESSION_TYPES)}"
        )


def _find_session(year: int, round_number: int, session_type: str) -> Optional[dict]:
    _validate_session_type(session_type)
    index = load_season_index(year, session_type)
    for result in index.results:
        if result["session"]["round_number"] == round_number:
            return result
    return None


def _classify_driver(result: dict, driver: str) -> Literal["not_in_session", "did_not_run", "ran"]:
    """Classify `driver` against one already-found session's roster and
    lap record, for the three-way distinction driver-filtered tools need:

    - "not_in_session": the driver code isn't on this session's roster at
      all (wrong code, or the wrong session).
    - "did_not_run": on the roster, but laps_recorded == 0 for them (a
      real fact - e.g. Gasly, British GP round 12, grid P19, status "Did
      not start"). Every roster driver has a lap_exclusions entry (same
      source driver list as `drivers[]` - see persistence.py), so this
      never has to guess.
    - "ran": on the roster with laps_recorded > 0. A driver-filtered tool
      finding zero matching entries for a driver classified "ran" (e.g.
      Sargeant, Canadian GP round 9: 24 laps recorded, retired without
      ever pitting) must return status="ok" with an empty list - that's
      a real, valid answer ("no pit stops happened"), never "no_data".
    """
    if not any(d["driver"] == driver for d in result["drivers"]):
        return "not_in_session"
    exclusions_entry = next((e for e in result["lap_exclusions"] if e["driver"] == driver), None)
    if exclusions_entry is not None and exclusions_entry["laps_recorded"] == 0:
        return "did_not_run"
    return "ran"


def list_available_sessions(year: int, session_type: Optional[str] = None) -> ToolResult:
    """Every persisted session for `year`, optionally filtered to one
    session_type. Always status="ok" - see docs/agent_tools.md.
    """
    if session_type is not None:
        _validate_session_type(session_type)
        session_types = (session_type,)
    else:
        session_types = tuple(sorted(VALID_SESSION_TYPES))

    sessions: list[dict] = []
    for st in session_types:
        index = load_season_index(year, st)
        for result in index.results:
            s = result["session"]
            sessions.append(
                {
                    "year": s["year"],
                    "round_number": s["round_number"],
                    "event_name": s["event_name"],
                    "session_type": s["session_type"],
                }
            )

    sessions.sort(key=lambda s: (s["round_number"], s["session_type"]))
    return ToolResult(status="ok", data=sessions)


def get_session_summary(year: int, round_number: int, session_type: str) -> ToolResult:
    """Roster, classification, and track conditions for one session."""
    result = _find_session(year, round_number, session_type)
    if result is None:
        return ToolResult(status="no_data", reason="session_not_persisted")
    return ToolResult(
        status="ok",
        data={
            "session": result["session"],
            "drivers": result["drivers"],
            "track_conditions": result["track_conditions"],
            "position_changes": result["position_changes"],
        },
    )


def get_race_pace(
    year: int,
    round_number: int,
    session_type: str,
    policy: str = "representative_race_pace",
    driver: Optional[str] = None,
) -> ToolResult:
    """Race pace for one or every driver, under an explicitly-named
    policy. Defaults to representative_race_pace (the answer), not
    green_flag_pace (the sensitivity check) - see README.
    """
    if policy not in _RACE_PACE_POLICIES:
        raise ValueError(f"Unknown policy {policy!r}. Expected one of {sorted(_RACE_PACE_POLICIES)}")

    result = _find_session(year, round_number, session_type)
    if result is None:
        return ToolResult(status="no_data", reason="session_not_persisted")

    pace_list = result["race_pace"][policy]
    if driver is None:
        return ToolResult(status="ok", data=pace_list)

    entry = next((p for p in pace_list if p["driver"] == driver), None)
    if entry is not None:
        return ToolResult(status="ok", data=entry)

    # Absent from the pace list. persistence.py only omits a roster
    # driver from race_pace when they have zero laps at all (see
    # persistence._build_race_pace catching DriverNotFoundError) - so
    # "ran" can't actually occur here, but _classify_driver is still the
    # single source of truth for the not_in_session/did_not_run split
    # rather than duplicating that logic.
    classification = _classify_driver(result, driver)
    if classification == "not_in_session":
        return ToolResult(status="no_data", reason="driver_not_in_session")
    return ToolResult(status="no_data", reason="driver_did_not_run")


def _get_driver_filtered_field(
    year: int, round_number: int, session_type: str, field_name: str, driver: Optional[str]
) -> ToolResult:
    """Shared implementation for get_stints/get_tyre_degradation/
    get_pit_stops - all three are "filter a persisted list by driver,
    optionally" with identical refusal behavior.

    Unlike get_race_pace, a driver who genuinely ran can have zero
    entries here for a real reason (e.g. Sargeant, Canadian GP round 9:
    24 laps recorded, retired without ever pitting - zero pit_stops is
    the correct, complete answer for him, not a refusal). So an empty
    match list is only "no_data" when _classify_driver says the driver
    didn't run at all or isn't in the session - a "ran" classification
    with zero matches is status="ok", data=[].
    """
    result = _find_session(year, round_number, session_type)
    if result is None:
        return ToolResult(status="no_data", reason="session_not_persisted")

    items = result[field_name]
    if driver is None:
        return ToolResult(status="ok", data=items)

    matching = [item for item in items if item["driver"] == driver]
    if matching:
        return ToolResult(status="ok", data=matching)

    classification = _classify_driver(result, driver)
    if classification == "not_in_session":
        return ToolResult(status="no_data", reason="driver_not_in_session")
    if classification == "did_not_run":
        return ToolResult(status="no_data", reason="driver_did_not_run")
    return ToolResult(status="ok", data=[])  # ran, genuinely zero of this category


def get_stints(
    year: int, round_number: int, session_type: str, driver: Optional[str] = None
) -> ToolResult:
    """Tyre stint history for one or every driver."""
    return _get_driver_filtered_field(year, round_number, session_type, "stints", driver)


def get_tyre_degradation(
    year: int, round_number: int, session_type: str, driver: Optional[str] = None
) -> ToolResult:
    """Per-stint degradation slope for one or every driver. Net trend
    (tyre wear confounded with fuel burn-off), not pure degradation - see
    README; this tool surfaces the number as already computed.
    """
    return _get_driver_filtered_field(year, round_number, session_type, "tyre_degradation", driver)


def get_pit_stops(
    year: int, round_number: int, session_type: str, driver: Optional[str] = None
) -> ToolResult:
    """Pit stops for one or every driver."""
    return _get_driver_filtered_field(year, round_number, session_type, "pit_stops", driver)


def get_compound_performance(year: int, round_number: int, session_type: str) -> ToolResult:
    """Session-wide median pace per tyre compound. No driver parameter -
    inherently session-wide. A compound nobody ran simply doesn't appear
    in the list; that's `ok` with a shorter list, not `no_data`.
    """
    result = _find_session(year, round_number, session_type)
    if result is None:
        return ToolResult(status="no_data", reason="session_not_persisted")
    return ToolResult(status="ok", data=result["compound_performance"])


def get_lap_exclusions(year: int, round_number: int, session_type: str, driver: str) -> ToolResult:
    """Full exclusion accounting for one driver - all three quality
    policies, multi-label per-lap detail. `driver` is required, unlike
    the other per-driver tools - this one is only meaningful for one
    driver at a time.

    Note: unlike the other driver-filtered tools, there is no separate
    "did not run" no_data case here - every roster driver has a
    lap_exclusions entry regardless of whether they ever set a lap time
    (a did-not-start driver's entry simply shows laps_recorded=0, a real
    ok answer - see Gasly, British GP round 12). Absence here can only
    mean the driver isn't on this session's roster at all.
    """
    result = _find_session(year, round_number, session_type)
    if result is None:
        return ToolResult(status="no_data", reason="session_not_persisted")

    entry = next((e for e in result["lap_exclusions"] if e["driver"] == driver), None)
    if entry is None:
        return ToolResult(status="no_data", reason="driver_not_in_session")
    return ToolResult(status="ok", data=entry)


def get_teammate_head_to_head(year: int, session_type: str = "R") -> ToolResult:
    """Season-long teammate representative_race_pace head-to-head - the
    one cross-session tool in this surface. Every caller presenting a
    result from this tool must attach the track-position/strategy
    confound caveat documented in the README - this tool does not repeat
    that text itself, to avoid a second copy drifting from the canonical
    one.
    """
    _validate_session_type(session_type)
    index: SeasonIndex = load_season_index(year, session_type)
    if len(index) == 0:
        return ToolResult(status="no_data", reason="season_not_persisted")
    return ToolResult(status="ok", data=teammate_pace_head_to_head(index))


@dataclass(frozen=True)
class ToolSpec:
    """Framework-neutral tool description - name, description, a plain
    input schema, and the callable itself. Not coupled to any agent SDK's
    tool format; that adapter is a separate, later layer.
    """

    name: str
    description: str
    input_schema: dict[str, dict[str, Any]]
    func: Callable[..., ToolResult]


TOOLS: dict[str, ToolSpec] = {
    "list_available_sessions": ToolSpec(
        name="list_available_sessions",
        description="List every persisted session for a season, optionally filtered by session type.",
        input_schema={
            "year": {"type": "int", "required": True, "description": "Championship year, e.g. 2024"},
            "session_type": {
                "type": "str", "required": False,
                "description": "e.g. 'R' or 'S'; omit for every session type",
            },
        },
        func=list_available_sessions,
    ),
    "get_session_summary": ToolSpec(
        name="get_session_summary",
        description="Roster, classification, and track conditions for one session.",
        input_schema={
            "year": {"type": "int", "required": True, "description": "Championship year"},
            "round_number": {"type": "int", "required": True, "description": "Schedule round number"},
            "session_type": {"type": "str", "required": True, "description": "e.g. 'R' or 'S'"},
        },
        func=get_session_summary,
    ),
    "get_race_pace": ToolSpec(
        name="get_race_pace",
        description="Race pace for one or every driver in a session, under an explicitly-named policy.",
        input_schema={
            "year": {"type": "int", "required": True, "description": "Championship year"},
            "round_number": {"type": "int", "required": True, "description": "Schedule round number"},
            "session_type": {"type": "str", "required": True, "description": "e.g. 'R' or 'S'"},
            "policy": {
                "type": "str", "required": False,
                "description": "'representative_race_pace' (default, the answer) or 'green_flag_pace' (the sensitivity check)",
            },
            "driver": {
                "type": "str", "required": False,
                "description": "3-letter driver code; omit for every driver",
            },
        },
        func=get_race_pace,
    ),
    "get_stints": ToolSpec(
        name="get_stints",
        description="Tyre stint history for one or every driver in a session.",
        input_schema={
            "year": {"type": "int", "required": True, "description": "Championship year"},
            "round_number": {"type": "int", "required": True, "description": "Schedule round number"},
            "session_type": {"type": "str", "required": True, "description": "e.g. 'R' or 'S'"},
            "driver": {
                "type": "str", "required": False,
                "description": "3-letter driver code; omit for every driver",
            },
        },
        func=get_stints,
    ),
    "get_tyre_degradation": ToolSpec(
        name="get_tyre_degradation",
        description="Per-stint tyre degradation slope for one or every driver (net trend, not pure wear).",
        input_schema={
            "year": {"type": "int", "required": True, "description": "Championship year"},
            "round_number": {"type": "int", "required": True, "description": "Schedule round number"},
            "session_type": {"type": "str", "required": True, "description": "e.g. 'R' or 'S'"},
            "driver": {
                "type": "str", "required": False,
                "description": "3-letter driver code; omit for every driver",
            },
        },
        func=get_tyre_degradation,
    ),
    "get_compound_performance": ToolSpec(
        name="get_compound_performance",
        description="Session-wide median pace per tyre compound (real compounds only).",
        input_schema={
            "year": {"type": "int", "required": True, "description": "Championship year"},
            "round_number": {"type": "int", "required": True, "description": "Schedule round number"},
            "session_type": {"type": "str", "required": True, "description": "e.g. 'R' or 'S'"},
        },
        func=get_compound_performance,
    ),
    "get_pit_stops": ToolSpec(
        name="get_pit_stops",
        description="Pit stops for one or every driver in a session.",
        input_schema={
            "year": {"type": "int", "required": True, "description": "Championship year"},
            "round_number": {"type": "int", "required": True, "description": "Schedule round number"},
            "session_type": {"type": "str", "required": True, "description": "e.g. 'R' or 'S'"},
            "driver": {
                "type": "str", "required": False,
                "description": "3-letter driver code; omit for every driver",
            },
        },
        func=get_pit_stops,
    ),
    "get_lap_exclusions": ToolSpec(
        name="get_lap_exclusions",
        description="Full lap-quality exclusion accounting for one driver in one session.",
        input_schema={
            "year": {"type": "int", "required": True, "description": "Championship year"},
            "round_number": {"type": "int", "required": True, "description": "Schedule round number"},
            "session_type": {"type": "str", "required": True, "description": "e.g. 'R' or 'S'"},
            "driver": {"type": "str", "required": True, "description": "3-letter driver code"},
        },
        func=get_lap_exclusions,
    ),
    "get_teammate_head_to_head": ToolSpec(
        name="get_teammate_head_to_head",
        description=(
            "Season-long teammate representative_race_pace head-to-head. "
            "Callers must attach the track-position/strategy confound caveat "
            "(see README) to any presented result."
        ),
        input_schema={
            "year": {"type": "int", "required": True, "description": "Championship year"},
            "session_type": {
                "type": "str", "required": False,
                "description": "Defaults to 'R' - Sprint/Race are not pooled",
            },
        },
        func=get_teammate_head_to_head,
    ),
}
