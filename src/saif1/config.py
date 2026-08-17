"""Project-wide configuration for SAIF1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache"

# FastF1 session-type identifiers as accepted by fastf1.get_session().
VALID_SESSION_TYPES = {"FP1", "FP2", "FP3", "Q", "S", "SQ", "R"}

# Every Compound value FastF1 is known to emit, determined empirically -
# NOT hand-written from assumption - by reading fastf1.plotting's own
# per-season Constants[year].compound_colors keys for every year FastF1
# defines them (2018-2025 at time of writing), then cross-checked by
# loading real sessions across compound-naming eras: 2018 Monaco/Abu Dhabi
# (HYPERSOFT/SUPERSOFT/ULTRASOFT), 2018/2019 German GP (wet races, for
# INTERMEDIATE/WET), and 2021/2024 Bahrain (current SOFT/MEDIUM/HARD
# naming). "UNKNOWN" and "TEST-UNKNOWN" are genuine FastF1-emitted values
# (FastF1 itself reporting it doesn't know the compound), not errors -
# see normalize_compound() below for how a truly-unrecognized value (e.g.
# the literal string "None", observed in real 2023 Canadian GP data) is
# distinguished from these.
KNOWN_TYRE_COMPOUNDS = {
    "SOFT", "MEDIUM", "HARD",  # current era (2019+) relative naming
    "HYPERSOFT", "ULTRASOFT", "SUPERSOFT", "SUPERHARD",  # 2018 absolute naming
    "INTERMEDIATE", "WET",
    "UNKNOWN", "TEST-UNKNOWN",  # FastF1's own "don't know" sentinels
}

# The subset of KNOWN_TYRE_COMPOUNDS that represents an actual physical
# tyre choice, for analyses that rank/compare compound pace - UNKNOWN and
# TEST-UNKNOWN are legitimate FastF1 values but not a "compound" in that
# sense, so they're excluded from pace ranking without being treated as
# unrecognized/invalid data.
RANKABLE_COMPOUNDS = KNOWN_TYRE_COMPOUNDS - {"UNKNOWN", "TEST-UNKNOWN"}

# Sentinel for a non-null Compound value that isn't in KNOWN_TYRE_COMPOUNDS
# at all - i.e. SAIF1 doesn't recognize it, as opposed to FastF1 reporting
# it doesn't know (that's "UNKNOWN"/"TEST-UNKNOWN", both real FastF1
# values passed through unchanged). Never invented from missing data - see
# normalize_compound().
UNRECOGNIZED_COMPOUND = "UNRECOGNIZED"


def normalize_compound(value) -> Optional[str]:
    """Validate a raw Compound value against FastF1's known vocabulary.

    Returns:
        The value unchanged if it's a real FastF1 compound (including its
        own "UNKNOWN"/"TEST-UNKNOWN" sentinels), UNRECOGNIZED_COMPOUND if
        a non-null value is present but not recognized (e.g. corrupted
        data), or None if the value is genuinely missing (NaN).
    """
    if pd.isna(value):
        return None
    if value in KNOWN_TYRE_COMPOUNDS:
        return value
    return UNRECOGNIZED_COMPOUND


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
