"""Matplotlib visualizations for race analysis.

Charts take already-loaded FastF1 objects (Laps / Session) plus the
structured outputs from saif1.analysis, and return a Matplotlib Figure so
callers can display or save it as needed. These functions never call
plt.show() or plt.savefig() themselves.
"""

from __future__ import annotations

from typing import Sequence

import matplotlib.pyplot as plt
from fastf1.core import Laps

# Approximate 2024+ Pirelli compound colors, used as a visual convention
# only - not sourced from any official F1 branding assets.
COMPOUND_COLORS = {
    "SOFT": "#DA291C",
    "MEDIUM": "#FFD12E",
    "HARD": "#F0F0EC",
    "INTERMEDIATE": "#43B02A",
    "WET": "#0067AD",
    "UNKNOWN": "#888888",
}


def plot_lap_time_progression(laps: Laps, drivers: Sequence[str]) -> plt.Figure:
    """Line chart of lap time vs. lap number for the given drivers."""
    fig, ax = plt.subplots(figsize=(11, 6))

    for driver in drivers:
        driver_laps = laps.pick_drivers([driver]).sort_values("LapNumber")
        lap_times = driver_laps["LapTime"].dt.total_seconds()
        ax.plot(driver_laps["LapNumber"], lap_times, marker="o", markersize=3, label=driver)

    ax.set_xlabel("Lap")
    ax.set_ylabel("Lap Time (s)")
    ax.set_title("Lap Time Progression")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def plot_driver_pace_comparison(laps: Laps, drivers: Sequence[str]) -> plt.Figure:
    """Box plot comparing race-pace distribution across drivers."""
    fig, ax = plt.subplots(figsize=(9, 6))

    data = []
    tick_labels = []
    for driver in drivers:
        driver_laps = laps.pick_drivers([driver])
        lap_times = driver_laps["LapTime"].dropna().dt.total_seconds()
        if lap_times.empty:
            continue
        data.append(lap_times)
        tick_labels.append(driver)

    ax.boxplot(data, tick_labels=tick_labels, showfliers=False)
    ax.set_ylabel("Lap Time (s)")
    ax.set_title("Race Pace Comparison")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    return fig


def plot_tyre_stints(stints: list[dict], drivers: Sequence[str]) -> plt.Figure:
    """Horizontal bar chart of tyre stints per driver, colored by compound."""
    fig, ax = plt.subplots(figsize=(11, max(4, len(drivers) * 0.4)))

    for i, driver in enumerate(drivers):
        for stint in (s for s in stints if s["driver"] == driver):
            color = COMPOUND_COLORS.get(stint["compound"], COMPOUND_COLORS["UNKNOWN"])
            ax.barh(
                i,
                stint["stint_length"],
                left=stint["start_lap"] - 1,
                color=color,
                edgecolor="black",
                linewidth=0.5,
            )

    ax.set_yticks(range(len(drivers)))
    ax.set_yticklabels(drivers)
    ax.set_xlabel("Lap")
    ax.set_title("Tyre Stints")
    ax.invert_yaxis()
    fig.tight_layout()
    return fig


def plot_position_progression(laps: Laps, drivers: Sequence[str]) -> plt.Figure:
    """Line chart of race position vs. lap number for the given drivers."""
    fig, ax = plt.subplots(figsize=(11, 6))

    for driver in drivers:
        driver_laps = laps.pick_drivers([driver]).sort_values("LapNumber")
        ax.plot(
            driver_laps["LapNumber"],
            driver_laps["Position"],
            marker="o",
            markersize=3,
            label=driver,
        )

    ax.set_xlabel("Lap")
    ax.set_ylabel("Position")
    ax.set_title("Position Progression")
    ax.invert_yaxis()
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    return fig


def plot_pit_stop_timeline(pit_stops: list[dict], drivers: Sequence[str]) -> plt.Figure:
    """Scatter timeline of pit stops per driver by lap."""
    fig, ax = plt.subplots(figsize=(11, max(4, len(drivers) * 0.4)))

    driver_index = {driver: i for i, driver in enumerate(drivers)}
    for stop in pit_stops:
        if stop["driver"] not in driver_index:
            continue
        ax.scatter(stop["in_lap"], driver_index[stop["driver"]], color="#DA291C", zorder=3)

    ax.set_yticks(range(len(drivers)))
    ax.set_yticklabels(drivers)
    ax.set_xlabel("Lap")
    ax.set_title("Pit Stop Timeline")
    ax.invert_yaxis()
    ax.grid(alpha=0.3, axis="x")
    fig.tight_layout()
    return fig
