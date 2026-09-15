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


def test_resolve_event_same_country_multiple_races_resolved_by_exact_eventname():
    # Real 2024 failure: "United States Grand Prix" substring-matched
    # Miami, United States, and Las Vegas GPs (all Country="United States"
    # or "USA") before EventName got exact-match precedence. All three
    # share a country here too, reproducing the actual condition.
    schedule = _schedule(
        [
            {
                "RoundNumber": 6, "EventName": "Miami Grand Prix",
                "OfficialEventName": "FORMULA 1 MIAMI GRAND PRIX 2024",
                "Location": "Miami", "Country": "United States",
                "EventDate": pd.Timestamp("2024-05-05"),
            },
            {
                "RoundNumber": 19, "EventName": "United States Grand Prix",
                "OfficialEventName": "FORMULA 1 UNITED STATES GRAND PRIX 2024",
                "Location": "Austin", "Country": "United States",
                "EventDate": pd.Timestamp("2024-10-20"),
            },
            {
                "RoundNumber": 22, "EventName": "Las Vegas Grand Prix",
                "OfficialEventName": "FORMULA 1 LAS VEGAS GRAND PRIX 2024",
                "Location": "Las Vegas", "Country": "United States",
                "EventDate": pd.Timestamp("2024-11-23"),
            },
        ]
    )
    resolved = resolve_event(schedule, "United States Grand Prix", 2024)
    assert resolved.round_number == 19
    assert resolved.event_name == "United States Grand Prix"


def test_resolve_event_sponsor_polluted_official_name_resolved_by_exact_eventname():
    # Real 2024 failure: "Qatar Grand Prix" substring-matched four events
    # because their OfficialEventName carries "Qatar Airways" sponsor
    # branding. Reproduced here with two sponsor-polluted decoys plus the
    # real Qatar GP.
    schedule = _schedule(
        [
            {
                "RoundNumber": 11, "EventName": "Austrian Grand Prix",
                "OfficialEventName": "FORMULA 1 QATAR AIRWAYS AUSTRIAN GRAND PRIX 2024",
                "Location": "Spielberg", "Country": "Austria",
                "EventDate": pd.Timestamp("2024-06-30"),
            },
            {
                "RoundNumber": 12, "EventName": "British Grand Prix",
                "OfficialEventName": "FORMULA 1 QATAR AIRWAYS BRITISH GRAND PRIX 2024",
                "Location": "Silverstone", "Country": "United Kingdom",
                "EventDate": pd.Timestamp("2024-07-07"),
            },
            {
                "RoundNumber": 23, "EventName": "Qatar Grand Prix",
                "OfficialEventName": "FORMULA 1 QATAR AIRWAYS QATAR GRAND PRIX 2024",
                "Location": "Lusail", "Country": "Qatar",
                "EventDate": pd.Timestamp("2024-12-01"),
            },
        ]
    )
    resolved = resolve_event(schedule, "Qatar Grand Prix", 2024)
    assert resolved.round_number == 23
    assert resolved.event_name == "Qatar Grand Prix"


def test_resolve_event_genuine_location_country_ambiguity_still_raises():
    # Required property: "Spa" exact-matches nothing (Location is the full
    # "Spa-Francorchamps", Country is "Belgium"), so it must fall through
    # to substring matching - where it hits both Spa-Francorchamps
    # (Location, via substring) and Spain (Country, via substring, since
    # "spa" is a prefix of "spain") - and must still raise, not silently
    # pick one. Fixing the two real failures above must not weaken this.
    schedule = _schedule(
        [
            {
                "RoundNumber": 14, "EventName": "Belgian Grand Prix",
                "OfficialEventName": "FORMULA 1 BELGIAN GRAND PRIX 2024",
                "Location": "Spa-Francorchamps", "Country": "Belgium",
                "EventDate": pd.Timestamp("2024-07-28"),
            },
            {
                "RoundNumber": 10, "EventName": "Spanish Grand Prix",
                "OfficialEventName": "FORMULA 1 SPANISH GRAND PRIX 2024",
                "Location": "Barcelona", "Country": "Spain",
                "EventDate": pd.Timestamp("2024-06-23"),
            },
        ]
    )
    with pytest.raises(SessionNotFoundError, match="multiple"):
        resolve_event(schedule, "Spa", 2024)
