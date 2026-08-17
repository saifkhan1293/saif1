import pandas as pd
import pytest

from saif1.analysis.strategy import extract_pit_stops, position_changes, position_progression
from saif1.exceptions import DriverNotFoundError
from tests.conftest import make_laps


class _FakeSession:
    """Minimal stand-in for fastf1.core.Session - position_changes only
    reads .results, so a full Session (which requires a live API load)
    isn't needed to test it.
    """

    def __init__(self, results: pd.DataFrame) -> None:
        self.results = results


def test_extract_pit_stops_normal(two_driver_race_laps):
    stops = extract_pit_stops(two_driver_race_laps)
    assert len(stops) == 2

    ver_stop = next(s for s in stops if s["driver"] == "VER")
    assert ver_stop["in_lap"] == 5
    assert ver_stop["compound_before"] == "SOFT"
    assert ver_stop["compound_after"] == "HARD"
    assert ver_stop["pit_lane_time_s"] is not None
    assert ver_stop["pit_lane_time_s"] > 0


def test_extract_pit_stops_no_stops():
    laps = make_laps([{"LapNumber": 1}, {"LapNumber": 2}])
    assert extract_pit_stops(laps) == []


def test_extract_pit_stops_empty():
    laps = make_laps([])
    assert extract_pit_stops(laps) == []


def test_position_changes_normal():
    results = pd.DataFrame(
        [
            {"Abbreviation": "VER", "GridPosition": 3, "Position": 1, "Status": "Finished"},
            {"Abbreviation": "HAM", "GridPosition": 1, "Position": 2, "Status": "Finished"},
            {"Abbreviation": "DNF", "GridPosition": 10, "Position": float("nan"), "Status": "Retired"},
        ]
    )
    changes = position_changes(_FakeSession(results))

    ver = next(c for c in changes if c["driver"] == "VER")
    assert ver["positions_gained"] == 2

    dnf = next(c for c in changes if c["driver"] == "DNF")
    assert dnf["finish_position"] is None
    assert dnf["positions_gained"] is None

    # Drivers with a valid gain are ranked ahead of those without one.
    assert changes[0]["driver"] == "VER"


def test_position_changes_empty_results():
    results = pd.DataFrame(columns=["Abbreviation", "GridPosition", "Position", "Status"])
    assert position_changes(_FakeSession(results)) == []


def test_position_progression_normal(two_driver_race_laps):
    progression = position_progression(two_driver_race_laps, "VER")
    assert len(progression) == 10
    assert progression[0] == {"lap": 1, "position": 1}


def test_position_progression_driver_not_found(two_driver_race_laps):
    with pytest.raises(DriverNotFoundError):
        position_progression(two_driver_race_laps, "NOTREAL")
