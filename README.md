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

1. **Data + analysis foundation** *(Phase 1)* - reliable ingestion of
   completed session data and deterministic race-pace/strategy metrics.
2. **Analytical reliability & persistence** *(Phase 1.5, this phase)* -
   confidence-gated event resolution, explicit named pace/quality policies,
   and structured JSON persistence of analysis output.
3. Agentic analyst layer - tool-calling agent that investigates a race.
4. Critic/validation layer - challenges unsupported claims before publish.
5. Visualization, reporting, and automated content generation.

Do not assume later phases exist yet; this README reflects Phase 1.5.

## Current capabilities (Phase 1.5)

- Load any completed FastF1-supported session (`data/loader.py`) with clear
  errors instead of raw tracebacks or silent wrong-event fuzzy-matches - see
  **Event validation** below.
- Deterministic analysis functions, all returning structured data (dicts /
  lists of dicts), not prose:
  - `analysis.pace` - `calculate_race_pace` / `calculate_green_flag_pace`
    (median/mean/best per driver, each tagged with which policy produced
    it) and head-to-head pace comparison.
  - `analysis.stints` - tyre stint extraction (compound, lap range,
    per-lap times).
  - `analysis.tyres` - per-stint degradation trend (linear fit) and
    per-compound pace summary.
  - `analysis.strategy` - pit stops, grid-to-finish position changes, and
    lap-by-lap position progression.
  - `analysis.quality` - the three named lap-filtering policies every
    function above is built on, plus per-driver exclusion accounting and
    a session-level track-condition summary (see **Data quality &
    assumptions** below).
- Five chart types (`visualization/charts.py`): lap time progression,
  driver pace comparison, tyre stints, position progression, pit stop
  timeline.
- Structured JSON persistence (`persistence.py`) of a full session's
  analysis output to `data/results/` - see **Persisted result schema**.
- A CLI (`scripts/analyze_race.py`) that ties it together end-to-end for a
  single session.
- Unit tests (offline, no network) for every analysis function against
  synthetic edge cases (empty data, missing values, deleted laps, unknown
  drivers, DNF drivers, duplicate rows), including cross-check tests that
  verify the exclusion-accounting classifier agrees with the real
  filtering functions rather than trusting them to agree by construction.

## Architecture

```
saif1/
├── config.py            Session identification, cache path, constants
├── exceptions.py         SAIF1Error hierarchy for clear failure messages
├── persistence.py         JSON assembly + writing of analysis results
├── data/
│   ├── loader.py             FastF1 session loading + validation
│   ├── event_resolution.py    Confidence-gated event-name resolution
│   └── cache.py               FastF1 on-disk cache setup
├── analysis/
│   ├── quality.py          Named lap-filtering policies + exclusion accounting
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

## Event validation

FastF1's own `get_session(year, "some string", session_type)` fuzzy-matches
whatever string you pass against its event schedule and always returns its
single best guess - even a poor one - only logging a warning when the match
wasn't precise. A missed log line means silently analyzing the wrong Grand
Prix.

`data/event_resolution.py` resolves the requested event name against the
same underlying schedule fields FastF1 uses (event name, official name,
location, country), but requires the query to be an **unambiguous, exact
substring match** against exactly one event before accepting it:

- `"Bahrain Grand Prix"`, `"Bahrain GP"`, and `"bahrain"` all resolve
  identically (each is an exact substring match against Bahrain's
  Country/EventName fields once common words like "Grand Prix"/"GP" and
  the year are stripped).
- Anything that isn't an unambiguous substring match - a typo, an
  unrelated name, a query matching more than one event - **raises
  `SessionNotFoundError`**, it is never silently accepted. `loader.py`
  then requests the session by the resolved **round number**, not the
  original string, so FastF1's own fuzzy matcher is never invoked a
  second time.
- `rapidfuzz` (already an unavoidable transitive dependency of FastF1
  itself, now declared explicitly in `requirements.txt`/`pyproject.toml`)
  is used **only** to build a "did you mean '{closest event}'?" hint in
  the error message after matching has already failed - it never
  selects or resolves an event that then gets loaded and analyzed. A
  fuzzy match alone can never cause a session to load.

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
| `--results-dir` | `data/results` | Where the persisted JSON result is saved |
| `--log-level` | `INFO` | Python logging level |

This prints race pace (both policies), stints, compound performance, pit
stops, and position changes to the console, saves five charts as PNGs, and
saves one structured JSON result (see **Persisted result schema**).

## Analytical methodology

**Representative pace** uses the *median* lap time, not the mean - it is
far less sensitive to the handful of outlier laps (traffic, a locked
wheel, a scrappy first lap) that survive filtering but still aren't
representative of true pace.

**Tyre degradation** is a simple linear regression (lap time vs. tyre age,
via `numpy.polyfit`) over one stint - a deterministic calculation, not a
predictive model. The fitted slope is a **net** trend, not pure tyre
degradation: fuel burn-off speeds laps up as a stint progresses, working
directly against tyre wear (which slows them down), and track evolution
can move lap times either way independently of both. A shallow or even
negative slope does not mean the tyre wasn't degrading - it may mean fuel
burn-off outweighed wear. Read the slope as net trend direction and rough
magnitude, never as a physical tyre-wear rate. Uses the strictest
(`green_flag_pace`) lap filter, since a single stint already has few data
points and any flag-affected lap is disproportionate noise on such a small
sample.

**Pit stop duration** (`pit_lane_time_s`) is measured from the lap
crossing the pit-entry line to the following lap crossing the pit-exit
line. This is pit-lane transit time, not the stationary "box" time you
see on a TV broadcast - FastF1's basic timing data (without telemetry)
does not expose stationary time separately. Treat it as an approximation
of total time lost, not a precise stop duration. **During a red flag**,
this same calculation spans the entire stoppage (observed directly in the
2023 Australian GP verification run: pit lane times over 900 seconds) -
it is technically correct (time from pit-entry to pit-exit) but not
meaningful as a "stop duration" during a red flag; a consumer of this
field should be aware a red flag occurred (see `track_conditions` below)
before treating a large value as a slow pit stop.

## Data quality & assumptions

F1 timing data contains laps that don't represent true pace: in/out laps,
deleted laps, laps FastF1 flags as timing-inaccurate, and laps run under
yellow flags, Safety Car, VSC, or a red flag. None of this data is
arbitrarily discarded. `analysis.quality` provides one general mechanism
(`filter_usable_laps`) and three named, explicitly documented policies
built on it - every other analysis function picks one of these three by
name (the canonical descriptions live in `quality.POLICY_DEFINITIONS`,
which `persistence.py` reads directly rather than duplicating the prose):

| Policy | Excludes | Used by |
|---|---|---|
| `all_usable_laps` | deleted, inaccurate, pit in/out laps only | `stints`, `strategy` (structural analyses that need full lap coverage regardless of flags) |
| `representative_race_pace` | + Safety Car, VSC, red flag | `pace.calculate_race_pace`, `tyres.compound_performance` (the default pace metric) |
| `green_flag_pace` | + any yellow-flagged lap (all flags excluded) | `tyres.stint_degradation`, `pace.calculate_green_flag_pace` (strictest, smallest sample) |

`representative_race_pace` keeps yellow-flagged laps deliberately: a
yellow is usually localized to one sector and often barely changes overall
lap time, so excluding every yellow-affected lap by default would discard
a lot of legitimate data for comparatively little benefit. `green_flag_pace`
excluding yellow-flagged laps on top of that is **a deliberately strict
analytical policy, not a claim that every yellow-affected lap is
inherently invalid** - it exists for callers who want zero flag
interference at all, even at the cost of a smaller sample.

**Empirical finding from verification runs** (2023 Australian GP - 3 red
flags; 2023 Canadian GP - 1 Safety Car, no red flag): in both races, every
driver's Safety-Car/VSC/red-flag-affected laps were *also* independently
flagged inaccurate or were pit in/out laps, so `representative_race_pace`
and `all_usable_laps` retained the exact same lap count for every driver
in both races, even though genuine SC/VSC/red-flag periods definitely
occurred (confirmed via `track_conditions`, see below). This appears to be
because FastF1's accuracy heuristic is sensitive to the erratic,
bunched-up timing typical of Safety Car/VSC laps. It is not a bug - the
`representative_race_pace` vs. `all_usable_laps` exclusion sets are
correct and cross-checked (see below) - it just means the severe-condition
exclusion rule frequently has no *additional* effect beyond what accuracy
filtering already removes, in the two real races tested so far. Do not
assume this always holds; it just means when you see no difference, check
`track_conditions` before concluding SC/VSC didn't occur.

### Per-driver exclusion accounting (`lap_exclusions`)

Every lap is classified with a **single** exclusion reason by precedence
(`quality.EXCLUSION_PRECEDENCE`): `deleted` > `pit_in` > `pit_out` >
`inaccurate` > `red_flag` > `safety_car` > `virtual_safety_car` >
`yellow_flag`. Structural reasons outrank flag conditions (a
deleted/pit/inaccurate lap is invalid regardless of what flag was active);
`pit_in`/`pit_out` outrank `inaccurate` specifically because pit laps are
very often *also* flagged inaccurate by FastF1, and the pit-lane label is
far more meaningful to a reader. Flag conditions are ordered by severity.

**This means `excluded_by_reason` counts are incremental attribution, not
a census of race conditions.** A lap that is both under Safety Car *and*
flagged inaccurate is counted under `inaccurate` only - the `safety_car`
bucket will not count it, even though a Safety Car genuinely was active on
that lap (see the empirical finding above, where this happens for nearly
every SC/VSC/red-flag-affected lap in both verification races). Do
**not** read a zero `safety_car`/`virtual_safety_car`/`red_flag` count as
"no Safety Car/VSC/red flag occurred" - check `track_conditions` for that.

`quality.summarize_exclusions_by_policy(driver_laps)` computes this once
per driver and derives all three policies' retained/excluded counts from
it. The **primary correctness check** (in `tests/test_quality.py`) is not
that these numbers are internally self-consistent (`retained +
sum(excluded_by_reason) == total`, which holds by construction and proves
nothing on its own) - it's that `retained_laps` for each policy is
cross-checked against calling the real `all_usable_laps` /
`representative_race_pace_laps` / `green_flag_laps` filter functions
directly, across both synthetic edge-case fixtures (empty, all-deleted,
all-inaccurate, a DNF-like driver with fewer laps than race distance,
duplicate rows) and, in manual verification, real 2023/2024 race data.
No disagreement has been found between the classifier and the real filter
chain in any case tested.

### Session-level track conditions (`track_conditions`)

Because `lap_exclusions` can mask genuine SC/VSC/red-flag involvement (see
above), `quality.summarize_track_conditions(laps)` independently answers
"was Safety Car/VSC/red flag/yellow active during lap range X" at the
**session level** (not per-driver - these are field-wide conditions), by
taking the union of every driver's `TrackStatus` per lap number and
collapsing it into contiguous lap ranges. This is the reliable way to
check whether a condition occurred; `lap_exclusions`'s reason buckets are
not.

### Real edge cases found while testing

- FastF1's own `pick_not_deleted()` silently collapses a zero-row `Laps`
  frame to zero *columns* as well (a pandas boolean-indexing quirk), which
  would otherwise break every downstream `pick_*()` call.
  `filter_usable_laps` short-circuits on empty input specifically to avoid
  this.
- FastF1's `get_event_by_name`/fuzzy event matching (see **Event
  validation** above) will accept and silently "correct" almost any input
  string rather than failing - this is why `event_resolution.py` exists
  as an independent, stricter check on top of it.

## Persisted result schema

Every `analyze_race.py` run writes one JSON file to `data/results/`
(git-tracked - see below), containing every driver's analysis output, not
just whichever drivers `--drivers` chose to print/chart. Filename:
`{year}_{round:02d}_{event-slug}_{session_type}.json`, e.g.
`2024_01_bahrain-grand-prix_R.json`. The slug is derived from FastF1's
*resolved* `EventName`, not the raw string you typed, so re-running the
same session however it was invoked overwrites the same file rather than
creating duplicates.

```jsonc
{
  "schema_version": "1.0",
  "provenance": {
    "data_source": "FastF1",
    "fastf1_version": "3.8.3",
    "saif1_methodology_version": "1.5.0",
    "generated_at": "2026-08-17T18:04:00+00:00",
    "session_identifier": "2024-01-R"
  },
  "session": {
    "year": 2024, "event_name": "Bahrain Grand Prix", "round_number": 1,
    "session_type": "R", "location": "Sakhir", "country": "Bahrain",
    "event_date": "2024-03-02", "session_date": "2024-03-02T15:00:00"
  },
  "drivers": [
    {
      "driver": "VER", "driver_number": "1", "full_name": "Max Verstappen",
      "team": "Red Bull Racing", "grid_position": 1, "finish_position": 1,
      "status": "Finished"
    }
    // one entry per session.results row; grid_position/finish_position
    // are explicit null (never 0, never omitted) when FastF1 reports none
  ],
  "race_pace": {
    "representative_race_pace": [ /* one calculate_race_pace() dict per driver with laps */ ],
    "green_flag_pace": [ /* one calculate_green_flag_pace() dict per driver with laps */ ]
  },
  "stints": [ /* extract_stints() output, all drivers */ ],
  "tyre_degradation": [ /* one stint_degradation() result per stint, all drivers */ ],
  "compound_performance": [ /* compound_performance() output */ ],
  "pit_stops": [ /* extract_pit_stops() output */ ],
  "position_changes": [ /* position_changes() output - drivers[] is canonical for grid/finish position, this must always agree with it */ ],
  "lap_exclusions": [
    {
      "driver": "VER",
      "laps_recorded": 57,
      "policies": {
        "all_usable_laps": {
          "retained_laps": 52, "excluded_laps": 5,
          "excluded_by_reason": {
            "deleted": {"count": 1, "lap_numbers": [46]},
            "pit_in": {"count": 1, "lap_numbers": [17]},
            "pit_out": {"count": 1, "lap_numbers": [18]},
            "inaccurate": {"count": 2, "lap_numbers": [1, 38]},
            "red_flag": {"count": 0, "lap_numbers": []},
            "safety_car": {"count": 0, "lap_numbers": []},
            "virtual_safety_car": {"count": 0, "lap_numbers": []},
            "yellow_flag": {"count": 0, "lap_numbers": []}
          }
        },
        "representative_race_pace": { "...same shape..." },
        "green_flag_pace": { "...same shape, strictest..." }
      }
    }
  ],
  "track_conditions": [
    { "condition": "safety_car", "code": "4", "start_lap": 12, "end_lap": 14 }
    // session-level, sorted by start_lap - see "Session-level track conditions" above
  ],
  "quality_policy_definitions": {
    "all_usable_laps": "...", "representative_race_pace": "...", "green_flag_pace": "..."
    // read directly from quality.POLICY_DEFINITIONS - never hand-duplicated
  }
}
```

**`drivers[]` field sources** (all from `session.results`, never invented):
`driver`←`Abbreviation`, `driver_number`←`DriverNumber` (kept as a string -
it is a car number, not an arithmetic quantity), `full_name`←`FullName`,
`team`←`TeamName`, `grid_position`←`GridPosition`, `finish_position`←
`Position` (both `int` or explicit `null`), `status`←`Status` (FastF1's own
classification text, e.g. `"Finished"`, `"Retired"`, `"Disqualified"`,
passed through verbatim).

**`laps_recorded`** is the number of lap rows FastF1 has for that driver
*before any filtering* - not the race distance. For a driver who completed
the full race distance the two are equal (verified directly: FastF1's laps
table starts at `LapNumber` 1 for the first green-flag racing lap, with no
separate formation-lap row, and the row count for a finisher matches
`session.total_laps` exactly). For a driver who retired early, this is
however many racing laps they actually completed, which is why the
`lap_exclusions` cross-check tests specifically include a synthetic
DNF-like driver fixture with fewer laps than race distance.

**Why JSON, not SQLite/Parquet/a database**: the result is naturally
nested (session → drivers → stints/pace/exclusions), which JSON matches
directly - normalizing it into relational tables now would be premature
without a demonstrated cross-race query need. It's human-readable (useful
for a public portfolio repo), needs no schema migrations, and needs no new
runtime dependency. SQLite is the natural next step once there's real
value in querying across many persisted races (e.g. once the agent phase
needs "compare degradation across every 2024 race"); that need doesn't
exist yet.

**`data/results/` is git-tracked**, not gitignored - a deliberate choice.
Reproducible, inspectable analytical output is a credibility/transparency
asset for a public portfolio project, and these are small (~130-150 KB per
race session, measured from real verification runs - see below), fully
deterministic, non-sensitive JSON files with no raw data or telemetry in
them. At ~24 races/season this is on the order of 3-4 MB/season if only
Race sessions are persisted - trivial for git.

**Regeneration overwrites in place.** The filename depends only on
`year`/`round_number`/`event_name` (FastF1's resolved name)/`session_type`
- never on `saif1_methodology_version`. Re-analyzing a session after a
methodology change overwrites the same file, so the git diff shows exactly
what changed, which is the point: a `_v2`-suffix versioning scheme would
instead accumulate stale files and hide what actually changed between
runs. Because `provenance.generated_at` changes on every run, re-analyzing
an *unchanged* session still produces a one-line timestamp diff even when
every number is identical - that's expected, and is the signal that
nothing else changed.

## Known limitations

- Telemetry is not loaded by default (`telemetry=False` in
  `load_session`) to keep the cache small and load times fast; none of
  the current analysis functions need it. This means true stationary pit
  time, tyre pressures, and car-level telemetry aren't available yet.
- Session/event validation depends on FastF1's schedule data being
  available for the requested year; sessions that haven't happened yet,
  or years with no published schedule, raise `SessionNotFoundError`.
- `lap_exclusions`'s per-reason counts are incremental attribution, not a
  condition census - see **Data quality & assumptions** above. Always
  check `track_conditions` before concluding a flag condition didn't
  occur just because its exclusion bucket is zero.
- `pit_lane_time_s` during a red flag spans the entire stoppage, not a
  real pit stop duration - observed directly in the 2023 Australian GP
  verification run (900+ second values). Technically correct given the
  documented definition, but easy to misread without checking
  `track_conditions` first.
- No cross-race querying, no API, no schema migration story - each
  session is one independent JSON file. This is the deliberate current
  scope (see **Persisted result schema**), not an oversight.
- No agent, critic/validation layer, ML, or automated publishing exists
  yet - see Roadmap.

## Roadmap

- **Phase 2**: SAIF1 Analyst Agent - tool-calling agent that uses the
  Phase 1/1.5 analysis functions and persisted results to investigate a
  race and produce findings.
- **Phase 3**: Critic/validation layer that challenges unsupported claims,
  bad assumptions, and small sample sizes before a finding is finalized.
- **Phase 4**: Visualization polish, structured reports, and automated
  publishing.
- SQLite (or similar) becomes worth adopting once there's a real
  cross-race querying need - not before.
- ML is intentionally deferred until a clearly-defined prediction problem
  justifies it (e.g. lap-time or degradation prediction); it is not the
  foundation of this project.

## Testing

```bash
python -m pytest tests/ -v
```

Tests use synthetic `Laps`/`Session` data (see `tests/conftest.py` and the
`_FakeSession`/`_FakeEvent`-style fixtures in `tests/test_persistence.py`
and `tests/test_strategy.py`) rather than live FastF1 calls, so they run
offline and fast. Coverage includes empty datasets, deleted/inaccurate
laps, missing drivers, duplicate rows, DNF-like drivers with fewer laps
than race distance, ambiguous/invalid event names, and cross-checking the
exclusion-accounting classifier against the real filtering functions it's
meant to describe.
