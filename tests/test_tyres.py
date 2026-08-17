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
