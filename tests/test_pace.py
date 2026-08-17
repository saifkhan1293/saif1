import pytest

from saif1.analysis.pace import (
    calculate_green_flag_pace,
    calculate_race_pace,
    compare_driver_pace,
    lap_time_to_seconds,
)
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
    assert stats["policy"] == "representative_race_pace"
    assert stats["total_laps"] == 10
    # Laps 5 (PitInTime) and 6 (PitOutTime) are pit laps and excluded.
    # No severe (SC/VSC/red) laps in this fixture, so the policy change
    # doesn't affect the count here - see test_calculate_green_flag_pace_*
    # below for a fixture where the two policies actually diverge.
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


def test_calculate_green_flag_pace_matches_race_pace_when_no_flags():
    # Fixture has no severe or yellow-flag laps, so both policies should
    # agree exactly - proves green_flag_pace doesn't over-exclude when
    # there's nothing flag-related to exclude.
    laps = make_laps([{"LapNumber": n, "LapTime": 90.0 + n * 0.01} for n in range(1, 6)])
    representative = calculate_race_pace(laps, "XXX")
    green_flag = calculate_green_flag_pace(laps, "XXX")

    assert green_flag["policy"] == "green_flag_pace"
    assert green_flag["usable_laps"] == representative["usable_laps"]
    assert green_flag["median_lap_time_s"] == pytest.approx(representative["median_lap_time_s"])


def test_calculate_green_flag_pace_excludes_yellow_but_race_pace_keeps_it():
    # This is the case the two policies exist to distinguish: a yellow
    # flag lap is excluded from green_flag_pace but kept in the default
    # representative_race_pace.
    laps = make_laps(
        [
            {"LapNumber": 1, "LapTime": 90.0, "TrackStatus": "1"},
            {"LapNumber": 2, "LapTime": 90.1, "TrackStatus": "1"},
            {"LapNumber": 3, "LapTime": 95.0, "TrackStatus": "2"},  # yellow
        ]
    )
    representative = calculate_race_pace(laps, "XXX")
    green_flag = calculate_green_flag_pace(laps, "XXX")

    assert representative["usable_laps"] == 3
    assert green_flag["usable_laps"] == 2
    assert green_flag["best_lap_time_s"] == pytest.approx(90.0)


def test_calculate_green_flag_pace_driver_not_found(two_driver_race_laps):
    with pytest.raises(DriverNotFoundError):
        calculate_green_flag_pace(two_driver_race_laps, "NOTREAL")
