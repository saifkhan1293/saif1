"""Session loading from FastF1, wrapped with clear error handling.

FastF1 itself is tolerant of bad input in ways that can silently produce
the wrong data - its own event matching fuzzy-matches unrecognized event
names to the closest known event instead of raising an error, and only
logs a warning. This module resolves the requested event through
saif1.data.event_resolution first, which requires an unambiguous,
confident match before any session is loaded, then requests the session
by validated round number so FastF1's fuzzy matcher is never invoked.
"""

from __future__ import annotations

import logging

import fastf1
from fastf1.core import Session

from saif1.config import SessionRequest
from saif1.data.cache import enable_cache
from saif1.data.event_resolution import resolve_event
from saif1.exceptions import SessionNotFoundError

logger = logging.getLogger(__name__)


def load_session(
    request: SessionRequest,
    *,
    laps: bool = True,
    telemetry: bool = False,
    weather: bool = True,
    messages: bool = True,
) -> Session:
    """Load a completed F1 session via FastF1.

    Args:
        request: Identifies the year, event, and session type to load.
        laps: Whether to load lap-by-lap timing data.
        telemetry: Whether to load car telemetry. Defaults to False since
            it is large (tens of MB per session) and not required by the
            Phase 1 analytical functions, which work off lap-level data.
        weather: Whether to load weather data.
        messages: Whether to load race control messages (flags, penalties).

    Returns:
        A loaded fastf1.core.Session.

    Raises:
        SessionNotFoundError: If the event/session cannot be located, has
            not occurred yet, or FastF1 fails to load its data.
    """
    enable_cache()

    try:
        schedule = fastf1.get_event_schedule(request.year, include_testing=False)
    except Exception as exc:
        raise SessionNotFoundError(
            f"Could not load the {request.year} event schedule. Underlying "
            f"error: {exc}"
        ) from exc

    # Raises SessionNotFoundError itself on no/ambiguous match - resolution
    # must be unambiguous and confident before any session is requested.
    resolved = resolve_event(schedule, request.event, request.year)
    resolved_name = resolved.event_name

    try:
        session = fastf1.get_session(request.year, resolved.round_number, request.session_type)
    except Exception as exc:
        raise SessionNotFoundError(
            f"Could not resolve session: {request.year} round "
            f"{resolved.round_number} '{resolved_name}' ({request.session_type}). "
            f"Underlying error: {exc}"
        ) from exc

    try:
        session.load(laps=laps, telemetry=telemetry, weather=weather, messages=messages)
    except Exception as exc:
        raise SessionNotFoundError(
            f"Session data could not be loaded for {request.year} "
            f"'{resolved_name}' ({request.session_type}). This session may "
            f"not have occurred yet, or FastF1/F1 timing data is "
            f"unavailable for it. Underlying error: {exc}"
        ) from exc

    if not laps:
        return session

    if session.laps is None or session.laps.empty:
        raise SessionNotFoundError(
            f"Session {request.year} '{resolved_name}' ({request.session_type}) "
            "loaded but contains no lap data."
        )

    logger.info(
        "Loaded %s %s (%s): %d laps across %d drivers",
        request.year,
        resolved_name,
        request.session_type,
        len(session.laps),
        len(session.drivers),
    )
    return session
