"""Tyre stint extraction: per-driver, per-stint compound and lap range."""

from __future__ import annotations

from typing import Optional

import pandas as pd
from fastf1.core import Laps

from saif1.config import UNRECOGNIZED_COMPOUND, normalize_compound
from saif1.exceptions import DriverNotFoundError

# Fallback stint compound when literally no Compound data was recorded at
# all for the stint (every lap's value is NaN). Deliberately reuses the
# same "UNKNOWN" value FastF1 itself uses when it can't identify a
# compound (see KNOWN_TYRE_COMPOUNDS in config.py) - both mean "nobody
# knows the compound", just from a different cause (no data vs. FastF1
# explicitly saying so), and that distinction isn't preserved here. What
# IS always distinguished is UNRECOGNIZED_COMPOUND (data was present but
# not a known value at all, e.g. corrupted data) - never silently folded
# into "UNKNOWN".
NO_COMPOUND_DATA = "UNKNOWN"


def extract_stints(laps: Laps, driver: Optional[str] = None) -> list[dict]:
    """Extract tyre stints (compound + lap range) from lap data.

    Args:
        laps: Full session Laps (e.g. session.laps).
        driver: If given, restrict to this driver only.

    Returns:
        List of dicts, one per stint, ordered by driver then stint number:
        {
            "driver": str,
            "stint_number": int,
            "compound": str,  # a real compound name, "UNKNOWN" (no data,
                               # or FastF1 itself doesn't know), or
                               # "UNRECOGNIZED" (data present but not a
                               # known value) - see config.normalize_compound
            "start_lap": int,
            "end_lap": int,
            "stint_length": int,
            "lap_times_s": list[float],  # lap-number order, missing dropped
        }

    Raises:
        DriverNotFoundError: If `driver` is given but has no laps.
    """
    subset = laps
    if driver is not None:
        subset = laps.pick_drivers([driver])
        if subset.empty:
            raise DriverNotFoundError(f"No lap data found for driver '{driver}'.")

    stints: list[dict] = []
    for (drv, stint_num), stint_laps in subset.groupby(["Driver", "Stint"]):
        if pd.isna(stint_num):
            continue

        stint_laps = stint_laps.sort_values("LapNumber")
        normalized_compounds = stint_laps["Compound"].apply(normalize_compound).dropna().unique()
        known_compounds = [c for c in normalized_compounds if c != UNRECOGNIZED_COMPOUND]
        if known_compounds:
            compound = known_compounds[0]
        elif len(normalized_compounds):
            # Every lap's Compound was present but none recognized.
            compound = UNRECOGNIZED_COMPOUND
        else:
            # No Compound data recorded at all for this stint.
            compound = NO_COMPOUND_DATA
        lap_times_s = stint_laps["LapTime"].dropna().dt.total_seconds().tolist()

        stints.append(
            {
                "driver": drv,
                "stint_number": int(stint_num),
                "compound": compound,
                "start_lap": int(stint_laps["LapNumber"].min()),
                "end_lap": int(stint_laps["LapNumber"].max()),
                "stint_length": int(len(stint_laps)),
                "lap_times_s": lap_times_s,
            }
        )

    stints.sort(key=lambda s: (s["driver"], s["stint_number"]))
    return stints
