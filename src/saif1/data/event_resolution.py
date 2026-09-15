"""Deterministic, confidence-gated event-name resolution.

FastF1's own event matching (used internally by ``fastf1.get_session``)
fuzzy-matches any input string against a season's schedule and always
returns its single best guess, however poor - it only logs a warning when
the match wasn't a precise one. A missed log line means silently
analyzing the wrong Grand Prix.

This module resolves an event name against the same underlying fields
FastF1 uses (event name, official name, location, country) but adds an
explicit confidence gate: a query must be an unambiguous match against
exactly one event to be accepted. Anything else (no match, or a match
against more than one event) raises a clear, catchable error instead of
silently proceeding.

Resolution is two-tiered:

1. EXACT match, tried against EventName, then Location, then Country, in
   that precedence order. The first tier with exactly one exact match
   wins immediately. OfficialEventName is deliberately excluded from this
   tier - it is the field most likely to carry sponsor branding (e.g. a
   season where several unrelated events' OfficialEventName contains
   "Qatar Airways" as a title sponsor) and the least likely to be what a
   caller actually typed.
2. Only if no exact match exists at any of those three tiers, fall
   through to substring matching across all four fields (Location,
   Country, EventName, OfficialEventName), same as before - this is what
   lets "Silverstone" resolve the British Grand Prix, or "Spa" correctly
   stay ambiguous between Spa-Francorchamps (a Location) and Spain (a
   Country) rather than picking one silently.

This tiering was added after real 2024 season data surfaced two cases the
substring-only version got wrong: "United States Grand Prix" substring-
matched three same-country US races (Miami/Austin/Las Vegas) via the
Country field, and "Qatar Grand Prix" substring-matched four events
because several others' OfficialEventName carried "Qatar Airways" sponsor
text. Both are exact matches against the real event's EventName once that
tier is checked first.

Deliberately not built on ``fastf1.internals.fuzzy`` (an unstable,
explicitly "internal" module) - this is a small, self-contained
implementation using ``rapidfuzz`` directly (already a FastF1 dependency)
so behavior stays fully within our control and is unit-testable with
synthetic schedules, without any network access.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
from rapidfuzz import fuzz

from saif1.exceptions import SessionNotFoundError

logger = logging.getLogger(__name__)

# Words stripped before matching since they appear in almost every event
# name/official name and carry no distinguishing information.
_COMMON_WORDS = ("formula 1", "grand prix", "gp")

# Minimum rapidfuzz ratio (0-100) required to even mention a fuzzy
# "did you mean" suggestion in the error message. Below this, the best
# guess is too unrelated to be useful.
_SUGGESTION_MIN_RATIO = 40


@dataclass(frozen=True)
class ResolvedEvent:
    """The result of confidently resolving a user-supplied event string
    against one season's schedule."""

    round_number: int
    event_name: str
    official_event_name: str
    location: str
    country: str
    event_date: pd.Timestamp
    # The query was an unambiguous substring match against exactly one
    # event's Location/Country/EventName/OfficialEventName - not
    # necessarily an exact string match (e.g. "Bahrain GP" resolves this
    # way against "Bahrain Grand Prix"). Always True today; reserved for a
    # possible future non-strict mode that could set it False.
    matched_unambiguously: bool


def _normalize(text: str, year: int) -> str:
    text = text.casefold()
    for word in (*_COMMON_WORDS, str(year)):
        text = text.replace(word, "")
    return text.replace(" ", "").strip()


def _candidate_fields(row: pd.Series, year: int) -> list[str]:
    fields = []
    for col in ("Location", "Country"):
        value = row.get(col)
        if value:
            fields.append(_normalize(str(value), year))
    for col in ("EventName", "OfficialEventName"):
        value = row.get(col)
        if value:
            fields.append(_normalize(str(value), year))
    return fields


def resolve_event(schedule: pd.DataFrame, requested_event: str, year: int) -> ResolvedEvent:
    """Resolve `requested_event` against one season's event schedule.

    Args:
        schedule: A FastF1 EventSchedule (or any DataFrame with
            RoundNumber/EventName/OfficialEventName/Location/Country/
            EventDate columns), already filtered to `year`.
        requested_event: The event string as supplied by the caller, e.g.
            "Bahrain Grand Prix" or "Bahrain GP".
        year: Championship year. Used only to strip a redundant year
            token from the query (e.g. "2024 Bahrain Grand Prix").

    Returns:
        ResolvedEvent describing the single matching event.

    Raises:
        SessionNotFoundError: If the query is too generic to mean
            anything, matches no event with any confidence, or matches
            more than one event (ambiguous).
    """
    if schedule.empty:
        raise SessionNotFoundError(f"No event schedule available for {year}.")

    query = _normalize(requested_event, year)
    if not query:
        raise SessionNotFoundError(
            f"Event name '{requested_event}' is too generic to resolve - it "
            f"consists only of common words like 'Grand Prix'. Provide a "
            f"circuit, country, or event-specific name (e.g. 'Bahrain', "
            f"'Silverstone')."
        )

    # Tier 1: exact match, precedence EventName > Location > Country.
    # OfficialEventName is intentionally not part of this tier - see the
    # module docstring for why (sponsor-name pollution).
    for field_name in ("EventName", "Location", "Country"):
        exact_matches = [
            pos
            for pos in range(len(schedule))
            if (value := schedule.iloc[pos].get(field_name))
            and _normalize(str(value), year) == query
        ]
        if len(exact_matches) == 1:
            return _to_resolved_event(schedule.iloc[exact_matches[0]])
        if len(exact_matches) > 1:
            names = [schedule.iloc[i]["EventName"] for i in exact_matches]
            raise SessionNotFoundError(
                f"Event name '{requested_event}' matches multiple {year} events: "
                f"{', '.join(names)}. Use a more specific name to disambiguate."
            )
        # Zero exact matches at this tier - fall through to the next one.

    # Tier 2: no exact match anywhere - fall through to substring matching
    # across all four fields, same as before tiering was added.
    substring_matches: list[int] = []
    best_ratio = 0
    best_ratio_pos: int | None = None

    for pos in range(len(schedule)):
        row = schedule.iloc[pos]
        fields = _candidate_fields(row, year)
        if any(query in field for field in fields):
            substring_matches.append(pos)
        ratio = max((fuzz.ratio(query, field) for field in fields), default=0)
        if ratio > best_ratio:
            best_ratio, best_ratio_pos = ratio, pos

    if len(substring_matches) == 1:
        return _to_resolved_event(schedule.iloc[substring_matches[0]])

    if len(substring_matches) > 1:
        names = [schedule.iloc[i]["EventName"] for i in substring_matches]
        raise SessionNotFoundError(
            f"Event name '{requested_event}' matches multiple {year} events: "
            f"{', '.join(names)}. Use a more specific name to disambiguate."
        )

    # No substring match at all. Never silently accept a fuzzy guess here -
    # always fail, optionally with a "did you mean" hint built from the
    # same ratio computed above.
    message = (
        f"Could not confidently resolve event '{requested_event}' for "
        f"{year} season. No event name, location, or country matched."
    )
    if best_ratio_pos is not None and best_ratio >= _SUGGESTION_MIN_RATIO:
        best_guess = schedule.iloc[best_ratio_pos]["EventName"]
        message += f" Did you mean '{best_guess}'? (similarity: {best_ratio}/100)"
    message += " Check spelling, or use the exact event name from the FastF1/F1 schedule."

    raise SessionNotFoundError(message)


def _to_resolved_event(row: pd.Series) -> ResolvedEvent:
    return ResolvedEvent(
        round_number=int(row["RoundNumber"]),
        event_name=row["EventName"],
        official_event_name=row.get("OfficialEventName", row["EventName"]),
        location=row.get("Location", ""),
        country=row.get("Country", ""),
        event_date=row.get("EventDate"),
        matched_unambiguously=True,
    )
