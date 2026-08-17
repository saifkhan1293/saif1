# SAIF1

SAIF1 is an independent Formula 1 data, strategy, and performance analytics
platform. It is a personal/portfolio project and is **not affiliated with,
endorsed by, or connected to Formula 1, the FIA, Liberty Media, or any F1
team**.

## Vision

The long-term goal is an agentic F1 analyst that can investigate race data,
identify interesting performance and strategy events, test hypotheses
against real data, validate its own conclusions, and communicate findings
clearly:

```
F1 DATA → INGESTION → NORMALIZATION/STORAGE → ANALYTICAL TOOLS
   → SAIF1 ANALYST AGENT → CRITIC/VALIDATION → FINAL INSIGHTS
   → VISUALIZATION → REPORT → social/publishing channels
```

This is **not** a generic AI news bot. Numerical conclusions come from
deterministic calculations over real timing data; an LLM layer (built in a
later phase) reasons over those calculated facts, it never invents them.

The project is being built in deliberately small, testable phases:

1. **Data + analysis foundation** *(this phase)* - reliable ingestion of
   completed session data and deterministic race-pace/strategy metrics.
2. Agentic analyst layer - tool-calling agent that investigates a race.
3. Critic/validation layer - challenges unsupported claims before publish.
4. Visualization, reporting, and automated content generation.

Do not assume later phases exist yet; this README reflects Phase 1 only.

## Current capabilities (Phase 1)

- Load any completed FastF1-supported session (`data/loader.py`) with clear
  errors instead of raw tracebacks or silent wrong-event fuzzy-matches.
- Deterministic analysis functions, all returning structured data (dicts /
  lists of dicts), not prose:
  - `analysis.pace` - representative race pace (median/mean/best) per
    driver, and head-to-head pace comparison.
  - `analysis.stints` - tyre stint extraction (compound, lap range,
    per-lap times).
  - `analysis.tyres` - per-stint degradation trend (linear fit) and
    per-compound pace summary.
  - `analysis.strategy` - pit stops, grid-to-finish position changes, and
    lap-by-lap position progression.
  - `analysis.quality` - the shared lap-filtering rules every function
    above is built on (see **Data quality & assumptions** below).
- Five chart types (`visualization/charts.py`): lap time progression,
  driver pace comparison, tyre stints, position progression, pit stop
  timeline.
- A CLI (`scripts/analyze_race.py`) that ties it together end-to-end for a
  single session.
- Unit tests for every analysis function against synthetic edge cases
  (empty data, missing values, deleted laps, unknown drivers).

## Architecture

```
saif1/
├── config.py            Session identification, cache path, constants
├── exceptions.py         SAIF1Error hierarchy for clear failure messages
├── data/
│   ├── loader.py          FastF1 session loading + validation
│   └── cache.py           FastF1 on-disk cache setup
├── analysis/
│   ├── quality.py          Shared lap-filtering rules (see below)
│   ├── pace.py              Race pace + driver comparison
│   ├── stints.py            Tyre stint extraction
│   ├── tyres.py              Degradation + compound performance
│   └── strategy.py           Pit stops + position changes
└── visualization/
    └── charts.py             Matplotlib chart functions
```

Three-layer separation, enforced going forward:

- **Data layer** never contains LLM-generated information.
- **Analysis layer** is deterministic and reproducible - same input laps
  always produce the same output numbers.
- **Intelligence layer** (future phase) reasons over analysis-layer output;
  it does not calculate facts itself.

`analysis/quality.py` was added beyond the originally sketched structure
because every other analysis module needs the same lap-filtering rules;
centralizing it avoids four slightly-different, silently-inconsistent
filters.

## Data source

[FastF1](https://docs.fastf1.dev/) (v3.8.3 at time of writing), which
sources timing data from the F1 live timing API and Ergast. FastF1's
on-disk cache is enabled automatically at `data/cache/` to avoid
re-downloading session data on repeat runs.

## Installation

Requires Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # macOS/Linux
pip install -e .
```

## Usage

```bash
python scripts/analyze_race.py --year 2024 --event "Bahrain Grand Prix" --session R
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--year` | required | Championship year, e.g. `2024` |
| `--event` | required | Event name, e.g. `"Bahrain Grand Prix"` |
| `--session` | `R` | `FP1`/`FP2`/`FP3`/`Q`/`S`/`SQ`/`R` |
| `--drivers` | top 6 finishers | Comma-separated driver codes, e.g. `VER,HAM` |
| `--output-dir` | `analysis_output` | Where charts are saved |
| `--log-level` | `INFO` | Python logging level |

This prints race pace, stints, compound performance, pit stops, and
position changes to the console, and saves five charts as PNGs.

## Analytical methodology

**Representative pace** uses the *median* lap time, not the mean - it is
far less sensitive to the handful of outlier laps (traffic, a locked
wheel, a scrappy first lap) that survive filtering but still aren't
representative of true pace.

**Tyre degradation** is a simple linear regression (lap time vs. tyre age,
via `numpy.polyfit`) over one stint - a deterministic calculation, not a
predictive model. Pace also drifts with fuel load, traffic, and track
evolution within a stint, so read the slope as a trend direction and
rough magnitude, not a precise physical degradation rate.

**Pit stop duration** (`pit_lane_time_s`) is measured from the lap
crossing the pit-entry line to the following lap crossing the pit-exit
line. This is pit-lane transit time, not the stationary "box" time you
see on a TV broadcast - FastF1's basic timing data (without telemetry)
does not expose stationary time separately. Treat it as an approximation
of total time lost, not a precise stop duration.

## Data quality & assumptions

F1 timing data contains laps that don't represent true pace. Every
analysis function is built on `analysis.quality.filter_usable_laps`,
which applies these rules explicitly rather than dropping data silently:

- **Deleted laps** (e.g. track limits violations) are excluded by
  default - they didn't count for official timing.
- **Inaccurate laps** - FastF1's own `IsAccurate` flag (laps with
  missing/inconsistent sector timing) are excluded by default.
- **In-laps and out-laps** are excluded by default - they're slower for
  reasons unrelated to race pace.
- **Yellow flag / safety car / VSC / red flag laps** are *not* excluded
  by default (`green_flag_only=False`), since that would also remove
  legitimate, valid-but-slow laps (e.g. genuine traffic). Pass
  `green_flag_only=True` when pure green-flag pace comparison is needed.

One real edge case found while testing: FastF1's own `pick_not_deleted()`
silently collapses a zero-row `Laps` frame to zero *columns* as well (a
pandas boolean-indexing quirk), which would otherwise break every
downstream `pick_*()` call. `filter_usable_laps` short-circuits on empty
input specifically to avoid this.

## Known limitations

- Telemetry is not loaded by default (`telemetry=False` in
  `load_session`) to keep the cache small and load times fast; none of
  the current analysis functions need it. This means true stationary pit
  time, tyre pressures, and car-level telemetry aren't available yet.
- FastF1 fuzzy-matches unrecognized event names to the closest known
  event instead of raising an error. `load_session` detects and logs a
  warning when the resolved event name doesn't match the request, but
  does not hard-fail - review the log before trusting results for an
  event name you're unsure about.
- Session/event validation depends on FastF1's schedule data being
  available for the requested year; sessions that haven't happened yet,
  or years with no published schedule, raise `SessionNotFoundError`.
- No agent, critic/validation layer, ML, or automated publishing exists
  yet - see Roadmap.

## Roadmap

- **Phase 2**: SAIF1 Analyst Agent - tool-calling agent that uses the
  Phase 1 analysis functions to investigate a race and produce findings.
- **Phase 3**: Critic/validation layer that challenges unsupported claims,
  bad assumptions, and small sample sizes before a finding is finalized.
- **Phase 4**: Visualization polish, structured reports, and automated
  publishing.
- ML is intentionally deferred until a clearly-defined prediction problem
  justifies it (e.g. lap-time or degradation prediction); it is not the
  foundation of this project.

## Testing

```bash
python -m pytest tests/ -v
```

Tests use synthetic `Laps` data (see `tests/conftest.py`) rather than
live FastF1 calls, so they run offline and fast, and cover empty
datasets, deleted/inaccurate laps, missing drivers, and duplicate rows in
addition to normal race data.
