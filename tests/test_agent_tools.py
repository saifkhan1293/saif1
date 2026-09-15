"""Tests for saif1.agent.tools - the Phase 2 Milestone 1 tool surface.

Deliberately exercised against REAL persisted 2024 data (data/results/),
not synthetic fixtures, per the milestone's instruction: these tools are
thin wrappers with no new logic of their own, so what matters is that
they correctly read the real files, including the real no-data cases
that real data actually contains (a driver absent from race_pace
entirely vs. present with usable_laps=0 are both real, verified facts
about the 2024 season, not constructed for the test).

No live FastF1 access anywhere in this file - every test reads files
already on disk.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from saif1.agent import tools as agent_tools
from saif1.agent.tools import TOOLS, ToolResult

# Real, verified 2024 facts this file relies on:
#   - Bahrain (round 1, R): VER raced normally - 3 stints, 2 pit stops,
#     HARD/SOFT compounds used, full lap_exclusions/tyre_degradation data.
#   - Monaco (round 8, R): OCO has a race_pace entry with usable_laps=0,
#     median_lap_time_s=None (lap 1 red flag) - present, not missing.
#   - British GP (round 12, R): GAS is in the session's driver roster but
#     has NO entry at all in race_pace (FastF1 recorded zero laps for
#     him) - the "driver_not_found" case, distinct from Monaco's OCO.
YEAR = 2024
BAHRAIN_ROUND = 1
MONACO_ROUND = 8
BRITISH_ROUND = 12


# --- ToolResult itself ---


def test_tool_result_ok_can_carry_empty_list():
    result = ToolResult(status="ok", data=[])
    assert result.data == []


def test_tool_result_no_data_requires_valid_reason():
    with pytest.raises(ValueError, match="no_data reason"):
        ToolResult(status="no_data", reason="not_a_real_reason")


def test_tool_result_no_data_rejects_data():
    with pytest.raises(ValueError, match="must not carry data"):
        ToolResult(status="no_data", reason="session_not_persisted", data=[1, 2, 3])


def test_tool_result_ok_rejects_reason():
    with pytest.raises(ValueError, match="only meaningful"):
        ToolResult(status="ok", data=[], reason="driver_not_found")


# --- list_available_sessions ---


def test_list_available_sessions_finds_real_2024_races():
    result = agent_tools.list_available_sessions(YEAR, session_type="R")
    assert result.status == "ok"
    round_numbers = {s["round_number"] for s in result.data}
    assert round_numbers == set(range(1, 25))  # all 24 rounds persisted
    assert all(s["session_type"] == "R" for s in result.data)


def test_list_available_sessions_includes_sprints_when_unfiltered():
    result = agent_tools.list_available_sessions(YEAR)
    assert result.status == "ok"
    session_types = {s["session_type"] for s in result.data}
    assert session_types == {"R", "S"}


def test_list_available_sessions_empty_year_is_ok_not_no_data():
    # A season with nothing persisted is a real, correct empty answer -
    # never no_data (there's no single specific thing being asked about).
    result = agent_tools.list_available_sessions(2099)
    assert result.status == "ok"
    assert result.data == []


def test_list_available_sessions_invalid_session_type_raises():
    with pytest.raises(ValueError, match="Unknown session_type"):
        agent_tools.list_available_sessions(YEAR, session_type="ZZ")


# --- get_session_summary ---


def test_get_session_summary_bahrain():
    result = agent_tools.get_session_summary(YEAR, BAHRAIN_ROUND, "R")
    assert result.status == "ok"
    assert result.data["session"]["event_name"] == "Bahrain Grand Prix"
    assert len(result.data["drivers"]) == 20
    assert "track_conditions" in result.data
    assert "position_changes" in result.data


def test_get_session_summary_not_persisted():
    result = agent_tools.get_session_summary(YEAR, 99, "R")
    assert result.status == "no_data"
    assert result.reason == "session_not_persisted"
    assert result.data is None


# --- get_race_pace ---


def test_get_race_pace_all_drivers_bahrain():
    result = agent_tools.get_race_pace(YEAR, BAHRAIN_ROUND, "R")
    assert result.status == "ok"
    assert any(p["driver"] == "VER" for p in result.data)
    assert all(p["policy"] == "representative_race_pace" for p in result.data)


def test_get_race_pace_single_driver():
    result = agent_tools.get_race_pace(YEAR, BAHRAIN_ROUND, "R", driver="VER")
    assert result.status == "ok"
    assert result.data["driver"] == "VER"
    assert result.data["usable_laps"] > 0


def test_get_race_pace_zero_usable_laps_is_ok_not_no_data():
    # OCO exists in Monaco's race_pace list with usable_laps=0 - a real
    # answer (raced, no usable pace data), not "missing".
    result = agent_tools.get_race_pace(YEAR, MONACO_ROUND, "R", driver="OCO")
    assert result.status == "ok"
    assert result.data["usable_laps"] == 0
    assert result.data["median_lap_time_s"] is None


def test_get_race_pace_driver_absent_entirely_is_no_data():
    # GAS is on British GP's roster but has zero laps recorded by FastF1
    # at all - absent from race_pace entirely, distinct from OCO above.
    result = agent_tools.get_race_pace(YEAR, BRITISH_ROUND, "R", driver="GAS")
    assert result.status == "no_data"
    assert result.reason == "driver_not_found"


def test_get_race_pace_green_flag_policy():
    result = agent_tools.get_race_pace(YEAR, BAHRAIN_ROUND, "R", policy="green_flag_pace", driver="VER")
    assert result.status == "ok"
    assert result.data["policy"] == "green_flag_pace"


def test_get_race_pace_invalid_policy_raises():
    with pytest.raises(ValueError, match="Unknown policy"):
        agent_tools.get_race_pace(YEAR, BAHRAIN_ROUND, "R", policy="fastest_lap")


def test_get_race_pace_session_not_persisted():
    result = agent_tools.get_race_pace(YEAR, 99, "R")
    assert result.status == "no_data"
    assert result.reason == "session_not_persisted"


# --- get_stints / get_tyre_degradation / get_pit_stops (shared shape) ---


def test_get_stints_all_and_single_driver():
    all_result = agent_tools.get_stints(YEAR, BAHRAIN_ROUND, "R")
    assert all_result.status == "ok"
    assert len(all_result.data) > 3  # multiple drivers, multiple stints each

    ver_result = agent_tools.get_stints(YEAR, BAHRAIN_ROUND, "R", driver="VER")
    assert ver_result.status == "ok"
    assert len(ver_result.data) == 3
    assert all(s["driver"] == "VER" for s in ver_result.data)


def test_get_stints_unknown_driver_code_is_no_data():
    result = agent_tools.get_stints(YEAR, BAHRAIN_ROUND, "R", driver="ZZZ")
    assert result.status == "no_data"
    assert result.reason == "driver_not_found"


def test_get_tyre_degradation_single_driver():
    result = agent_tools.get_tyre_degradation(YEAR, BAHRAIN_ROUND, "R", driver="VER")
    assert result.status == "ok"
    assert len(result.data) == 3
    assert all("slope_s_per_lap" in d for d in result.data)


def test_get_pit_stops_single_driver():
    result = agent_tools.get_pit_stops(YEAR, BAHRAIN_ROUND, "R", driver="VER")
    assert result.status == "ok"
    assert len(result.data) == 2


def test_get_pit_stops_session_not_persisted():
    result = agent_tools.get_pit_stops(YEAR, 99, "R")
    assert result.status == "no_data"
    assert result.reason == "session_not_persisted"


# --- get_compound_performance ---


def test_get_compound_performance_bahrain():
    result = agent_tools.get_compound_performance(YEAR, BAHRAIN_ROUND, "R")
    assert result.status == "ok"
    compounds = {c["compound"] for c in result.data}
    assert compounds == {"HARD", "SOFT"}  # verified real fact: no MEDIUM used


def test_get_compound_performance_session_not_persisted():
    result = agent_tools.get_compound_performance(YEAR, 99, "R")
    assert result.status == "no_data"
    assert result.reason == "session_not_persisted"


# --- get_lap_exclusions ---


def test_get_lap_exclusions_single_driver_required():
    result = agent_tools.get_lap_exclusions(YEAR, BAHRAIN_ROUND, "R", "VER")
    assert result.status == "ok"
    assert result.data["driver"] == "VER"
    assert "excluded_laps_detail" in result.data
    assert "policies" in result.data


def test_get_lap_exclusions_unknown_driver_is_no_data():
    result = agent_tools.get_lap_exclusions(YEAR, BAHRAIN_ROUND, "R", "ZZZ")
    assert result.status == "no_data"
    assert result.reason == "driver_not_found"


def test_get_lap_exclusions_session_not_persisted():
    result = agent_tools.get_lap_exclusions(YEAR, 99, "R", "VER")
    assert result.status == "no_data"
    assert result.reason == "session_not_persisted"


# --- get_teammate_head_to_head ---


def test_get_teammate_head_to_head_2024():
    result = agent_tools.get_teammate_head_to_head(YEAR)
    assert result.status == "ok"
    red_bull = next(p for p in result.data if p["team"] == "Red Bull Racing")
    assert {red_bull["driver_a"], red_bull["driver_b"]} == {"PER", "VER"}
    assert red_bull["median_gap_s"] is not None


def test_get_teammate_head_to_head_season_not_persisted():
    result = agent_tools.get_teammate_head_to_head(2099)
    assert result.status == "no_data"
    assert result.reason == "season_not_persisted"


def test_get_teammate_head_to_head_invalid_session_type_raises():
    with pytest.raises(ValueError, match="Unknown session_type"):
        agent_tools.get_teammate_head_to_head(YEAR, session_type="ZZ")


# --- TOOLS registry ---


def test_tools_registry_covers_every_public_function():
    expected = {
        "list_available_sessions", "get_session_summary", "get_race_pace",
        "get_stints", "get_tyre_degradation", "get_compound_performance",
        "get_pit_stops", "get_lap_exclusions", "get_teammate_head_to_head",
    }
    assert set(TOOLS.keys()) == expected


def test_tools_registry_entries_are_self_consistent():
    for name, spec in TOOLS.items():
        assert spec.name == name
        assert spec.description
        assert callable(spec.func)
        assert isinstance(spec.input_schema, dict)
        for param_name, param_spec in spec.input_schema.items():
            assert "type" in param_spec
            assert "required" in param_spec
            assert "description" in param_spec


def test_tools_registry_callable_end_to_end():
    # The registry's func must be the exact same callable a direct import
    # would give - no adapter/wrapping snuck in.
    spec = TOOLS["get_session_summary"]
    result = spec.func(YEAR, BAHRAIN_ROUND, "R")
    assert result.status == "ok"


# --- module boundary ---


def test_agent_tools_importable_without_fastf1():
    """Same discipline as aggregation.py, more urgently here: an agent
    calling these tools must never transitively require fastf1. Runs in
    a subprocess with fastf1's import blocked at the meta-path level, so
    a failure can't leak into any other test in this process.
    """
    src_dir = Path(__file__).resolve().parents[1] / "src"
    script = (
        f"import sys\n"
        f"sys.path.insert(0, {str(src_dir)!r})\n"
        "class _BlockFastF1:\n"
        "    def find_spec(self, name, path, target=None):\n"
        "        if name == 'fastf1' or name.startswith('fastf1.'):\n"
        "            raise ImportError('fastf1 blocked for this test')\n"
        "        return None\n"
        "sys.meta_path.insert(0, _BlockFastF1())\n"
        "import saif1.agent.tools\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "OK" in result.stdout
