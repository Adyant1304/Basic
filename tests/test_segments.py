"""Segment data: the stored filings must add up, and the helpers must behave.

The first test is the important one. Segment figures are transcribed by hand
from filings, and a typo is easy to make and hard to spot in a chart. Every
stored period must sum to the total its filing states.
"""

import json

import pytest

from mtm import segments as S
from mtm import views
from mtm import theme as T


def _all_entries():
    data = json.loads(S.DATA_FILE.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


@pytest.mark.parametrize("ticker", sorted(_all_entries()))
def test_every_stored_view_adds_up_to_its_stated_total(ticker):
    entry = _all_entries()[ticker]
    assert entry["views"], f"{ticker} has no views"
    for view in entry["views"]:
        assert S.check_view(view) == [], f"{ticker}: {view['title']}"


@pytest.mark.parametrize("ticker", sorted(_all_entries()))
def test_every_stored_view_names_its_source_and_period(ticker):
    for view in _all_entries()[ticker]["views"]:
        if not _all_entries()[ticker].get("illustrative"):
            assert view["source"] and view["source_url"].startswith("https://")
        assert view["kind"] in ("share", "amount")
        for p in view["periods"]:
            assert p["label"] and p["values"]


def test_apple_segments_match_the_revenue_yahoo_reports():
    """Apple's FY25 revenue on Yahoo is 416,161 (USD million)."""
    entry = S.get_segments("AAPL")
    for view in entry["views"]:
        assert sum(view["periods"][0]["values"].values()) == 416_161


def test_alias_lookup_and_case_insensitivity():
    assert S.get_segments("infy")["company"] == "Infosys"
    assert S.get_segments("INFY.NS")["company"] == "Infosys"
    assert S.get_segments("  wipro.ns ")["company"] == "Wipro"
    assert S.get_segments("NOT-STORED.NS") is None
    assert S.get_segments("") is None


def test_the_invented_sample_is_not_listed_as_covered():
    assert "SAMPLE.NS" not in S.covered_tickers()
    assert "INFY.NS" in S.covered_tickers()


def test_check_view_catches_a_typo():
    view = {"periods": [{"label": "FY26", "total": 100.0,
                         "values": {"A": 60.0, "B": 30.0}}]}      # 90, not 100
    problems = S.check_view(view)
    assert problems and "FY26" in problems[0]


def test_check_view_catches_a_negative_segment_and_an_empty_period():
    assert S.check_view({"periods": [{"label": "X", "values": {"A": -1.0, "B": 5.0}}]})
    assert S.check_view({"periods": [{"label": "X", "values": {}}]})


def test_shares_sum_to_one():
    sh = S.shares({"A": 30.0, "B": 50.0, "C": 20.0})
    assert sum(sh.values()) == pytest.approx(1.0)
    assert sh["B"] == pytest.approx(0.5)


def test_shares_of_nothing_are_zero_not_a_crash():
    assert S.shares({"A": 0.0, "B": 0.0}) == {"A": 0.0, "B": 0.0}


def test_mix_shift_is_in_points_and_sorted_by_size_of_move():
    view = {"periods": [{"label": "new", "values": {"A": 60.0, "B": 40.0}},
                        {"label": "old", "values": {"A": 50.0, "B": 50.0}}]}
    rows = S.mix_shift(view)
    assert rows[0]["shift"] == pytest.approx(10.0) or rows[0]["shift"] == pytest.approx(-10.0)
    assert {r["segment"]: round(r["shift"], 6) for r in rows} == {"A": 10.0, "B": -10.0}
    assert S.mix_shift({"periods": [view["periods"][0]]}) == []


def test_fold_tail_keeps_the_total_and_the_cap():
    vals = {f"S{i}": float(10 - i) for i in range(9)}
    out = S.fold_tail(vals, 6)
    assert len(out) == 6 and "Other segments" in out
    assert sum(out.values()) == pytest.approx(sum(vals.values()))
    assert S.fold_tail({"A": 1.0, "B": 2.0}, 6) == {"B": 2.0, "A": 1.0}


def test_user_rows_build_a_valid_view():
    v = S.view_from_rows("Mine", [("North", "120"), ("South", 80), ("", 5),
                                  ("Bad", "abc"), ("Neg", -3), ("North", 30)],
                         "USD million")
    assert v["periods"][0]["values"] == {"North": 150.0, "South": 80.0}
    assert S.check_view(v) == []


def test_user_rows_need_at_least_two_segments():
    assert S.view_from_rows("Mine", [("Only", 100)]) is None
    assert S.view_from_rows("Mine", []) is None


# --------------------------------------------------------------------------
# Colours: an entity keeps its colour
# --------------------------------------------------------------------------

def test_colours_follow_reported_order_not_size():
    view = {"periods": [{"label": "new", "values": {"A": 10.0, "B": 90.0}},
                        {"label": "old", "values": {"A": 90.0, "B": 10.0}}]}
    cm = views.colour_map(view)
    assert cm["A"] == T.SEGMENT_COLOURS[0] and cm["B"] == T.SEGMENT_COLOURS[1]
    assert S.colour_order(view) == ["A", "B"]


def test_up_to_six_segments_each_get_their_own_colour():
    vals = {f"S{i}": 10.0 for i in range(6)}
    cm = views.colour_map({"periods": [{"label": "x", "values": vals}]})
    assert len(set(cm.values())) == 6 and T.OTHER_COLOUR not in cm.values()


def test_beyond_six_the_tail_shares_grey_and_the_donut_folds_it():
    vals = {f"S{i}": float(10 - i) for i in range(8)}
    view = {"periods": [{"label": "x", "values": vals}]}
    cm = views.colour_map(view)
    assert [n for n, col in cm.items() if col == T.OTHER_COLOUR] == ["S5", "S6", "S7"]
    groups, colours = views.donut_groups(vals, view)
    assert len(groups) == 6 and groups["Other segments"] == pytest.approx(5 + 4 + 3)
    assert sum(groups.values()) == pytest.approx(sum(vals.values()))
    assert colours["Other segments"] == T.OTHER_COLOUR


def test_the_infosys_donut_never_exceeds_the_readable_slice_count():
    entry = S.get_segments("INFY.NS")
    view = entry["views"][0]                         # eight segments
    groups, _ = views.donut_groups(view["periods"][0]["values"], view)
    assert len(groups) <= S.MAX_SLICES
    assert sum(groups.values()) == pytest.approx(100.0)
