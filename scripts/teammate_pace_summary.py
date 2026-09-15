#!/usr/bin/env python
"""Season-long teammate representative_race_pace head-to-head.

The first deliverable of saif1.aggregation - a cross-race finding that
cannot be produced from any single persisted session file. See
aggregation.teammate_pace_head_to_head for the full method and its
constraints (zero-usable-lap handling, mid-season driver changes treated
as separate pairings, etc).

Usage:
    python scripts/teammate_pace_summary.py --year 2024
    python scripts/teammate_pace_summary.py --year 2024 --session S
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from saif1.aggregation import load_season_index, teammate_pace_head_to_head  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Season-long teammate pace head-to-head.")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--session", type=str, default="R", help="Session type (default: R)")
    return parser.parse_args(argv)


def _describe_gap(r: dict) -> str:
    """Self-describing margin - names the faster driver, positive
    magnitude. The internal (driver_b - driver_a) signed convention is
    useful programmatically (see aggregation.teammate_pace_head_to_head's
    median_gap_s) but unreadable in output without knowing that
    convention - never print the bare signed value.
    """
    gap = r["median_gap_s"]
    if gap is None:
        return "n/a"
    if gap > 0:
        return f"{r['driver_a']} faster by {gap:.3f}s"
    if gap < 0:
        return f"{r['driver_b']} faster by {abs(gap):.3f}s"
    return "even"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    index = load_season_index(args.year, args.session)
    print(f"Loaded {len(index)} {args.year} {args.session} session(s), "
          f"methodology_version={index.methodology_version}\n")

    results = teammate_pace_head_to_head(index)
    if not results:
        print("No teammate pairings found.")
        return 0

    print(f"{'Team':<25} {'Wins (representative_race_pace)':<20} {'Margin':<24} {'Compared':>8} {'No data':>8}")
    for r in results:
        matchup = f"{r['driver_a']} {r['driver_a_faster']}-{r['driver_b_faster']} {r['driver_b']}"
        print(
            f"{r['team']:<25} {matchup:<20} {_describe_gap(r):<24} "
            f"{r['races_compared']:>8} {r['races_no_data']:>8}"
        )

    print(
        "\nSame car, different circumstances. This compares teammates in identical\n"
        "machinery, which controls for the car - but not for the race. Track position\n"
        "(the faster driver often runs in cleaner air) and strategy divergence\n"
        "(different pit timing means different fuel loads/tyre ages at a given lap)\n"
        "both still contribute to every gap above. A count and a magnitude describe\n"
        "what happened; neither isolates driver capability from circumstance."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
