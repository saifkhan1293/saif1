import pytest

from saif1.analysis.stints import extract_stints
from saif1.exceptions import DriverNotFoundError
from tests.conftest import make_laps


def test_extract_stints_normal(two_driver_race_laps):
    stints = extract_stints(two_driver_race_laps)
    ver_stints = [s for s in stints if s["driver"] == "VER"]
    ham_stints = [s for s in stints if s["driver"] == "HAM"]

    assert len(ver_stints) == 2
    assert ver_stints[0] == {
        "driver": "VER",
        "stint_number": 1,
        "compound": "SOFT",
        "start_lap": 1,
        "end_lap": 5,
        "stint_length": 5,
        "lap_times_s": pytest.approx([90.01, 90.02, 90.03, 90.04, 90.05]),
    }
    assert ver_stints[1]["compound"] == "HARD"
    assert ver_stints[1]["start_lap"] == 6
    assert ver_stints[1]["end_lap"] == 10

    assert len(ham_stints) == 2
    assert ham_stints[0]["end_lap"] == 6  # HAM's stint break is at lap 6, not 5


def test_extract_stints_single_driver_filter(two_driver_race_laps):
    stints = extract_stints(two_driver_race_laps, driver="VER")
    assert {s["driver"] for s in stints} == {"VER"}
    assert len(stints) == 2


def test_extract_stints_driver_not_found(two_driver_race_laps):
    with pytest.raises(DriverNotFoundError):
        extract_stints(two_driver_race_laps, driver="NOTREAL")


def test_extract_stints_empty_laps():
    laps = make_laps([])
    assert extract_stints(laps) == []


def test_extract_stints_handles_duplicate_rows():
    # Duplicate timing rows shouldn't crash stint extraction; they show up
    # as extra laps in the stint since no deduplication is applied here.
    laps = make_laps(
        [
            {"Driver": "VER", "DriverNumber": "1", "LapNumber": 1, "Stint": 1, "LapTime": 90.0},
            {"Driver": "VER", "DriverNumber": "1", "LapNumber": 1, "Stint": 1, "LapTime": 90.0},
        ]
    )
    stints = extract_stints(laps)
    assert len(stints) == 1
    assert stints[0]["stint_length"] == 2


def test_extract_stints_no_compound_data_at_all_is_unknown():
    laps = make_laps(
        [{"LapNumber": n, "Stint": 1, "Compound": None, "LapTime": 90.0} for n in range(1, 4)]
    )
    stints = extract_stints(laps)
    assert stints[0]["compound"] == "UNKNOWN"


def test_extract_stints_unrecognized_compound_string_is_flagged():
    # The real bug: FastF1 emitted the literal string "None" for a whole
    # stint (2023 Canadian GP, TSU laps 36-70) and it was silently
    # accepted as the stint's compound label.
    laps = make_laps(
        [{"LapNumber": n, "Stint": 1, "Compound": "None", "LapTime": 90.0} for n in range(1, 4)]
    )
    stints = extract_stints(laps)
    assert stints[0]["compound"] == "UNRECOGNIZED"


def test_extract_stints_prefers_known_compound_over_unrecognized():
    # A stint where most laps carry a real compound and one lap has
    # corrupted data - the real value should win, not "UNRECOGNIZED".
    laps = make_laps(
        [
            {"LapNumber": 1, "Stint": 1, "Compound": "MEDIUM", "LapTime": 90.0},
            {"LapNumber": 2, "Stint": 1, "Compound": "None", "LapTime": 90.5},
            {"LapNumber": 3, "Stint": 1, "Compound": "MEDIUM", "LapTime": 91.0},
        ]
    )
    stints = extract_stints(laps)
    assert stints[0]["compound"] == "MEDIUM"


def test_extract_stints_recognizes_pre_2019_compound():
    laps = make_laps(
        [{"LapNumber": n, "Stint": 1, "Compound": "ULTRASOFT", "LapTime": 85.0} for n in range(1, 4)]
    )
    stints = extract_stints(laps)
    assert stints[0]["compound"] == "ULTRASOFT"
