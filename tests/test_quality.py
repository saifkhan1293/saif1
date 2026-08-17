from saif1.analysis.quality import filter_usable_laps, is_green_flag_lap
from tests.conftest import make_laps


def test_is_green_flag_lap_clear():
    assert is_green_flag_lap("1") is True


def test_is_green_flag_lap_safety_car():
    assert is_green_flag_lap("4") is False


def test_is_green_flag_lap_concatenated_codes():
    # FastF1 concatenates codes when multiple statuses occur in one lap.
    assert is_green_flag_lap("12") is False  # contains yellow (2)


def test_is_green_flag_lap_empty_string():
    assert is_green_flag_lap("") is True


def test_filter_usable_laps_removes_pit_deleted_and_inaccurate():
    laps = make_laps(
        [
            {"LapNumber": 1, "IsAccurate": True, "Deleted": False},
            {"LapNumber": 2, "IsAccurate": False, "Deleted": False},  # inaccurate
            {"LapNumber": 3, "IsAccurate": True, "Deleted": True},  # deleted
            {"LapNumber": 4, "IsAccurate": True, "Deleted": False, "PitInTime": 100.0},  # in-lap
            {"LapNumber": 5, "IsAccurate": True, "Deleted": False},
        ]
    )
    usable = filter_usable_laps(laps)
    assert sorted(usable["LapNumber"].tolist()) == [1, 5]


def test_filter_usable_laps_green_flag_only():
    laps = make_laps(
        [
            {"LapNumber": 1, "TrackStatus": "1"},
            {"LapNumber": 2, "TrackStatus": "4"},  # safety car
            {"LapNumber": 3, "TrackStatus": "12"},  # yellow mixed in
        ]
    )
    usable = filter_usable_laps(laps, green_flag_only=True)
    assert usable["LapNumber"].tolist() == [1]


def test_filter_usable_laps_empty_input():
    laps = make_laps([])
    usable = filter_usable_laps(laps)
    assert len(usable) == 0
