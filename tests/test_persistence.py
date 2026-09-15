"""Tests for saif1.persistence. Uses a synthetic _FakeSession - no live
FastF1 session is ever loaded here.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from saif1.config import SessionRequest
from saif1.persistence import build_session_result, result_filename, save_result
from tests.conftest import make_laps


class _FakeSession:
    """Minimal stand-in exposing exactly what build_session_result reads:
    .laps, .results, .event, .date.
    """

    def __init__(self, laps, results: pd.DataFrame, event: pd.Series, date: pd.Timestamp):
        self.laps = laps
        self.results = results
        self.event = event
        self.date = date


def _make_fake_session():
    results = pd.DataFrame(
        [
            {
                "Abbreviation": "AAA", "DriverNumber": "1", "FullName": "Driver Aaa",
                "TeamName": "Team A", "GridPosition": 1, "Position": 1, "Status": "Finished",
            },
            {
                "Abbreviation": "BBB", "DriverNumber": "2", "FullName": "Driver Bbb",
                "TeamName": "Team B", "GridPosition": 2, "Position": 2, "Status": "Finished",
            },
            {
                "Abbreviation": "CCC", "DriverNumber": "3", "FullName": "Driver Ccc",
                "TeamName": "Team C", "GridPosition": 3, "Position": float("nan"), "Status": "Retired",
            },
        ]
    )

    rows = []
    # AAA: full clean race, two stints, one pit stop.
    for lap in range(1, 21):
        rows.append(
            {
                "Driver": "AAA", "DriverNumber": "1", "LapNumber": lap,
                "LapTime": 90.0 + lap * 0.01,
                "Stint": 1 if lap <= 10 else 2,
                "Compound": "SOFT" if lap <= 10 else "HARD",
                "TyreLife": lap if lap <= 10 else lap - 10,
                "PitInTime": 90.0 * lap if lap == 10 else None,
                "PitOutTime": 90.0 * lap + 24 if lap == 11 else None,
                "Position": 1,
                "TrackStatus": "1",
            }
        )
    # BBB: full race, one pit stop, one yellow-flag lap (to exercise
    # track_conditions and the two pace policies diverging).
    for lap in range(1, 21):
        rows.append(
            {
                "Driver": "BBB", "DriverNumber": "2", "LapNumber": lap,
                "LapTime": 91.0 + lap * 0.01 + (5.0 if lap == 15 else 0.0),
                "Stint": 1 if lap <= 10 else 2,
                "Compound": "SOFT" if lap <= 10 else "HARD",
                "TyreLife": lap if lap <= 10 else lap - 10,
                "PitInTime": 91.0 * lap if lap == 10 else None,
                "PitOutTime": 91.0 * lap + 24 if lap == 11 else None,
                "Position": 2,
                "TrackStatus": "2" if lap == 15 else "1",
            }
        )
    # CCC: retired after lap 10 - fewer laps recorded than the other two.
    for lap in range(1, 11):
        rows.append(
            {
                "Driver": "CCC", "DriverNumber": "3", "LapNumber": lap,
                "LapTime": 92.0 + lap * 0.01,
                "Stint": 1,
                "Compound": "MEDIUM",
                "TyreLife": lap,
                "Position": 3,
                "TrackStatus": "1",
            }
        )
    laps = make_laps(rows)

    event = pd.Series(
        {
            "RoundNumber": 1,
            "EventName": "Test Grand Prix",
            "Location": "Testville",
            "Country": "Testland",
            "EventDate": pd.Timestamp("2024-03-02"),
        }
    )
    date = pd.Timestamp("2024-03-02T15:00:00")

    return _FakeSession(laps, results, event, date)


@pytest.fixture
def fake_session():
    return _make_fake_session()


@pytest.fixture
def request_obj():
    return SessionRequest(year=2024, event="Test Grand Prix", session_type="R")


def test_build_session_result_top_level_keys(fake_session, request_obj):
    result = build_session_result(fake_session, request_obj)
    expected_keys = {
        "schema_version", "provenance", "session", "drivers", "race_pace",
        "stints", "tyre_degradation", "compound_performance", "pit_stops",
        "position_changes", "lap_exclusions", "track_conditions",
        "quality_policy_definitions",
    }
    assert expected_keys.issubset(result.keys())


def test_build_session_result_drivers_schema(fake_session, request_obj):
    result = build_session_result(fake_session, request_obj)
    drivers = {d["driver"]: d for d in result["drivers"]}

    assert drivers["AAA"] == {
        "driver": "AAA", "driver_number": "1", "full_name": "Driver Aaa",
        "team": "Team A", "grid_position": 1, "finish_position": 1, "status": "Finished",
    }
    # CCC retired - Position is NaN in the source data and must become an
    # explicit null, never 0 or omitted.
    ccc = drivers["CCC"]
    assert ccc["finish_position"] is None
    assert ccc["grid_position"] == 3
    assert ccc["status"] == "Retired"


def test_build_session_result_json_roundtrip(fake_session, request_obj):
    result = build_session_result(fake_session, request_obj)
    reloaded = json.loads(json.dumps(result))
    assert reloaded == result


def test_lap_exclusions_laps_recorded_matches_actual_lap_counts(fake_session, request_obj):
    result = build_session_result(fake_session, request_obj)
    exclusions = {e["driver"]: e for e in result["lap_exclusions"]}

    assert exclusions["AAA"]["laps_recorded"] == 20
    assert exclusions["BBB"]["laps_recorded"] == 20
    assert exclusions["CCC"]["laps_recorded"] == 10  # retired driver, fewer laps


def test_race_pace_policies_diverge_for_yellow_affected_driver(fake_session, request_obj):
    result = build_session_result(fake_session, request_obj)
    representative = {p["driver"]: p for p in result["race_pace"]["representative_race_pace"]}
    green_flag = {p["driver"]: p for p in result["race_pace"]["green_flag_pace"]}

    # BBB has one yellow-flagged lap - green_flag_pace must exclude it,
    # representative_race_pace must keep it.
    assert green_flag["BBB"]["usable_laps"] < representative["BBB"]["usable_laps"]
    # AAA has no flag-affected laps - the two policies must agree exactly.
    assert green_flag["AAA"]["usable_laps"] == representative["AAA"]["usable_laps"]


def test_track_conditions_reflects_yellow_flag_lap(fake_session, request_obj):
    result = build_session_result(fake_session, request_obj)
    yellow_entries = [c for c in result["track_conditions"] if c["condition"] == "yellow_flag"]
    assert any(c["start_lap"] == 15 and c["end_lap"] == 15 for c in yellow_entries)


def test_position_changes_matches_drivers_positions(fake_session, request_obj):
    """Decided: drivers[] is the canonical source for grid/finish position;
    position_changes[] must agree with it exactly, including null handling
    for the retired driver.
    """
    result = build_session_result(fake_session, request_obj)
    drivers_by_code = {d["driver"]: d for d in result["drivers"]}

    for change in result["position_changes"]:
        driver_entry = drivers_by_code[change["driver"]]
        assert change["start_position"] == driver_entry["grid_position"]
        assert change["finish_position"] == driver_entry["finish_position"]


def test_provenance_fields_present(fake_session, request_obj):
    result = build_session_result(fake_session, request_obj)
    provenance = result["provenance"]
    assert provenance["data_source"] == "FastF1"
    assert provenance["saif1_methodology_version"]
    assert provenance["fastf1_version"]
    assert provenance["generated_at"]
    assert provenance["session_identifier"] == "2024-01-R"


def test_quality_policy_definitions_match_single_source_of_truth(fake_session, request_obj):
    from saif1.analysis.quality import POLICY_DEFINITIONS

    result = build_session_result(fake_session, request_obj)
    assert result["quality_policy_definitions"] == POLICY_DEFINITIONS


def test_result_filename_is_deterministic_and_slugified(fake_session, request_obj):
    result = build_session_result(fake_session, request_obj)
    filename = result_filename(result)
    assert filename == "2024_01_test-grand-prix_R.json"


def test_result_filename_is_stable_for_known_events():
    """Regression net: a slug change means a persisted result's filename
    changes, which orphans the old file on disk (result_filename is used
    directly to decide where save_result overwrites - see its docstring).
    This pins the exact slug for real event names, including the one that
    was wrong before (accented characters were stripped, not
    transliterated - "São Paulo Grand Prix" produced
    "s-o-paulo-grand-prix"). A future change to slugging must fail this
    test rather than silently start writing to new filenames.
    """
    from saif1.persistence import _slugify

    assert _slugify("São Paulo Grand Prix") == "sao-paulo-grand-prix"
    assert _slugify("Bahrain Grand Prix") == "bahrain-grand-prix"
    assert _slugify("Emilia Romagna Grand Prix") == "emilia-romagna-grand-prix"
    assert _slugify("United States Grand Prix") == "united-states-grand-prix"
    assert _slugify("Qatar Grand Prix") == "qatar-grand-prix"


def test_unrecognized_compound_laps_reported_not_silently_dropped(request_obj):
    # Reproduces the real 2023 Canadian GP defect: a driver with a
    # genuinely unrecognized Compound value (the literal string "None")
    # must be counted and reported, not silently absorbed anywhere.
    results = pd.DataFrame(
        [{"Abbreviation": "AAA", "DriverNumber": "1", "FullName": "Driver Aaa",
          "TeamName": "Team A", "GridPosition": 1, "Position": 1, "Status": "Finished"}]
    )
    rows = [
        {"Driver": "AAA", "DriverNumber": "1", "LapNumber": 1, "Compound": "SOFT", "LapTime": 90.0},
        {"Driver": "AAA", "DriverNumber": "1", "LapNumber": 2, "Compound": "None", "LapTime": 90.5},
        {"Driver": "AAA", "DriverNumber": "1", "LapNumber": 3, "Compound": "None", "LapTime": 90.6},
    ]
    laps = make_laps(rows)
    event = pd.Series(
        {"RoundNumber": 1, "EventName": "Test Grand Prix", "Location": "Testville",
         "Country": "Testland", "EventDate": pd.Timestamp("2024-03-02")}
    )
    session = _FakeSession(laps, results, event, pd.Timestamp("2024-03-02T15:00:00"))

    result = build_session_result(session, request_obj)
    summary = result["unrecognized_compound_laps"]
    assert summary["count"] == 2
    assert summary["by_driver"] == {"AAA": [2, 3]}


def test_save_result_raises_on_nan_rather_than_writing_invalid_json(tmp_path):
    # allow_nan=False: a stray NaN reaching serialization must fail loudly
    # (ValueError, at write time) rather than silently produce a file with
    # a bare NaN token, which is invalid JSON for a strict parser (e.g. a
    # browser's JSON.parse).
    bad_result = {
        "schema_version": "1.1",
        "session": {"year": 2024, "round_number": 1, "event_name": "Test GP", "session_type": "R"},
        "team": float("nan"),  # simulates an unguarded field reaching serialization
    }
    with pytest.raises(ValueError):
        save_result(bad_result, output_dir=tmp_path)
    assert list(tmp_path.glob("*.json")) == []  # no partial/corrupt file left behind


def test_save_result_overwrites_same_path_not_duplicated(fake_session, request_obj, tmp_path):
    result_1 = build_session_result(fake_session, request_obj)
    path_1 = save_result(result_1, output_dir=tmp_path)

    # Mutate something so the second write is verifiably different content,
    # then save again - this must overwrite, not create a second file.
    result_2 = build_session_result(fake_session, request_obj)
    result_2["provenance"]["saif1_methodology_version"] = "9.9.9-test"
    path_2 = save_result(result_2, output_dir=tmp_path)

    assert path_1 == path_2
    assert list(tmp_path.glob("*.json")) == [path_1]

    on_disk = json.loads(path_1.read_text(encoding="utf-8"))
    assert on_disk["provenance"]["saif1_methodology_version"] == "9.9.9-test"
