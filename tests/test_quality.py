import pytest

from saif1.analysis.quality import (
    EXCLUSION_PRECEDENCE,
    all_usable_laps,
    classify_all_exclusion_reasons,
    classify_lap_exclusion_reason,
    filter_usable_laps,
    green_flag_laps,
    has_severe_track_condition,
    is_green_flag_lap,
    representative_race_pace_laps,
    summarize_exclusions_by_policy,
    summarize_track_conditions,
)
from tests.conftest import make_laps


def test_is_green_flag_lap_clear():
    assert is_green_flag_lap("1") is True


def test_is_green_flag_lap_safety_car():
    assert is_green_flag_lap("4") is False


def test_is_green_flag_lap_concatenated_codes():
    # FastF1 concatenates codes when multiple statuses occur in one lap.
    assert is_green_flag_lap("12") is False  # contains yellow (2)


def test_is_green_flag_lap_empty_string():
    assert is_green_flag_lap("") is True


def test_filter_usable_laps_removes_pit_deleted_and_inaccurate():
    laps = make_laps(
        [
            {"LapNumber": 1, "IsAccurate": True, "Deleted": False},
            {"LapNumber": 2, "IsAccurate": False, "Deleted": False},  # inaccurate
            {"LapNumber": 3, "IsAccurate": True, "Deleted": True},  # deleted
            {"LapNumber": 4, "IsAccurate": True, "Deleted": False, "PitInTime": 100.0},  # in-lap
            {"LapNumber": 5, "IsAccurate": True, "Deleted": False},
        ]
    )
    usable = filter_usable_laps(laps)
    assert sorted(usable["LapNumber"].tolist()) == [1, 5]


def test_filter_usable_laps_green_flag_only():
    laps = make_laps(
        [
            {"LapNumber": 1, "TrackStatus": "1"},
            {"LapNumber": 2, "TrackStatus": "4"},  # safety car
            {"LapNumber": 3, "TrackStatus": "12"},  # yellow mixed in
        ]
    )
    usable = filter_usable_laps(laps, green_flag_only=True)
    assert usable["LapNumber"].tolist() == [1]


def test_filter_usable_laps_empty_input():
    laps = make_laps([])
    usable = filter_usable_laps(laps)
    assert len(usable) == 0


def test_has_severe_track_condition_safety_car():
    assert has_severe_track_condition("4") is True


def test_has_severe_track_condition_yellow_only():
    # Yellow alone is not "severe" - that's the distinction from
    # is_green_flag_lap, which treats yellow the same as SC/VSC/red.
    assert has_severe_track_condition("2") is False


def test_has_severe_track_condition_concatenated():
    assert has_severe_track_condition("124") is True  # contains SC (4)


def test_has_severe_track_condition_empty():
    assert has_severe_track_condition("") is False


# --- Mixed fixture used by the classification/cross-check tests below -----
#
# One lap per exclusion reason, plus a few laps that trigger more than one
# reason simultaneously (to exercise EXCLUSION_PRECEDENCE), plus two clean
# laps. Lap numbers double as documentation of what each row represents.

_MIXED_FIXTURE_ROWS = [
    {"LapNumber": 1},  # clean
    {"LapNumber": 2, "Deleted": True},  # deleted
    {"LapNumber": 3, "PitInTime": 100.0},  # pit_in
    {"LapNumber": 4, "PitOutTime": 100.0},  # pit_out
    {"LapNumber": 5, "IsAccurate": False},  # inaccurate
    {"LapNumber": 6, "TrackStatus": "5"},  # red_flag
    {"LapNumber": 7, "TrackStatus": "4"},  # safety_car
    {"LapNumber": 8, "TrackStatus": "6"},  # virtual_safety_car (deployed)
    {"LapNumber": 9, "TrackStatus": "7"},  # virtual_safety_car (ending)
    {"LapNumber": 10, "TrackStatus": "2"},  # yellow_flag
    {"LapNumber": 11, "Deleted": True, "PitInTime": 100.0, "IsAccurate": False, "TrackStatus": "4"},  # -> deleted wins
    {"LapNumber": 12, "PitInTime": 100.0, "IsAccurate": False},  # -> pit_in wins over inaccurate
    {"LapNumber": 13, "IsAccurate": False, "TrackStatus": "4"},  # -> inaccurate wins over safety_car
    {"LapNumber": 14, "TrackStatus": "24"},  # safety_car + yellow -> safety_car wins
    {"LapNumber": 15},  # clean
]


def _mixed_fixture():
    return make_laps(_MIXED_FIXTURE_ROWS)


@pytest.mark.parametrize(
    "lap_number,expected_reason",
    [
        (1, None),
        (2, "deleted"),
        (3, "pit_in"),
        (4, "pit_out"),
        (5, "inaccurate"),
        (6, "red_flag"),
        (7, "safety_car"),
        (8, "virtual_safety_car"),
        (9, "virtual_safety_car"),
        (10, "yellow_flag"),
        (11, "deleted"),  # deleted outranks pit_in/inaccurate/safety_car
        (12, "pit_in"),  # pit_in outranks inaccurate
        (13, "inaccurate"),  # inaccurate outranks safety_car
        (14, "safety_car"),  # safety_car outranks yellow_flag
        (15, None),
    ],
)
def test_classify_lap_exclusion_reason_precedence(lap_number, expected_reason):
    laps = _mixed_fixture()
    row = laps[laps["LapNumber"] == lap_number].iloc[0]
    assert classify_lap_exclusion_reason(row) == expected_reason


def test_policy_tiers_produce_correctly_nested_subsets():
    laps = _mixed_fixture()

    all_usable = all_usable_laps(laps)
    representative = representative_race_pace_laps(laps)
    green_flag = green_flag_laps(laps)

    # Strictly more gets excluded as the policy gets stricter, so retained
    # laps only shrink (or stay equal): green_flag <= representative <= all_usable.
    assert len(green_flag) <= len(representative) <= len(all_usable) <= len(laps)

    # Every green_flag lap must also be present in the looser policies -
    # stricter policies narrow the set, they never admit laps the looser
    # ones excluded.
    assert set(green_flag["LapNumber"]).issubset(set(representative["LapNumber"]))
    assert set(representative["LapNumber"]).issubset(set(all_usable["LapNumber"]))

    # Concretely, for this fixture: only structural exclusions apply to
    # all_usable_laps (laps 2,3,4,5,11,12,13 excluded -> 8 retained of 15).
    assert len(all_usable) == 8
    # representative_race_pace additionally drops red_flag/safety_car/vsc
    # laps (6,7,8,9,14) but keeps yellow_flag (10) -> 3 retained of 15.
    assert len(representative) == 3
    # green_flag_pace additionally drops yellow_flag (10) too -> 2 retained.
    assert len(green_flag) == 2


def test_summarize_exclusions_by_policy_cross_checked_against_real_filters():
    """PRIMARY invariant: summarize_exclusions_by_policy's retained_laps
    must match what the real policy filter functions actually retain - not
    just be internally self-consistent. classify_lap_exclusion_reason is a
    second, independent implementation of "what gets excluded"; this test
    is what actually catches the two disagreeing, which the arithmetic
    reconciliation check alone cannot do (it holds by construction).
    """
    laps = _mixed_fixture()
    summary = summarize_exclusions_by_policy(laps)

    assert summary["laps_recorded"] == len(laps) == 15

    assert summary["policies"]["all_usable_laps"]["retained_laps"] == len(all_usable_laps(laps))
    assert summary["policies"]["representative_race_pace"]["retained_laps"] == len(
        representative_race_pace_laps(laps)
    )
    assert summary["policies"]["green_flag_pace"]["retained_laps"] == len(green_flag_laps(laps))


def test_summarize_exclusions_by_policy_reconciliation_invariant():
    """Secondary check: retained + excluded_laps == total for every
    policy (excluded_laps counts each excluded lap once, however many
    reasons applied to it). Cheap, holds by construction, and is NOT a
    substitute for the cross-check above.
    """
    laps = _mixed_fixture()
    summary = summarize_exclusions_by_policy(laps)

    for policy_name, policy in summary["policies"].items():
        assert policy["retained_laps"] + policy["excluded_laps"] == summary["laps_recorded"], policy_name


def test_summarize_exclusions_by_policy_is_genuinely_multi_label():
    """Multi-label means a lap with several applicable reasons is counted
    under every one of its reason buckets, so the reason-bucket counts can
    legitimately sum to more than excluded_laps - if they never did, this
    would just be single-label with extra steps.
    """
    laps = _mixed_fixture()
    summary = summarize_exclusions_by_policy(laps)

    green_flag = summary["policies"]["green_flag_pace"]
    reason_sum = sum(r["count"] for r in green_flag["excluded_by_reason"].values())
    # Lap 11 alone contributes to 4 buckets (deleted/pit_in/inaccurate/
    # safety_car), lap 12 to 2, lap 13 to 2, lap 14 to 2 - so the sum must
    # exceed the 13 distinct excluded laps.
    assert reason_sum > green_flag["excluded_laps"]


def test_excluded_laps_detail_multi_label_and_primary_reason():
    laps = _mixed_fixture()
    summary = summarize_exclusions_by_policy(laps)
    detail_by_lap = {d["lap_number"]: d for d in summary["excluded_laps_detail"]}

    # Lap 11: deleted + pit_in + inaccurate + safety_car all genuinely
    # apply - none should be masked by precedence in the detail list.
    assert detail_by_lap[11]["reasons"] == ["deleted", "pit_in", "inaccurate", "safety_car"]
    assert detail_by_lap[11]["primary_reason"] == "deleted"

    # Lap 14: safety_car + yellow_flag (TrackStatus "24").
    assert detail_by_lap[14]["reasons"] == ["safety_car", "yellow_flag"]
    assert detail_by_lap[14]["primary_reason"] == "safety_car"

    # Clean laps (1, 15) never appear in the detail list at all.
    assert 1 not in detail_by_lap
    assert 15 not in detail_by_lap

    # Sorted by lap number.
    lap_numbers = [d["lap_number"] for d in summary["excluded_laps_detail"]]
    assert lap_numbers == sorted(lap_numbers)


def test_classify_all_exclusion_reasons_returns_every_applicable_reason():
    laps = _mixed_fixture()
    row13 = laps[laps["LapNumber"] == 13].iloc[0]
    # Lap 13: inaccurate + safety_car - classify_lap_exclusion_reason
    # (single-label) only returns "inaccurate"; the multi-label version
    # must return both.
    assert classify_all_exclusion_reasons(row13) == ["inaccurate", "safety_car"]
    assert classify_lap_exclusion_reason(row13) == "inaccurate"


def test_multi_label_does_not_change_cross_check_result():
    """The multi-label refactor must not change which laps are retained
    per policy - verified directly (not just argued algebraically) against
    the same edge-case fixtures used for the Step 1 cross-check.
    """
    for rows in (
        [],
        [{"LapNumber": n, "Deleted": True} for n in range(1, 6)],
        [{"LapNumber": n, "IsAccurate": False} for n in range(1, 6)],
        _MIXED_FIXTURE_ROWS,
    ):
        laps = make_laps(rows)
        summary = summarize_exclusions_by_policy(laps)
        assert summary["policies"]["all_usable_laps"]["retained_laps"] == len(all_usable_laps(laps))
        assert summary["policies"]["representative_race_pace"]["retained_laps"] == len(
            representative_race_pace_laps(laps)
        )
        assert summary["policies"]["green_flag_pace"]["retained_laps"] == len(green_flag_laps(laps))


def test_summarize_exclusions_by_policy_lap_numbers_correct():
    """Multi-label: laps 11-14 have more than one applicable reason, so
    they appear under every bucket that applies to them, not just one.
    """
    laps = _mixed_fixture()
    summary = summarize_exclusions_by_policy(laps)

    reasons = summary["policies"]["green_flag_pace"]["excluded_by_reason"]
    assert reasons["deleted"]["lap_numbers"] == [2, 11]
    assert reasons["pit_in"]["lap_numbers"] == [3, 11, 12]
    assert reasons["pit_out"]["lap_numbers"] == [4]
    assert reasons["inaccurate"]["lap_numbers"] == [5, 11, 12, 13]
    assert reasons["red_flag"]["lap_numbers"] == [6]
    assert reasons["safety_car"]["lap_numbers"] == [7, 11, 13, 14]
    assert reasons["virtual_safety_car"]["lap_numbers"] == [8, 9]
    assert reasons["yellow_flag"]["lap_numbers"] == [10, 14]


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param([], id="empty"),
        pytest.param([{"LapNumber": n, "Deleted": True} for n in range(1, 6)], id="all_deleted"),
        pytest.param([{"LapNumber": n, "IsAccurate": False} for n in range(1, 6)], id="all_inaccurate"),
        pytest.param(
            [{"LapNumber": n} for n in range(1, 11)], id="dnf_driver_fewer_laps_than_race_distance"
        ),
        pytest.param(
            [{"LapNumber": 1, "Deleted": True}, {"LapNumber": 1, "Deleted": True}], id="duplicate_rows"
        ),
    ],
)
def test_summarize_exclusions_cross_check_on_edge_case_fixtures(rows):
    """Same PRIMARY cross-check as above, repeated across edge-case
    fixtures explicitly called out as required: empty, all-deleted,
    all-inaccurate, a DNF-like driver with fewer laps than a full race
    distance, and duplicate rows.
    """
    laps = make_laps(rows)
    summary = summarize_exclusions_by_policy(laps)

    assert summary["laps_recorded"] == len(laps)
    assert summary["policies"]["all_usable_laps"]["retained_laps"] == len(all_usable_laps(laps))
    assert summary["policies"]["representative_race_pace"]["retained_laps"] == len(
        representative_race_pace_laps(laps)
    )
    assert summary["policies"]["green_flag_pace"]["retained_laps"] == len(green_flag_laps(laps))

    # Secondary reconciliation, same as the dedicated test above.
    for policy in summary["policies"].values():
        excluded_sum = sum(r["count"] for r in policy["excluded_by_reason"].values())
        assert policy["retained_laps"] + excluded_sum == summary["laps_recorded"]


def test_summarize_exclusions_all_reason_keys_always_present():
    # Every reason bucket must exist even at 0, so persisted JSON always
    # has a stable, predictable shape for consumers to read.
    summary = summarize_exclusions_by_policy(make_laps([{"LapNumber": 1}]))
    for policy in summary["policies"].values():
        assert set(policy["excluded_by_reason"].keys()) == set(EXCLUSION_PRECEDENCE)


def test_summarize_track_conditions_groups_contiguous_ranges_across_drivers():
    # Two drivers offset by one lap for the safety car window - the union
    # across drivers should still produce one contiguous range, since a
    # Safety Car is a field-wide condition even if individual cars' laps
    # don't align perfectly in lap-number terms.
    rows = []
    for lap in range(1, 11):
        status = "4" if lap in (5, 6, 7) else "1"
        rows.append({"Driver": "AAA", "DriverNumber": "1", "LapNumber": lap, "TrackStatus": status})
    for lap in range(1, 11):
        status = "4" if lap in (6, 7, 8) else ("2" if lap == 3 else "1")
        rows.append({"Driver": "BBB", "DriverNumber": "2", "LapNumber": lap, "TrackStatus": status})

    laps = make_laps(rows)
    conditions = summarize_track_conditions(laps)

    assert {"condition": "yellow_flag", "code": "2", "start_lap": 3, "end_lap": 3} in conditions
    assert {"condition": "safety_car", "code": "4", "start_lap": 5, "end_lap": 8} in conditions
    # Sorted by start_lap.
    assert [c["start_lap"] for c in conditions] == sorted(c["start_lap"] for c in conditions)


def test_summarize_track_conditions_no_conditions_present():
    laps = make_laps([{"LapNumber": n, "TrackStatus": "1"} for n in range(1, 5)])
    assert summarize_track_conditions(laps) == []


def test_summarize_track_conditions_empty_laps():
    assert summarize_track_conditions(make_laps([])) == []
