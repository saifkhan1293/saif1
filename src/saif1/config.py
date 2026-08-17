"""Project-wide configuration for SAIF1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache"

# FastF1 session-type identifiers as accepted by fastf1.get_session().
VALID_SESSION_TYPES = {"FP1", "FP2", "FP3", "Q", "S", "SQ", "R"}


@dataclass(frozen=True)
class SessionRequest:
    """Identifies a single F1 session to load.

    Attributes:
        year: Championship year, e.g. 2024.
        event: Event name or round identifier, e.g. "Bahrain Grand Prix".
            Matched against FastF1's event schedule, which uses fuzzy
            matching - see saif1.data.loader for how mismatches are surfaced.
        session_type: One of VALID_SESSION_TYPES. Defaults to "R" (Race).
    """

    year: int
    event: str
    session_type: str = "R"

    def __post_init__(self) -> None:
        if self.session_type.upper() not in VALID_SESSION_TYPES:
            raise ValueError(
                f"Unknown session_type '{self.session_type}'. "
                f"Expected one of: {sorted(VALID_SESSION_TYPES)}"
            )
