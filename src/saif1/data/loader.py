"""Session loading from FastF1, wrapped with clear error handling.

FastF1 itself is tolerant of bad input in ways that can silently produce
the wrong data (e.g. it fuzzy-matches unrecognized event names to the
closest known event instead of raising an error). This module adds the
validation and logging needed to catch that before it reaches analysis
code.
"""

from __future__ import annotations

import logging

import fastf1
from fastf1.core import Session

from saif1.config import SessionRequest
from saif1.data.cache import enable_cache
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
        session = fastf1.get_session(request.year, request.event, request.session_type)
    except Exception as exc:
        raise SessionNotFoundError(
            f"Could not resolve session: {request.year} '{request.event}' "
            f"({request.session_type}). Underlying error: {exc}"
        ) from exc

    resolved_name = session.event.get("EventName", request.event)
    if request.event.strip().lower() not in resolved_name.strip().lower():
        logger.warning(
            "Requested event '%s' did not match exactly - FastF1 resolved "
            "it to '%s'. Verify this is the intended race before trusting "
            "the results.",
            request.event,
            resolved_name,
        )

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
