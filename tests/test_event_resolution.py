"""Tests for saif1.data.event_resolution - all use a synthetic in-memory
schedule DataFrame, never a live fastf1.get_event_schedule() call.
"""

from __future__ import annotations

import pandas as pd
import pytest

from saif1.data.event_resolution import resolve_event
from saif1.exceptions import SessionNotFoundError


def _schedule(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


@pytest.fixture
def sample_schedule() -> pd.DataFrame:
    return _schedule(
        [
            {
                "RoundNumber": 1,
                "EventName": "Bahrain Grand Prix",
                "OfficialEventName": "FORMULA 1 GULF AIR BAHRAIN GRAND PRIX 2024",
                "Location": "Sakhir",
                "Country": "Bahrain",
                "EventDate": pd.Timestamp("2024-03-02"),
            },
            {
                "RoundNumber": 2,
                "EventName": "Saudi Arabian Grand Prix",
                "OfficialEventName": "FORMULA 1 STC SAUDI ARABIAN GRAND PRIX 2024",
                "Location": "Jeddah",
                "Country": "Saudi Arabia",
                "EventDate": pd.Timestamp("2024-03-09"),
            },
            {
                "RoundNumber": 3,
                "EventName": "Australian Grand Prix",
                "OfficialEventName": "FORMULA 1 ROLEX AUSTRALIAN GRAND PRIX 2024",
                "Location": "Melbourne",
                "Country": "Australia",
                "EventDate": pd.Timestamp("2024-03-24"),
            },
        ]
    )


def test_resolve_event_valid_exact_name(sample_schedule):
    resolved = resolve_event(sample_schedule, "Bahrain Grand Prix", 2024)
    assert resolved.round_number == 1
    assert resolved.event_name == "Bahrain Grand Prix"
    assert resolved.matched_unambiguously is True


def test_resolve_event_reasonable_variation(sample_schedule):
    # Common real-world variations: abbreviated "GP", country name alone,
    # different casing. All should resolve to the same event as above.
    for variant in ("Bahrain GP", "bahrain", "BAHRAIN"):
        resolved = resolve_event(sample_schedule, variant, 2024)
        assert resolved.round_number == 1
        assert resolved.event_name == "Bahrain Grand Prix"


def test_resolve_event_invalid_name_raises_with_hint(sample_schedule):
    with pytest.raises(SessionNotFoundError) as exc_info:
        resolve_event(sample_schedule, "Nonexistent Grand Prix", 2024)
    # No real event is a plausible fuzzy match for "nonexistent", so the
    # error should reject outright without fabricating a confident guess.
    assert "Could not confidently resolve" in str(exc_info.value)


def test_resolve_event_gibberish_name_raises(sample_schedule):
    with pytest.raises(SessionNotFoundError):
        resolve_event(sample_schedule, "Zzzxqy Racetrack", 2024)


def test_resolve_event_too_generic_raises(sample_schedule):
    with pytest.raises(SessionNotFoundError, match="too generic"):
        resolve_event(sample_schedule, "Grand Prix", 2024)


def test_resolve_event_ambiguous_raises():
    # Two synthetic events deliberately share "testland" in their Country
    # field, so a query for "Testland" is a substring match for both -
    # this must fail loudly rather than silently pick one.
    schedule = _schedule(
        [
            {
                "RoundNumber": 10,
                "EventName": "Testland North Grand Prix",
                "OfficialEventName": "Testland North Grand Prix",
                "Location": "North City",
                "Country": "Testland",
                "EventDate": pd.Timestamp("2024-05-01"),
            },
            {
                "RoundNumber": 11,
                "EventName": "Testland South Grand Prix",
                "OfficialEventName": "Testland South Grand Prix",
                "Location": "South City",
                "Country": "Testland",
                "EventDate": pd.Timestamp("2024-05-08"),
            },
        ]
    )
    with pytest.raises(SessionNotFoundError) as exc_info:
        resolve_event(schedule, "Testland", 2024)
    message = str(exc_info.value)
    assert "multiple" in message
    assert "Testland North Grand Prix" in message
    assert "Testland South Grand Prix" in message


def test_resolve_event_empty_schedule_raises():
    with pytest.raises(SessionNotFoundError):
        resolve_event(_schedule([]), "Bahrain Grand Prix", 2024)


def test_resolve_event_distinct_similar_names_not_ambiguous(sample_schedule):
    # "Australian" is textually close to a hypothetical "Austrian" but
    # there's only one candidate here, and it's an exact substring match -
    # this must resolve cleanly, not be flagged ambiguous just because
    # fuzzy ratios to other unrelated events happen to be nontrivial.
    resolved = resolve_event(sample_schedule, "Australian Grand Prix", 2024)
    assert resolved.event_name == "Australian Grand Prix"
