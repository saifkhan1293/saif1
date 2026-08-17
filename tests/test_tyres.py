import pytest

from saif1.analysis.tyres import compound_performance, stint_degradation
from tests.conftest import make_laps


def test_stint_degradation_normal():
    laps = make_laps(
        [
            {"LapNumber": n, "TyreLife": n, "LapTime": 90.0 + 0.5 * (n - 1)}
            for n in range(1, 6)
        ]
    )
    result = stint_degradation(laps)
    assert result["slope_s_per_lap"] == pytest.approx(0.5, abs=1e-6)
    assert result["usable_laps"] == 5


def test_stint_degradation_insufficient_laps():
    laps = make_laps(
        [
            {"LapNumber": 1, "TyreLife": 1, "LapTime": 90.0},
            {"LapNumber": 2, "TyreLife": 2, "LapTime": 90.5},
        ]
    )
    result = stint_degradation(laps)
    assert result["slope_s_per_lap"] is None
    assert result["usable_laps"] == 2


def test_stint_degradation_empty():
    laps = make_laps([])
    result = stint_degradation(laps)
    assert result["slope_s_per_lap"] is None
    assert result["usable_laps"] == 0


def test_stint_degradation_excludes_yellow_flag_lap():
    # Proves the policy switch to green_flag_laps actually took effect:
    # a yellow-flagged lap (lap 3, an outlier that would distort the fit)
    # must not count toward the linear regression.
    # y = 90.0 + 0.5 * (TyreLife - 1) is the exact underlying line; lap 3's
    # LapTime is deliberately off that line (an outlier) to prove it gets
    # excluded rather than distorting the fit.
    laps = make_laps(
        [
            {"LapNumber": 1, "TyreLife": 1, "LapTime": 90.0, "TrackStatus": "1"},
            {"LapNumber": 2, "TyreLife": 2, "LapTime": 90.5, "TrackStatus": "1"},
            {"LapNumber": 3, "TyreLife": 3, "LapTime": 110.0, "TrackStatus": "2"},  # yellow, excluded
            {"LapNumber": 4, "TyreLife": 4, "LapTime": 91.5, "TrackStatus": "1"},
            {"LapNumber": 5, "TyreLife": 5, "LapTime": 92.0, "TrackStatus": "1"},
        ]
    )
    result = stint_degradation(laps)
    # Only 4 of the 5 laps are usable (lap 3 excluded); the perfectly
    # linear 0.5 s/lap trend from the remaining laps must survive intact -
    # if the yellow-flagged outlier leaked in, this slope would be way off
    # (110.0 is nowhere near the line).
    assert result["usable_laps"] == 4
    assert result["slope_s_per_lap"] == pytest.approx(0.5, abs=1e-6)


def test_compound_performance_normal():
    laps = make_laps(
        [
            {"LapNumber": 1, "Compound": "SOFT", "LapTime": 90.0},
            {"LapNumber": 2, "Compound": "SOFT", "LapTime": 90.4},
            {"LapNumber": 3, "Compound": "HARD", "LapTime": 91.0},
            {"LapNumber": 4, "Compound": "HARD", "LapTime": 91.2},
        ]
    )
    results = compound_performance(laps)
    compounds = [r["compound"] for r in results]
    assert compounds == ["SOFT", "HARD"]  # sorted fastest-first
    soft = next(r for r in results if r["compound"] == "SOFT")
    assert soft["median_lap_time_s"] == pytest.approx(90.2)
    assert soft["usable_laps"] == 2


def test_compound_performance_empty():
    laps = make_laps([])
    assert compound_performance(laps) == []


def test_compound_performance_rejects_unrecognized_string():
    # The real bug found in 2023 Canadian GP data: FastF1 emitted the
    # literal string "None" for 35 laps, which used to rank FIRST in
    # compound_performance ahead of real compounds.
    laps = make_laps(
        [
            {"LapNumber": 1, "Compound": "MEDIUM", "LapTime": 90.0},
            {"LapNumber": 2, "Compound": "MEDIUM", "LapTime": 90.4},
            {"LapNumber": 3, "Compound": "None", "LapTime": 1.0},  # would rank first if not rejected
            {"LapNumber": 4, "Compound": "None", "LapTime": 1.0},
        ]
    )
    results = compound_performance(laps)
    assert [r["compound"] for r in results] == ["MEDIUM"]


def test_compound_performance_recognizes_pre_2019_compounds():
    # 2018 used HYPERSOFT/ULTRASOFT/SUPERSOFT/SUPERHARD naming (verified
    # empirically against real 2018 FastF1 data, not assumed) - these must
    # rank normally, not be treated as unrecognized.
    laps = make_laps(
        [
            {"LapNumber": 1, "Compound": "HYPERSOFT", "LapTime": 88.0},
            {"LapNumber": 2, "Compound": "HYPERSOFT", "LapTime": 88.4},
            {"LapNumber": 3, "Compound": "SUPERHARD", "LapTime": 92.0},
            {"LapNumber": 4, "Compound": "SUPERHARD", "LapTime": 92.4},
        ]
    )
    results = compound_performance(laps)
    assert [r["compound"] for r in results] == ["HYPERSOFT", "SUPERHARD"]


def test_compound_performance_excludes_fastf1_unknown_from_ranking():
    # FastF1's own "UNKNOWN"/"TEST-UNKNOWN" are legitimate values (FastF1
    # itself doesn't know the compound) but aren't a physical tyre choice,
    # so they're excluded from a pace *ranking* without being flagged as
    # unrecognized/invalid data.
    laps = make_laps(
        [
            {"LapNumber": 1, "Compound": "SOFT", "LapTime": 90.0},
            {"LapNumber": 2, "Compound": "SOFT", "LapTime": 90.4},
            {"LapNumber": 3, "Compound": "UNKNOWN", "LapTime": 1.0},
            {"LapNumber": 4, "Compound": "TEST-UNKNOWN", "LapTime": 1.0},
        ]
    )
    results = compound_performance(laps)
    assert [r["compound"] for r in results] == ["SOFT"]
