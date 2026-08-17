#!/usr/bin/env python
"""CLI entry point for running SAIF1 Phase 1 analysis on a single session.

Usage:
    python scripts/analyze_race.py --year 2024 --event "Bahrain Grand Prix" --session R
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running this script directly (python scripts/analyze_race.py)
# without having installed the package first.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from saif1.analysis.pace import calculate_green_flag_pace, calculate_race_pace, compare_driver_pace  # noqa: E402
from saif1.analysis.stints import extract_stints  # noqa: E402
from saif1.analysis.strategy import extract_pit_stops, position_changes  # noqa: E402
from saif1.analysis.tyres import compound_performance  # noqa: E402
from saif1.config import SessionRequest  # noqa: E402
from saif1.data.loader import load_session  # noqa: E402
from saif1.exceptions import SAIF1Error  # noqa: E402
from saif1.persistence import DEFAULT_RESULTS_DIR, build_session_result, save_result  # noqa: E402
from saif1.visualization.charts import (  # noqa: E402
    plot_driver_pace_comparison,
    plot_lap_time_progression,
    plot_pit_stop_timeline,
    plot_position_progression,
    plot_tyre_stints,
)

logger = logging.getLogger("saif1.analyze_race")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SAIF1 Phase 1 analysis on one F1 session.")
    parser.add_argument("--year", type=int, required=True, help="Championship year, e.g. 2024")
    parser.add_argument("--event", type=str, required=True, help='Event name, e.g. "Bahrain Grand Prix"')
    parser.add_argument(
        "--session", type=str, default="R", help="Session type: FP1/FP2/FP3/Q/S/SQ/R (default: R)"
    )
    parser.add_argument(
        "--drivers",
        type=str,
        default=None,
        help="Comma-separated driver codes to focus on, e.g. VER,HAM (default: top 6 finishers)",
    )
    parser.add_argument(
        "--output-dir", type=str, default="analysis_output", help="Directory to save charts into"
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        default=str(DEFAULT_RESULTS_DIR),
        help="Directory to save the persisted JSON result into (default: data/results)",
    )
    parser.add_argument("--log-level", type=str, default="INFO")
    return parser.parse_args(argv)


def _fmt_seconds(value: float | None) -> str:
    return f"{value:.3f}s" if value is not None else "N/A"


def _configure_logging(level: str) -> None:
    """Configure logging for saif1's own loggers only.

    FastF1 configures its own handlers on import (producing the
    "core INFO ..." style lines). Using logging.basicConfig() here would
    attach a second handler to the root logger and double-print every
    FastF1 log line, so saif1's messages get their own handler instead.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    saif1_logger = logging.getLogger("saif1")
    saif1_logger.setLevel(level)
    saif1_logger.addHandler(handler)
    saif1_logger.propagate = False


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _configure_logging(args.log_level)

    request = SessionRequest(year=args.year, event=args.event, session_type=args.session.upper())

    try:
        session = load_session(request)
    except SAIF1Error as exc:
        logger.error(str(exc))
        return 1

    laps = session.laps

    if args.drivers:
        drivers = [d.strip().upper() for d in args.drivers.split(",")]
    else:
        finish_order = session.results.sort_values("Position")
        drivers = finish_order["Abbreviation"].dropna().head(6).tolist()

    print(f"\n=== {request.year} {session.event['EventName']} ({request.session_type}) ===")
    print(f"Drivers in focus: {', '.join(drivers)}\n")

    print("--- Race pace (representative_race_pace policy: excludes deleted/inaccurate/pit ---")
    print("--- laps and Safety Car/VSC/red-flag laps; keeps yellow-flagged laps) ---")
    for driver in drivers:
        try:
            stats = calculate_race_pace(laps, driver)
        except SAIF1Error as exc:
            logger.warning(str(exc))
            continue
        print(
            f"{driver}: median={_fmt_seconds(stats['median_lap_time_s'])} "
            f"mean={_fmt_seconds(stats['mean_lap_time_s'])} "
            f"best={_fmt_seconds(stats['best_lap_time_s'])} "
            f"usable_laps={stats['usable_laps']}/{stats['total_laps']}"
        )

    print("\n--- Race pace (green_flag_pace policy: additionally excludes any ---")
    print("--- yellow-flagged lap - strictest tier, smaller sample) ---")
    for driver in drivers:
        try:
            stats = calculate_green_flag_pace(laps, driver)
        except SAIF1Error as exc:
            logger.warning(str(exc))
            continue
        print(
            f"{driver}: median={_fmt_seconds(stats['median_lap_time_s'])} "
            f"usable_laps={stats['usable_laps']}/{stats['total_laps']}"
        )

    if len(drivers) >= 2:
        print("\n--- Head-to-head pace (first two focus drivers) ---")
        comparison = compare_driver_pace(laps, drivers[0], drivers[1])
        print(
            f"{comparison['driver_1']} vs {comparison['driver_2']}: "
            f"median pace diff = {_fmt_seconds(comparison['median_pace_difference_s'])} "
            f"(positive = driver_1 slower)"
        )

    print("\n--- Tyre stints ---")
    stints = extract_stints(laps)
    for stint in (s for s in stints if s["driver"] in drivers):
        print(
            f"{stint['driver']} stint {stint['stint_number']}: {stint['compound']} "
            f"laps {stint['start_lap']}-{stint['end_lap']} ({stint['stint_length']} laps)"
        )

    print("\n--- Compound performance (session-wide) ---")
    for comp in compound_performance(laps):
        print(f"{comp['compound']}: median={_fmt_seconds(comp['median_lap_time_s'])} over {comp['usable_laps']} laps")

    print("\n--- Pit stops ---")
    pit_stops = extract_pit_stops(laps)
    for stop in (p for p in pit_stops if p["driver"] in drivers):
        duration = _fmt_seconds(stop["pit_lane_time_s"])
        print(
            f"{stop['driver']} lap {stop['in_lap']}: "
            f"{stop['compound_before']} -> {stop['compound_after']} "
            f"({duration} pit lane time)"
        )

    print("\n--- Position changes (grid -> finish) ---")
    for change in position_changes(session):
        if change["driver"] not in drivers:
            continue
        gained = change["positions_gained"]
        gained_str = f"{gained:+d}" if gained is not None else "N/A"
        print(
            f"{change['driver']}: P{change['start_position']} -> "
            f"P{change['finish_position']} ({gained_str}) [{change['status']}]"
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    charts = {
        "lap_time_progression.png": plot_lap_time_progression(laps, drivers),
        "pace_comparison.png": plot_driver_pace_comparison(laps, drivers),
        "tyre_stints.png": plot_tyre_stints(stints, drivers),
        "position_progression.png": plot_position_progression(laps, drivers),
        "pit_stop_timeline.png": plot_pit_stop_timeline(pit_stops, drivers),
    }
    print()
    for filename, fig in charts.items():
        path = output_dir / filename
        fig.savefig(path, dpi=150)
        print(f"Saved chart: {path}")

    result = build_session_result(session, request)
    result_path = save_result(result, output_dir=Path(args.results_dir))
    size_kb = result_path.stat().st_size / 1024
    print(f"Saved persisted result: {result_path} ({size_kb:.1f} KB)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
