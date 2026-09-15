"""Deterministic cross-session aggregation over persisted results.

Consumes persisted JSON produced by persistence.py - reads structured,
already-computed results and combines them across sessions. Adds no new
raw-data analysis of its own; every number here is a combination of
numbers persistence.py already computed. Sits above persistence in the
architecture: raw data -> deterministic analysis -> persisted structured
results -> aggregation (this module) -> API/frontend/agent/content.

Deliberately small and single-purpose for its first version - one
cross-race finding (teammate_pace_head_to_head), not a general query
framework. Extend by adding more such focused functions over SeasonIndex
as real questions arise, not by generalizing this into a query engine
ahead of a second question that actually needs one.

Built only after a full season (2024, 33 sessions) was persisted and its
data quality checked at scale - see README "Data quality & assumptions".
The constraints below are direct consequences of what that batch found,
not precautions taken in the abstract:

- Season is always an explicit parameter, never inferred from whatever
  happens to be on disk - data/results/ holds three different seasons
  (2023, 2024, 2026) at once, and there is no reliable way to guess which
  one a caller meant.
- Race and Sprint sessions are never pooled by default - the batch found
  5 of 2024's 6 Sprints had representative_race_pace identical to
  green_flag_pace, a very different mix from Race sessions, evidence the
  two session types behave differently enough that silently combining
  them would blur a real distinction.
- Drivers with zero usable pace data for a session (see
  lap_exclusions[].policies.*.retained_laps) are excluded from pace
  comparisons for that session explicitly, never treated as a zero or
  infinitely slow lap time and never silently dropped without being
  counted somewhere.
- Every loaded file's provenance.saif1_methodology_version is checked;
  aggregating across differing methodology versions would combine numbers
  computed under different rules into one meaningless average, so
  load_season_index refuses instead.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from saif1.exceptions import SAIF1Error
from saif1.persistence import DEFAULT_RESULTS_DIR

logger = logging.getLogger(__name__)


class MethodologyMismatchError(SAIF1Error):
    """Raised when persisted results being loaded together were computed
    under different methodology versions - aggregating across
    incompatible analytical rules would silently produce a meaningless
    number instead of an obviously wrong one."""


@dataclass(frozen=True)
class SeasonIndex:
    """A season's worth of persisted results for one session type, loaded
    once and held in memory for reuse across multiple aggregation
    questions - re-parsing the directory per question is how you
    convince yourself you need a database before you actually do (the
    full 2024+2023+2026 directory is 5.25 MB and parses in about a
    second).

    Never built implicitly: always for one explicit year and one explicit
    session_type. Race and Sprint are never combined into one index - a
    caller that genuinely wants both loads two indexes and says so.
    """

    year: int
    session_type: str
    methodology_version: str
    results: list[dict] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.results)


def load_season_index(
    year: int,
    session_type: str,
    results_dir: Path = DEFAULT_RESULTS_DIR,
) -> SeasonIndex:
    """Load every persisted result for one season and one session type
    into memory.

    Args:
        year: Championship year - explicit, never inferred from what's on
            disk.
        session_type: e.g. "R" or "S" - explicit, never pooled with any
            other session type by this function.
        results_dir: Where persisted results live.

    Returns:
        A SeasonIndex holding every matching result, loaded once.

    Raises:
        MethodologyMismatchError: If the loaded files were computed under
            more than one saif1_methodology_version.
    """
    results_dir = Path(results_dir)
    results: list[dict] = []
    versions: set[str] = set()

    for path in sorted(results_dir.glob(f"{year}_*_{session_type}.json")):
        with open(path, encoding="utf-8") as f:
            result = json.load(f)
        # Filename pattern matched, but verify the content actually
        # agrees before trusting it - the filename is a hint, not a
        # guarantee (see persistence.result_filename's slug derivation).
        if (
            result["session"]["year"] != year
            or result["session"]["session_type"] != session_type
        ):
            logger.warning(
                "Skipping %s: filename suggests %s %s but content says %s %s",
                path.name, year, session_type,
                result["session"]["year"], result["session"]["session_type"],
            )
            continue
        versions.add(result["provenance"]["saif1_methodology_version"])
        results.append(result)

    if len(versions) > 1:
        raise MethodologyMismatchError(
            f"{year} {session_type} results were computed under multiple "
            f"methodology versions: {sorted(versions)}. Regenerate the "
            f"older files (python scripts/persist_season.py --year "
            f"{year} --session {session_type}, without --skip-existing) "
            f"before aggregating."
        )

    methodology_version = next(iter(versions)) if versions else "unknown"
    logger.info(
        "Loaded %d %s %s result(s), methodology_version=%s",
        len(results), year, session_type, methodology_version,
    )
    return SeasonIndex(
        year=year, session_type=session_type,
        methodology_version=methodology_version, results=results,
    )


def teammate_pace_head_to_head(index: SeasonIndex) -> list[dict]:
    """Season-long representative_race_pace head-to-head between
    teammates, race by race.

    For each session in `index`, drivers sharing the same `team` (from
    that session's drivers[]) are compared on
    race_pace.representative_race_pace's median_lap_time_s - the
    "answer", not the "check" (see README "Data quality & assumptions"
    for why representative_race_pace, not green_flag_pace, is the right
    metric for this).

    A driver with usable_laps == 0 for a session (no meaningful pace to
    compare - see lap_exclusions) makes that session a "no_data" result
    for the pairing, never a zero or infinitely slow lap time and never
    silently dropped without being counted. A session where a team fields
    other than exactly two drivers (e.g. a mid-season reserve
    appearance alongside both regular drivers) is skipped entirely for
    that team in that session, not arbitrarily paired.

    A driver pairing is keyed by (team, sorted driver codes) - a
    mid-season teammate change (e.g. a reserve driver taking over a seat)
    produces a separate pairing entry rather than being merged into one,
    since "driver A vs driver B" and "driver A vs driver C" are different
    comparisons.

    Args:
        index: A SeasonIndex, typically for session_type="R" - see the
            module docstring for why Sprint/Race should not be pooled
            into one index before calling this.

    Returns:
        List of dicts, one per (team, driver_a, driver_b) pairing that
        appeared together at least once, sorted by driver_a's net
        win margin descending:
        {
            "team": str,
            "driver_a": str, "driver_b": str,
            "races_compared": int,   # both had usable pace data
            "driver_a_faster": int,  # lower median_lap_time_s
            "driver_b_faster": int,
            "races_no_data": int,    # one or both had 0 usable laps
        }
    """
    pairings: dict[tuple[str, str, str], dict] = {}
    skipped_non_two_driver_team_sessions = 0

    for result in index.results:
        pace_by_driver = {
            p["driver"]: p for p in result["race_pace"]["representative_race_pace"]
        }
        drivers_by_team: dict[str, list[str]] = {}
        for driver_entry in result["drivers"]:
            drivers_by_team.setdefault(driver_entry["team"], []).append(driver_entry["driver"])

        for team, drivers in drivers_by_team.items():
            if len(drivers) != 2:
                skipped_non_two_driver_team_sessions += 1
                continue

            driver_a, driver_b = sorted(drivers)
            key = (team, driver_a, driver_b)
            pairing = pairings.setdefault(
                key,
                {
                    "team": team, "driver_a": driver_a, "driver_b": driver_b,
                    "races_compared": 0, "driver_a_faster": 0, "driver_b_faster": 0,
                    "races_no_data": 0,
                },
            )

            pace_a = pace_by_driver.get(driver_a)
            pace_b = pace_by_driver.get(driver_b)
            if not pace_a or not pace_b or pace_a["usable_laps"] == 0 or pace_b["usable_laps"] == 0:
                pairing["races_no_data"] += 1
                continue

            pairing["races_compared"] += 1
            if pace_a["median_lap_time_s"] < pace_b["median_lap_time_s"]:
                pairing["driver_a_faster"] += 1
            elif pace_b["median_lap_time_s"] < pace_a["median_lap_time_s"]:
                pairing["driver_b_faster"] += 1
            # Exactly equal medians: neither incremented (rare, deterministic tie).

    if skipped_non_two_driver_team_sessions:
        logger.info(
            "Skipped %d team-session(s) with other than exactly 2 drivers",
            skipped_non_two_driver_team_sessions,
        )

    results = list(pairings.values())
    results.sort(key=lambda r: r["driver_a_faster"] - r["driver_b_faster"], reverse=True)
    return results
