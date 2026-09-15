#!/usr/bin/env python
"""Batch-persist every round of a season to data/results/.

Rationale (per the Phase 1.5 Senior Advisor review): before building the
agent, run the deterministic persistence pipeline against a full season's
worth of real variety so data-quality defects (like the tyre-compound
validation gap found via a single race) surface now rather than later. This
is a batch driver over the existing load_session -> build_session_result ->
save_result pipeline - it adds no new analysis logic of its own.

Skips chart generation (unlike scripts/analyze_race.py) since the goal here
is exercising the persistence layer at scale, not producing visuals for 24
races. One race failing does not stop the batch - failures are collected and
reported in the summary so a bad round is visible without losing the rest.

Usage:
    python scripts/persist_season.py --year 2024
    python scripts/persist_season.py --year 2024 --session Q --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fastf1  # noqa: E402

from saif1.config import SessionRequest  # noqa: E402
from saif1.data.cache import enable_cache  # noqa: E402
from saif1.data.loader import load_session  # noqa: E402
from saif1.exceptions import SAIF1Error  # noqa: E402
from saif1.persistence import DEFAULT_RESULTS_DIR, build_session_result, save_result  # noqa: E402

logger = logging.getLogger("saif1.persist_season")


def _configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    saif1_logger = logging.getLogger("saif1")
    saif1_logger.setLevel(level)
    saif1_logger.addHandler(handler)
    saif1_logger.propagate = False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch-persist every round of a season.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--session", type=str, default="R", help="Session type to persist for every round (default: R)"
    )
    parser.add_argument(
        "--results-dir", type=str, default=str(DEFAULT_RESULTS_DIR),
    )
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="Skip a round if its result file already exists (default: overwrite, per the existing regeneration design)",
    )
    parser.add_argument(
        "--rounds", type=str, default=None,
        help="Comma-separated round numbers to persist (default: every round in the schedule). "
        "Use for session types that don't apply to every round, e.g. Sprint weekends only.",
    )
    parser.add_argument("--log-level", type=str, default="WARNING")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.log_level)
    enable_cache()

    schedule = fastf1.get_event_schedule(args.year, include_testing=False)
    if args.rounds:
        wanted_rounds = {int(r.strip()) for r in args.rounds.split(",")}
        schedule = schedule[schedule["RoundNumber"].isin(wanted_rounds)]
    results_dir = Path(args.results_dir)

    succeeded: list[tuple[int, str, Path, float]] = []
    failed: list[tuple[int, str, str]] = []
    skipped: list[tuple[int, str]] = []

    total = len(schedule)
    for _, event in schedule.sort_values("RoundNumber").iterrows():
        round_number = int(event["RoundNumber"])
        event_name = event["EventName"]

        print(f"[{round_number:02d}] {event_name} ({args.session}, {total} in this batch) ...", flush=True)

        if args.skip_existing:
            already_persisted = list(
                results_dir.glob(f"{args.year}_{round_number:02d}_*_{args.session}.json")
            )
            if already_persisted:
                print(f"    SKIPPED (already exists: {already_persisted[0].name})", flush=True)
                skipped.append((round_number, event_name))
                continue

        request = SessionRequest(year=args.year, event=event_name, session_type=args.session)

        start = time.monotonic()
        try:
            session = load_session(request)
            result = build_session_result(session, request)
            path = save_result(result, output_dir=results_dir)
        except SAIF1Error as exc:
            elapsed = time.monotonic() - start
            print(f"    FAILED ({elapsed:.1f}s): {exc}", flush=True)
            failed.append((round_number, event_name, str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 - batch job must not die on one bad race
            elapsed = time.monotonic() - start
            print(f"    FAILED ({elapsed:.1f}s): unexpected {type(exc).__name__}: {exc}", flush=True)
            failed.append((round_number, event_name, f"{type(exc).__name__}: {exc}"))
            continue

        elapsed = time.monotonic() - start
        size_kb = path.stat().st_size / 1024
        print(f"    OK ({elapsed:.1f}s): {path.name} ({size_kb:.1f} KB)", flush=True)
        succeeded.append((round_number, event_name, path, elapsed))

    print(f"\n=== {args.year} {args.session} season batch complete ===")
    print(f"Succeeded: {len(succeeded)}/{len(schedule)}")
    print(f"Failed:    {len(failed)}/{len(schedule)}")
    if failed:
        print("\nFailures:")
        for round_number, event_name, error in failed:
            print(f"  [{round_number:02d}] {event_name}: {error}")
    if skipped:
        print("\nSkipped (already existed):")
        for round_number, event_name in skipped:
            print(f"  [{round_number:02d}] {event_name}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
