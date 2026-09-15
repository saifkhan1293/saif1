"""Tests for saif1.aggregation. Uses minimal synthetic result dicts (only
the fields the module actually reads) written to tmp_path - no real
persisted files or network access.
"""

from __future__ import annotations

import json

import pytest

from saif1.aggregation import MethodologyMismatchError, load_season_index, teammate_pace_head_to_head


def _pace_entry(driver: str, median: float | None, usable_laps: int = 50) -> dict:
    return {
        "driver": driver, "policy": "representative_race_pace",
        "median_lap_time_s": median, "mean_lap_time_s": median,
        "best_lap_time_s": median - 1 if median is not None else None,
        "usable_laps": usable_laps, "total_laps": 57,
    }


def _result(
    year: int, round_number: int, session_type: str, methodology_version: str,
    drivers_teams: dict[str, str], pace: dict[str, float | None],
) -> dict:
    """Build a minimal result dict. `pace` maps driver -> median lap time,
    or None for "zero usable laps that session"."""
    return {
        "schema_version": "1.1",
        "provenance": {
            "data_source": "FastF1", "fastf1_version": "3.8.3",
            "saif1_methodology_version": methodology_version,
            "generated_at": "2026-01-01T00:00:00+00:00",
            "session_identifier": f"{year}-{round_number:02d}-{session_type}",
        },
        "session": {
            "year": year, "event_name": f"Round {round_number}", "round_number": round_number,
            "session_type": session_type, "location": "Test", "country": "Test",
            "event_date": "2024-01-01", "session_date": "2024-01-01T00:00:00",
        },
        "drivers": [{"driver": d, "team": t} for d, t in drivers_teams.items()],
        "race_pace": {
            "representative_race_pace": [
                _pace_entry(d, m, usable_laps=0 if m is None else 50)
                for d, m in pace.items() if True
            ],
            "green_flag_pace": [],
        },
        "stints": [], "tyre_degradation": [], "compound_performance": [],
        "pit_stops": [], "position_changes": [], "lap_exclusions": [],
        "track_conditions": [], "unrecognized_compound_laps": {"count": 0, "by_driver": {}},
        "quality_policy_definitions": {},
    }


def _write(tmp_path, result: dict) -> None:
    session = result["session"]
    filename = f"{session['year']}_{session['round_number']:02d}_round_{session['session_type']}.json"
    (tmp_path / filename).write_text(json.dumps(result), encoding="utf-8")


# --- load_season_index ---


def test_load_season_index_filters_by_year_and_session_type(tmp_path):
    _write(tmp_path, _result(2024, 1, "R", "1.5.1", {"AAA": "Team A"}, {"AAA": 90.0}))
    _write(tmp_path, _result(2024, 1, "S", "1.5.1", {"AAA": "Team A"}, {"AAA": 90.0}))  # wrong session type
    _write(tmp_path, _result(2023, 1, "R", "1.5.1", {"AAA": "Team A"}, {"AAA": 90.0}))  # wrong year

    index = load_season_index(2024, "R", results_dir=tmp_path)
    assert len(index) == 1
    assert index.year == 2024
    assert index.session_type == "R"


def test_load_season_index_empty_directory(tmp_path):
    index = load_season_index(2099, "R", results_dir=tmp_path)
    assert len(index) == 0
    assert index.methodology_version == "unknown"


def test_load_season_index_raises_on_methodology_mismatch(tmp_path):
    _write(tmp_path, _result(2024, 1, "R", "1.5.0", {"AAA": "Team A"}, {"AAA": 90.0}))
    _write(tmp_path, _result(2024, 2, "R", "1.5.1", {"AAA": "Team A"}, {"AAA": 90.0}))

    with pytest.raises(MethodologyMismatchError, match="multiple"):
        load_season_index(2024, "R", results_dir=tmp_path)


def test_load_season_index_single_methodology_version_ok(tmp_path):
    _write(tmp_path, _result(2024, 1, "R", "1.5.1", {"AAA": "Team A"}, {"AAA": 90.0}))
    _write(tmp_path, _result(2024, 2, "R", "1.5.1", {"AAA": "Team A"}, {"AAA": 90.0}))

    index = load_season_index(2024, "R", results_dir=tmp_path)
    assert len(index) == 2
    assert index.methodology_version == "1.5.1"


# --- teammate_pace_head_to_head ---


def test_teammate_pace_head_to_head_basic(tmp_path):
    # Round 1: AAA faster. Round 2: BBB faster.
    r1 = _result(2024, 1, "R", "1.5.1", {"AAA": "Team A", "BBB": "Team A"}, {"AAA": 90.0, "BBB": 91.0})
    r2 = _result(2024, 2, "R", "1.5.1", {"AAA": "Team A", "BBB": "Team A"}, {"AAA": 92.0, "BBB": 91.0})
    _write(tmp_path, r1)
    _write(tmp_path, r2)

    index = load_season_index(2024, "R", results_dir=tmp_path)
    results = teammate_pace_head_to_head(index)

    assert len(results) == 1
    pairing = results[0]
    assert pairing["team"] == "Team A"
    assert {pairing["driver_a"], pairing["driver_b"]} == {"AAA", "BBB"}
    assert pairing["races_compared"] == 2
    assert pairing["driver_a_faster"] + pairing["driver_b_faster"] == 2
    # AAA won round 1, BBB won round 2 - exactly one win each.
    assert pairing["driver_a_faster"] == 1
    assert pairing["driver_b_faster"] == 1
    assert pairing["races_no_data"] == 0


def test_teammate_pace_head_to_head_zero_usable_laps_is_no_data_not_a_loss(tmp_path):
    # BBB has usable_laps=0 (crashed lap 1) - must not count as a win for
    # AAA, must not be treated as an infinitely slow/zero lap time.
    r1 = _result(2024, 1, "R", "1.5.1", {"AAA": "Team A", "BBB": "Team A"}, {"AAA": 90.0, "BBB": None})
    _write(tmp_path, r1)

    index = load_season_index(2024, "R", results_dir=tmp_path)
    results = teammate_pace_head_to_head(index)

    assert len(results) == 1
    pairing = results[0]
    assert pairing["races_compared"] == 0
    assert pairing["driver_a_faster"] == 0
    assert pairing["driver_b_faster"] == 0
    assert pairing["races_no_data"] == 1


def test_teammate_pace_head_to_head_skips_non_two_driver_team(tmp_path):
    # Three drivers for one team in one session (e.g. a reserve appearance
    # alongside both regulars) - must not create any pairing for this
    # session, not guess which two to compare.
    r1 = _result(
        2024, 1, "R", "1.5.1",
        {"AAA": "Team A", "BBB": "Team A", "CCC": "Team A"},
        {"AAA": 90.0, "BBB": 91.0, "CCC": 92.0},
    )
    _write(tmp_path, r1)

    index = load_season_index(2024, "R", results_dir=tmp_path)
    results = teammate_pace_head_to_head(index)
    assert results == []


def test_teammate_pace_head_to_head_midseason_driver_change_is_separate_pairing(tmp_path):
    # AAA+BBB race 1, AAA+CCC race 2 (BBB replaced) - two distinct
    # pairings, not merged into one nonsensical "BBB vs CCC" comparison.
    r1 = _result(2024, 1, "R", "1.5.1", {"AAA": "Team A", "BBB": "Team A"}, {"AAA": 90.0, "BBB": 91.0})
    r2 = _result(2024, 2, "R", "1.5.1", {"AAA": "Team A", "CCC": "Team A"}, {"AAA": 90.0, "CCC": 91.0})
    _write(tmp_path, r1)
    _write(tmp_path, r2)

    index = load_season_index(2024, "R", results_dir=tmp_path)
    results = teammate_pace_head_to_head(index)

    assert len(results) == 2
    pairs = {(r["driver_a"], r["driver_b"]) for r in results}
    assert pairs == {("AAA", "BBB"), ("AAA", "CCC")}
    for r in results:
        assert r["races_compared"] == 1


def test_teammate_pace_head_to_head_empty_index():
    from saif1.aggregation import SeasonIndex

    empty_index = SeasonIndex(year=2024, session_type="R", methodology_version="unknown", results=[])
    assert teammate_pace_head_to_head(empty_index) == []
