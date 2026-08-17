import pytest

from saif1.analysis.pace import calculate_race_pace, compare_driver_pace, lap_time_to_seconds
from saif1.exceptions import DriverNotFoundError
from tests.conftest import make_laps


def test_lap_time_to_seconds_normal():
    laps = make_laps([{"LapTime": 91.234}])
    assert lap_time_to_seconds(laps.iloc[0]["LapTime"]) == pytest.approx(91.234)


def test_lap_time_to_seconds_missing():
    laps = make_laps([{"LapTime": None}])
    assert lap_time_to_seconds(laps.iloc[0]["LapTime"]) is None


def test_calculate_race_pace_normal(two_driver_race_laps):
    stats = calculate_race_pace(two_driver_race_laps, "VER")
    assert stats["driver"] == "VER"
    assert stats["total_laps"] == 10
    # Laps 5 (PitInTime) and 6 (PitOutTime) are pit laps and excluded.
    assert stats["usable_laps"] == 8
    assert stats["best_lap_time_s"] == pytest.approx(90.01)
    assert stats["mean_lap_time_s"] is not None
    assert stats["median_lap_time_s"] is not None


def test_calculate_race_pace_excludes_deleted_lap(two_driver_race_laps):
    stats = calculate_race_pace(two_driver_race_laps, "HAM")
    # Lap 3 is deleted, laps 6/7 are pit laps -> 10 - 3 = 7 usable.
    assert stats["usable_laps"] == 7
    assert stats["best_lap_time_s"] == pytest.approx(91.01)


def test_calculate_race_pace_driver_not_found(two_driver_race_laps):
    with pytest.raises(DriverNotFoundError):
        calculate_race_pace(two_driver_race_laps, "NOTREAL")


def test_calculate_race_pace_empty_laps():
    laps = make_laps([])
    with pytest.raises(DriverNotFoundError):
        calculate_race_pace(laps, "VER")


def test_compare_driver_pace_normal(two_driver_race_laps):
    result = compare_driver_pace(two_driver_race_laps, "VER", "HAM")
    assert result["driver_1"] == "VER"
    assert result["driver_2"] == "HAM"
    assert result["usable_laps_driver_1"] == 8
    assert result["usable_laps_driver_2"] == 7
    # VER's lap times are consistently faster than HAM's in the fixture.
    assert result["median_pace_difference_s"] < 0
    assert result["mean_pace_difference_s"] < 0


def test_compare_driver_pace_missing_driver_raises(two_driver_race_laps):
    with pytest.raises(DriverNotFoundError):
        compare_driver_pace(two_driver_race_laps, "VER", "NOTREAL")
