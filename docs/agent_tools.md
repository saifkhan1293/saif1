# SAIF1 Agent Tool Surface — Specification

Phase 2, Milestone 1. This document specifies every tool the future SAIF1
Analyst Agent may call. It contains no agent, no LLM, no framework choice -
see `src/saif1/agent/tools.py` for the framework-neutral implementation this
document describes.

**Every tool is a thin wrapper over an existing, already-tested function.**
No new analysis logic was written for this milestone. Where a useful tool
would require new analysis, it is listed under **Gaps** at the end instead
of being built.

**Every tool reads persisted JSON only** (via `saif1.aggregation`), never a
live FastF1 load. This is deliberate and load-bearing: an agent calling these
tools must never transitively require `fastf1` to be installed, for the same
reason `aggregation.py` doesn't (see that module's docstring). No tool in
this surface needs a live load, so none is proposed.

## Identifying a session

Every session-level tool identifies a session by `(year, round_number,
session_type)` - **not** by event name. This is a deliberate consequence of
the project's own history: `resolve_event()` exists because event names are
genuinely ambiguous in real F1 data (see the 2024 "United States Grand Prix"/
"Qatar Grand Prix" cases). Persisted files are already keyed by round number,
which is unambiguous by construction. `list_available_sessions` is how an
agent discovers the round-number/event-name mapping before calling anything
else - it should always be the first tool call for a new season.

## The tool list

Confirmed from the candidate surface with one structural change and one
addition, both explained below.

| Tool | Reads | Backed by |
|---|---|---|
| `list_available_sessions` | persisted | directory listing + `session` block of each file |
| `get_session_summary` | persisted | `session`, `drivers`, `track_conditions`, `position_changes` fields |
| `get_race_pace` | persisted | `race_pace.{policy}` field |
| `get_stints` | persisted | `stints` field |
| `get_tyre_degradation` | persisted | `tyre_degradation` field |
| `get_compound_performance` | persisted | `compound_performance` field |
| `get_pit_stops` | persisted | `pit_stops` field |
| `get_lap_exclusions` | persisted | `lap_exclusions` field |
| `get_teammate_head_to_head` | persisted | `aggregation.teammate_pace_head_to_head` |

All nine read persisted JSON only. None needs a live FastF1 load, so the
"different risk class" question the milestone asked about doesn't arise for
this surface.

### Change from the candidate list: optional `driver` filter, not separate tools

The candidate surface grouped "stints / tyre degradation / compound
performance" and "pit stops / position changes" ambiguously - as one tool
each, or several. Implemented as separate, single-purpose tools (one per data
category - `get_stints`, `get_tyre_degradation`, `get_compound_performance`,
`get_pit_stops` are four tools, not one), matching standard tool-design
practice (a tool does one well-defined thing). `position_changes` is folded
into `get_session_summary` as the candidate list itself suggested.

Where a data category is naturally per-driver (`get_race_pace`, `get_stints`,
`get_tyre_degradation`, `get_pit_stops`), each takes an **optional**
`driver` parameter: omitted, it returns every driver's data for the session;
given, it returns just that driver's - `status="no_data"` if the driver has
no entry (see Refusal Contract). `compound_performance` has no `driver`
parameter - it's inherently session-wide, not per-driver.

### Addition not on the candidate list: none built, one considered and rejected for now

Considered adding a cross-season search tool (e.g. "find every wet race in a
season") while drafting this. Rejected for this milestone - not because it
needs new analysis (it doesn't; it would iterate `list_available_sessions`
and filter each session's `compound_performance` for INTERMEDIATE/WET, the
same shape as `teammate_pace_head_to_head`'s own iteration), but because it
wasn't on the confirmed candidate list and the instruction was to confirm or
argue against that list, not freely expand it. Flagging it here rather than
building it silently: worth adding later if a real question needs it.

## Tool specifications

Every tool validates `session_type` against `saif1.config.VALID_SESSION_TYPES`
and raises `ValueError` for anything else - see Refusal Contract for why this
is a raise, not a `no_data` result.

---

### `list_available_sessions(year, session_type=None)`

**Purpose**: Discover what's actually persisted for a season, before asking
about any of it by round number.

**Inputs**:
- `year: int` - required.
- `session_type: str | None` - optional. One of
  `saif1.config.VALID_SESSION_TYPES` if given; omitted means "every session
  type."

**Returns**: `ToolResult(status="ok", data=[{"year", "round_number",
"event_name", "session_type"}, ...])`, sorted by round number then session
type. Always `status="ok"` - an empty list for a season with nothing
persisted is itself the complete, correct answer (there is no more specific
single thing being asked about for this tool to be "missing").

**Refusal behavior**: Never `no_data`. Invalid `session_type` raises
`ValueError`.

**Backed by**: `saif1.aggregation.load_season_index`, called once per
session type being searched.

---

### `get_session_summary(year, round_number, session_type)`

**Purpose**: Roster, classification, and track conditions for one session -
the entry point for anything else about that session.

**Inputs**: `year: int`, `round_number: int`, `session_type: str`, all
required.

**Returns** (`status="ok"`): `{"session": {...}, "drivers": [...],
"track_conditions": [...], "position_changes": [...]}` - the corresponding
top-level fields of the persisted result, unchanged.

**Refusal behavior**: `status="no_data", reason="session_not_persisted"` if
no file matches `(year, round_number, session_type)`.

**Backed by**: reading the matching persisted result directly (via
`load_season_index` + filtering by `round_number`).

---

### `get_race_pace(year, round_number, session_type, policy="representative_race_pace", driver=None)`

**Purpose**: Race pace for one or every driver in a session, under an
explicitly-named policy.

**Inputs**: `year`, `round_number`, `session_type` required. `policy: str`,
must be `"representative_race_pace"` or `"green_flag_pace"` - **not**
validated silently; an unrecognized value raises. Defaults to
`"representative_race_pace"` per the project's own framing (see README "Data
quality & assumptions"): it's the answer, `green_flag_pace` is the
sensitivity check, and a tool defaulting to the check would invert that.
`driver: str | None` optional.

**Returns** (`status="ok"`): the matching `race_pace.{policy}` list (all
drivers) or single entry (one driver) - unchanged from the persisted shape,
including `usable_laps`/`median_lap_time_s` etc. A driver with
`usable_laps=0` and `median_lap_time_s=None` is a **real, valid `ok` answer**
(they raced but had no usable pace data that session, e.g. a first-lap
retirement) - not `no_data`. See Refusal Contract for why this distinction
matters.

**Refusal behavior**: `no_data/session_not_persisted` if the session isn't
persisted. If a `driver` was given and has no entry in that policy's list:
`no_data/driver_not_in_session` (not on this session's roster at all) or
`no_data/driver_did_not_run` (on the roster, `laps_recorded=0` - see the
Gasly example in the Refusal Contract). Invalid `policy` raises
`ValueError`.

**Backed by**: `race_pace.representative_race_pace` /
`race_pace.green_flag_pace` fields, produced by
`pace.calculate_race_pace`/`pace.calculate_green_flag_pace` at persistence
time.

---

### `get_stints(year, round_number, session_type, driver=None)`

**Purpose**: Tyre stint history for one or every driver.

**Inputs**: `year`, `round_number`, `session_type` required, `driver`
optional.

**Returns** (`status="ok"`): matching entries from the persisted `stints`
list, unchanged.

**Refusal behavior**: `no_data/session_not_persisted`. If `driver` was given
and matches zero stints: `no_data/driver_not_in_session` or
`no_data/driver_did_not_run` depending on which applies (see Refusal
Contract) - **not** automatically `no_data` just because the list is empty:
a driver who ran but genuinely has zero entries for this category returns
`status="ok", data=[]` instead (see the Sargeant pit-stops example in the
Refusal Contract - the same rule applies here).

**Backed by**: `stints` field (`analysis.stints.extract_stints` at
persistence time).

---

### `get_tyre_degradation(year, round_number, session_type, driver=None)`

**Purpose**: Per-stint degradation slope for one or every driver.

**Inputs/Returns/Refusal**: same shape as `get_stints`, over the persisted
`tyre_degradation` field.

**Backed by**: `tyre_degradation` field (`analysis.tyres.stint_degradation`
at persistence time). Note this is a **net** trend (tyre wear confounded
with fuel burn-off), not pure degradation - see the README; this tool
doesn't change that, it just surfaces the number as computed.

---

### `get_compound_performance(year, round_number, session_type)`

**Purpose**: Session-wide median pace per tyre compound.

**Inputs**: `year`, `round_number`, `session_type` required. No `driver`
parameter - inherently session-wide.

**Returns** (`status="ok"`): the persisted `compound_performance` list,
unchanged - real, physical compounds only, already excludes
`UNKNOWN`/`TEST-UNKNOWN`/unrecognized values (see README). A compound
nobody ran that session simply doesn't appear in the list; this is `ok`
with a shorter list, not `no_data` for that compound - there's no
per-compound query here to refuse.

**Refusal behavior**: `no_data/session_not_persisted` only.

**Backed by**: `compound_performance` field
(`analysis.tyres.compound_performance` at persistence time).

---

### `get_pit_stops(year, round_number, session_type, driver=None)`

**Purpose**: Pit stops for one or every driver.

**Inputs/Returns/Refusal**: same shape as `get_stints`. A driver who ran but
made zero pit stops - the real, verified example: Sargeant, Canadian GP
2024 round 9, `laps_recorded=24`, retired before ever pitting - returns
`status="ok", data=[]`, not `no_data`. See Refusal Contract for exactly how
this is distinguished from `driver_not_in_session`/`driver_did_not_run`.

**Backed by**: `pit_stops` field (`analysis.strategy.extract_pit_stops` at
persistence time).

---

### `get_lap_exclusions(year, round_number, session_type, driver)`

**Purpose**: Full exclusion accounting (all three quality policies,
multi-label per-lap detail) for one specific driver.

**Inputs**: `year`, `round_number`, `session_type`, `driver` - **all
required**, unlike the other per-driver tools. This tool is only meaningful
for one driver at a time (matches the candidate surface's own phrasing,
"for a driver in a session").

**Returns** (`status="ok"`): the matching entry from the persisted
`lap_exclusions` list - `laps_recorded`, `excluded_laps_detail`, and all
three policies' retained/excluded counts, unchanged. **This tool has no
`driver_did_not_run` case** - unlike every other per-driver tool: a
did-not-start driver already has a real `lap_exclusions` entry
(`laps_recorded: 0`), so their result is `status="ok"`, not a refusal
(verified: Gasly, British GP 2024 round 12, returns `ok` with
`laps_recorded: 0` here, even though the same driver/session is
`no_data/driver_did_not_run` from `get_race_pace`).

**Refusal behavior**: `no_data/session_not_persisted`, or
`no_data/driver_not_in_session` if `driver` isn't on the session's roster
at all.

**Backed by**: `lap_exclusions` field
(`analysis.quality.summarize_exclusions_by_policy` at persistence time).

---

### `get_teammate_head_to_head(year, session_type="R")`

**Purpose**: Season-long teammate pace comparison - the one cross-session
tool in this surface.

**Inputs**: `year: int` required. `session_type: str`, defaults to `"R"`
(Race) since that's the only session type this has been validated against
- see README "Data quality & assumptions" on why Sprint/Race shouldn't be
pooled by default.

**Returns** (`status="ok"`): the full list of pairings from
`teammate_pace_head_to_head`, unchanged - including `median_gap_s` etc. and
the emergent mid-season-substitution behavior documented in
`aggregation.py`. **Every caller of this tool must be given the
track-position/strategy confound caveat alongside any result presented from
it** - see README "Data quality & assumptions" and the Phase 3 roadmap note;
this specification does not repeat the caveat text itself since the
canonical wording already lives there and should not drift into a second
copy.

**Refusal behavior**: `no_data/season_not_persisted` if
`list_available_sessions` would show zero sessions for `(year,
session_type)`. Otherwise always `status="ok"`, even if the resulting
pairing list happens to be empty (a genuinely unusual case, not treated
differently from the general rule that a real empty list is `ok`).

**Backed by**: `aggregation.load_season_index` +
`aggregation.teammate_pace_head_to_head`, unchanged.

---

## The refusal contract

The most important part of this specification. Every tool above follows it
exactly - this section states the rule once rather than repeating it nine
times.

### Three structurally distinct outcomes

1. **A real answer, `status="ok"`.** This includes:
   - A populated list or dict - the normal case.
   - **A genuinely empty list** - e.g. a session with zero pit stops. This
     is not missing data; it's the correct, complete answer to "what pit
     stops happened," and it happened to be none. Never conflated with
     `no_data`.
   - **A real zero or `None` inside an otherwise-populated result** - e.g. a
     driver's `usable_laps=0, median_lap_time_s=None` in `get_race_pace`
     when they raced but had no usable pace data. The driver *exists* and
     the tool found their entry; the entry's own fields already say "zero"
     honestly. This is `ok`, not `no_data` - the persisted schema already
     makes this distinction (see `saif1.persistence`'s design), and this
     tool layer preserves it rather than collapsing it.

2. **No answer exists, `status="no_data"`.** The query was well-formed, but
   there is nothing to return - a session was never persisted, a driver
   code doesn't produce any entry in the data being asked about. `data` is
   always `None`. `reason` is always one of a fixed, small set of codes,
   never a free-text message:
   - `"session_not_persisted"` - no file matches the requested
     `(year, round_number, session_type)`.
   - `"season_not_persisted"` - no files match `(year, session_type)` at
     all (used by the one tool, `get_teammate_head_to_head`, that operates
     at season grain rather than session grain).
   - `"driver_not_in_session"` - the driver code does not appear in this
     session's roster at all (wrong code, or wrong session).
   - `"driver_did_not_run"` - the driver **is** on the roster, but
     `laps_recorded == 0` for them in `lap_exclusions` - they were entered
     for the session but never completed a lap (e.g. a genuine
     did-not-start).

   These two were originally one code (`driver_not_found`), collapsed on
   the reasoning that both mean "nothing here for this driver" to a
   caller. That reasoning didn't survive contact with a real case: British
   GP 2024 round 12, Gasly (`GAS`) is on the grid in **P19** with
   classification status **"Did not start"** - a real, reportable fact
   ("Gasly qualified P19 and did not start" is a legitimate sentence in a
   race report), not an absence. Under the collapsed code,
   `get_race_pace(2024, 12, "R", driver="GAS")` and the same call with
   `driver="ZZZ"` (not a driver at all) returned byte-identical results.
   The persisted schema itself already distinguishes this correctly
   (`drivers[]` carries Gasly with `status: "Did not start"`,
   `lap_exclusions` carries him with `laps_recorded: 0`) - collapsing the
   two at the tool boundary lost information the data underneath already
   had, at exactly the point an LLM starts consuming it. Split for real,
   not just renamed: `_classify_driver()` in `tools.py` checks roster
   membership first, then `laps_recorded`, so the two codes are never
   conflated regardless of which tool is asking.

   A related, correctly-`ok` case worth distinguishing from both: a driver
   who **did** run can have a genuinely empty result for one specific
   category without either code applying - e.g. Sargeant (`SAR`), Canadian
   GP 2024 round 9, `laps_recorded=24` (retired mid-race) but zero
   `pit_stops` (never made one before retiring). `get_pit_stops(2024, 9,
   "R", driver="SAR")` returns `status="ok", data=[]` - he ran, this
   category is just empty for him, which is case 1 above, not this one.

3. **Invalid input - a raised exception, not a `ToolResult` at all.** An
   unrecognized `session_type` or `policy` is a caller contract violation
   (the tool was called wrong), not a legitimate business "no answer" -
   raises `ValueError` immediately. `MethodologyMismatchError` (from
   `load_season_index`, if persisted files somehow span incompatible
   methodology versions) also propagates uncaught for the same reason: it's
   a real data-integrity problem, not something a tool should silently
   narrate around.

### Absolute rules

- **No tool returns prose.** Every value is structured data - a dict, a
  list, a fixed reason code. The agent writes sentences from this data; no
  tool writes a sentence for it.
- **No tool invents, estimates, or defaults a missing value.** Every number
  returned is read directly from a persisted field that
  `saif1.persistence`/`saif1.aggregation` already computed deterministically.
  If a tool doesn't have a real value, it returns `no_data` with a reason,
  never a placeholder, a zero standing in for "unknown," or a guess.

## Known limitation of this tool surface: exactly one cross-session tool

`get_teammate_head_to_head` is the only cross-session tool in this surface.
Every other tool answers a question about one session in isolation. This
means the agent has no way to establish that something is *unusual for the
season* except within a teammate comparison - it cannot ask "is this
degradation slope typical for this driver?", "was this pit stop slow
relative to the rest of the field that race, or the season?", or "is this
pace gap larger than normal for this pairing?" for anything outside
`get_teammate_head_to_head` itself, because nothing else exposes a
season-level baseline to compare a single-session number against.

This is a correct, deliberate scope decision for Milestone 1, not a gap to
fill now - stated here explicitly so Milestone 2 is scoped against a known
boundary instead of discovering it mid-build. If a future milestone adds
more cross-session tools, this note should be removed or narrowed rather
than silently going stale.

## Gaps - not built, needs new analysis logic

Per the milestone's instruction: these are useful tools this specification
does **not** provide, because building them would mean writing new analysis
logic, which this milestone explicitly excludes.

1. **Season-wide (cross-car) pace ranking** - "who had the best race pace
   all season, regardless of team" would need a new aggregation function;
   `teammate_pace_head_to_head` only ever compares drivers in the *same*
   car, which is what makes it a valid pace comparison in the first place
   (see the confound discussion in README). A cross-car ranking is a
   different, harder question (it would need to control for car
   performance somehow) and isn't answered by anything that exists today.
2. **Confound-controlled teammate comparison** (matched compound, similar
   tyre age, similar stint phase) - already recorded as a deferred known
   limitation in the README after the previous milestone; restated here
   because it would also change what `get_teammate_head_to_head` could
   honestly return, and no tool for it exists in this surface for the same
   reason it wasn't built there.
