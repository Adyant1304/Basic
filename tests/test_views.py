"""The logic behind the Overview, Segments and Relative value tabs."""

import math

import pytest

from mtm import charts, peers as P, segments as S, theme as T, views
from mtm.engine import baseline_assumptions, build_wacc, project
from mtm.markets import market_for
from mtm.sample import sample_company, sample_peer_set


@pytest.fixture
def company():
    return sample_company()


@pytest.fixture
def wacc(company):
    return build_wacc(company, beta_label="regression")


def _items(groups):
    return {i["label"]: i for _, items in groups for i in items}


# --------------------------------------------------------------------------
# KPI tiles
# --------------------------------------------------------------------------

def test_kpis_cover_four_groups_and_never_print_python_junk(company, wacc):
    groups = views.kpi_groups(company, wacc)
    assert [g for g, _ in groups] == [
        "The market", "What it is priced at", "How well the business earns",
        "Balance sheet and cash"]
    for _, items in groups:
        for it in items:
            assert it["label"] and it["value"]
            assert "None" not in it["value"] and "nan" not in it["value"].lower()


def test_beta_tile_shows_the_beta_actually_used(company, wacc):
    t = _items(views.kpi_groups(company, wacc))["Beta"]
    assert t["value"] == f"{wacc.beta:.2f}"
    assert t["sub"] == "regression"


def test_a_lender_shows_ev_multiples_as_not_meaningful(company, wacc):
    t = _items(views.kpi_groups(company, wacc, financial=True))
    for label in ("EV / EBITDA", "EV / Sales", "Enterprise value",
                  "Net debt / EBITDA", "Return on invested capital"):
        assert t[label]["value"] == "n/m", label
    assert t["P/E, trailing"]["value"] != "n/m"       # P/E still applies


def test_net_cash_is_called_net_cash(company, wacc):
    t = _items(views.kpi_groups(company, wacc))["Net debt / EBITDA"]
    assert t["value"].startswith("-")                 # the sample has net cash
    assert "net cash" in t["sub"]


def test_missing_data_degrades_to_na_rather_than_crashing(company, wacc):
    company.stats = {}
    company.statements = {}
    company.price_history = {}
    company.profile = {}
    groups = views.kpi_groups(company, wacc)
    assert len(groups) == 4


def test_the_52_week_tile_carries_a_position_marker(company, wacc):
    t = _items(views.kpi_groups(company, wacc))["52-week range"]
    assert 0.0 <= t["marker"] <= 1.0


# --------------------------------------------------------------------------
# Statements
# --------------------------------------------------------------------------

def test_income_statement_has_growth_and_margin_rows(company):
    headers, rows, classes = views.statement_table(company, "income")
    assert headers[:2] == ["", "FY2026"]
    labels = [r[0] for r in rows]
    assert "Revenue" in labels and "Revenue growth" in labels
    assert "Operating margin" in labels and "Net margin" in labels
    growth = rows[labels.index("Revenue growth")]
    assert growth[1].startswith("+8.") and growth[-1] == ""     # oldest year has no prior
    assert classes[labels.index("Revenue growth")] == "sub"


def test_statement_amounts_are_in_crore_with_indian_grouping(company):
    _, rows, _ = views.statement_table(company, "income")
    rev = next(r for r in rows if r[0] == "Revenue")
    assert rev[1] == "41,200"                         # 412bn rupees in crore
    eps = next(r for r in rows if r[0] == "Diluted EPS")
    assert eps[1].startswith("₹") and "." in eps[1]


def test_statement_table_is_none_when_nothing_was_stored(company):
    company.statements = {}
    assert views.statement_table(company, "income") is None


def test_dollar_statements_are_shown_in_millions():
    c = sample_company()
    c.currency = "USD"
    _, rows, _ = views.statement_table(c, "income")
    rev = next(r for r in rows if r[0] == "Revenue")
    assert rev[1] == f"{412e9 / 1e6:,.0f}"


# --------------------------------------------------------------------------
# Beta table
# --------------------------------------------------------------------------

def test_beta_table_lists_every_estimate_and_the_one_used(company, wacc):
    headers, rows, classes = views.beta_table(company, wacc)
    labels = [r[0] for r in rows]
    assert any(l.startswith("Regression") for l in labels)
    assert any("Blume" in l for l in labels)
    assert any("Yahoo" in l for l in labels)
    assert rows[-1][0] == "Used in the WACC" and classes[-1] == "agg"
    assert rows[-1][1] == f"{wacc.beta:.2f}"


# --------------------------------------------------------------------------
# Relative value
# --------------------------------------------------------------------------

def test_comparison_table_puts_the_company_first_and_the_median_last(company):
    ps = sample_peer_set()
    summary = P.summarize(ps["rows"])
    headers, rows, classes = views.comparison_table(company, ps["rows"], summary, False)
    assert classes[0] == "me" and rows[0][0] == company.name
    assert classes[-2:] == ["agg", "sub"] and rows[-2][0] == "Peer median"
    assert "EV/EBITDA" in headers and len(rows) == len(ps["rows"]) + 3
    mcaps = [r[1] for r in rows[1:-2]]
    assert len(mcaps) == len(ps["rows"])
    assert all(len(r) == len(headers) for r in rows)


def test_comparison_table_drops_ev_columns_for_a_lender(company):
    ps = sample_peer_set()
    headers, rows, _ = views.comparison_table(company, ps["rows"],
                                              P.summarize(ps["rows"]), True)
    assert "EV/EBITDA" not in headers and "EV/Sales" not in headers
    assert "P/E" in headers and "P/B" in headers
    assert all(len(r) == len(headers) for r in rows)


def test_premium_row_reports_a_discount_as_negative(company):
    ps = sample_peer_set()
    _, rows, _ = views.comparison_table(company, ps["rows"], P.summarize(ps["rows"]), False)
    prem = rows[-1]
    pe_col = 2
    assert prem[pe_col].startswith("-")        # 17.9x against peers near 20x


def test_football_rows_include_each_method_once(company):
    ps = sample_peer_set()
    implied = P.implied_values(company, P.summarize(ps["rows"]))
    dcf = {"point": 1000.0, "p5": 700.0, "p95": 1400.0}
    rows = views.football_rows(company, implied, dcf)
    labels = [r["label"] for r in rows]
    assert labels[0].startswith("Your DCF")
    assert "Analyst targets" in labels and "52-week trading range" in labels
    assert sum(1 for l in labels if l.startswith("Peer ")) == len(implied)
    assert all(r["low"] <= r["high"] for r in rows)
    assert {r["group"] for r in rows} <= {"dcf", "consensus", "relative", "market"}


def test_football_rows_without_a_dcf_for_a_lender(company):
    implied = P.implied_values(company, P.summarize(sample_peer_set()["rows"]))
    rows = views.football_rows(company, implied, None)
    assert not any(r["group"] == "dcf" for r in rows)


def test_reading_compares_peers_with_the_dcf(company):
    ps = sample_peer_set()
    implied = P.implied_values(company, P.summarize(ps["rows"]))
    up = views.valuation_reading(company, implied, {"point": company.price * 1.3})
    assert "peer multiples value" in up and "lean the same way" in up or "disagree" in up
    split = views.valuation_reading(company, implied, {"point": company.price * 0.5})
    assert "disagree" in split
    assert views.valuation_reading(company, [], None) == ""


# --------------------------------------------------------------------------
# Segment table
# --------------------------------------------------------------------------

def test_segment_table_total_row_and_changes():
    view = S.get_segments("WIPRO.NS")["views"][0]
    new, old = view["periods"][0], view["periods"][1]
    headers, rows, cells = views.segment_table(view, new, old)
    assert headers[0] == "Segment" and "Change" in headers
    assert rows[-1][0] == "Total" and rows[-1][-2] == "100.0%"
    assert len(rows) == len(view["periods"][0]["values"]) + 1
    americas2 = next(r for r in rows if r[0] == "Americas 2")
    assert americas2[-1].startswith("-")                  # lost share FY25 -> FY26
    assert all(len(r) == len(headers) for r in rows)
    assert all(len(r) == len(c) for r, c in zip(rows, cells))


def test_share_views_have_no_amount_column():
    view = S.get_segments("INFY.NS")["views"][0]
    headers, _, _ = views.segment_table(view, view["periods"][0], None)
    assert not any(h.startswith("Revenue") for h in headers)


def test_amount_formatting():
    assert views.fmt_amount(30557.1, "INR crore") == "₹30,557 cr"
    assert views.fmt_amount(209586, "USD million") == "$209,586m"
    assert views.fmt_amount(5, "widgets") == "5"


@pytest.mark.parametrize("raw,shown", [
    ("TATA CONSULTANCY SERV LT", "Tata Consultancy Serv"),
    ("HCL TECHNOLOGIES LTD", "HCL Technologies"),
    ("WIPRO LTD", "Wipro"),
    ("TECH MAHINDRA LIMITED", "Tech Mahindra"),
    ("LTM LIMITED", "LTM"),
    ("STATE BANK OF INDIA", "State Bank of India"),
    ("Microsoft Corporation", "Microsoft Corporation"),     # already readable
    ("NVIDIA Corporation", "NVIDIA Corporation"),
    ("", ""),
])
def test_peer_names_are_made_readable(raw, shown):
    assert views.nice_name(raw) == shown


def test_negative_money_puts_the_sign_before_the_symbol():
    assert T.per_share(-3.2, "USD") == "-$3"
    assert T.per_share(-1250.0, "INR") == "-₹1,250"
    assert T.money(-5e9, "USD") == "-$5.0bn"
    assert T.money(-4.2e9, "INR") == "-₹420 cr"
    assert T.per_share(1250.0, "INR") == "₹1,250"       # positives unchanged


def test_a_negative_equity_value_is_explained_not_expressed_as_a_percentage():
    """TTML printed 'worth -₹64 a share, 291.6% below the market'."""
    from mtm import components as ui
    html_ = ui.verdict(-64.0, 33.0, "INR", 0.0)
    assert "worth less than its debt" in html_ and "-₹64" in html_
    assert "below the market" not in html_
    ok = ui.verdict(836.0, 1013.0, "INR", 0.1)
    assert "below the market" in ok and "less than its debt" not in ok


def test_text_columns_can_be_left_aligned():
    from mtm import components as ui
    h = ui.html_table(["Name", "Value", "Note"], [["a", "1", "text"]],
                      left_cols=(2,))
    assert h.count('class="l"') == 2                   # the header and the cell
    assert '<td class="l">text</td>' in h and '<th class="l">Note</th>' in h
    assert '<td class="">1</td>' in h                  # numbers stay right-aligned


def test_the_yahoo_beta_caveat_only_applies_to_indian_listings(company, wacc):
    _, rows, _ = views.beta_table(company, wacc)
    assert any("unreliable for Indian" in r[2] for r in rows)
    company.ticker = "AAPL"
    _, rows, _ = views.beta_table(company, wacc)
    yahoo = next(r for r in rows if r[0].startswith("Yahoo"))
    assert "Indian" not in yahoo[2]


def test_a_zero_shift_never_prints_a_negative_zero():
    assert T.points(-0.004) == "0.0 pts"
    assert T.points(0.0) == "0.0 pts"
    assert T.points(-0.0) == "0.0 pts"
    assert T.points(0.74) == "+0.7 pts"
    assert T.points(-0.46) == "-0.5 pts"


def test_the_price_chart_closes_on_the_live_price(company):
    """Weekly bars stop at the last completed week, so without this the chart
    ended at one price and the header showed another."""
    company.price = 1234.0
    company.fetched_at = "2026-10-12T08:00:00+00:00"
    fig = charts.price_chart(company)
    assert list(fig.data[0].y)[-1] == 1234.0
    assert list(fig.data[0].x)[-1] == "2026-10-12"


# --------------------------------------------------------------------------
# Markets
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ticker,key,bench", [
    ("INFY.NS", "IN", "^NSEI"), ("ttml.bo", "IN", "^BSESN"),
    ("AAPL", "US", "^GSPC"), ("BP.L", "OTHER:United Kingdom", "^FTSE"),
    ("7203.T", "OTHER:Japan", "^N225"), ("", "US", "^GSPC")])
def test_market_lookup(ticker, key, bench):
    m = market_for(ticker)
    assert m.key == key and m.benchmark == bench


def test_the_us_market_does_not_inherit_indian_rates():
    """The original build discounted Apple at an Indian 6.55% risk-free rate."""
    us, india = market_for("AAPL"), market_for("INFY.NS")
    assert us.risk_free < india.risk_free
    assert us.erp < india.erp
    assert us.live_rf_symbol == "^TNX" and india.live_rf_symbol is None


# --------------------------------------------------------------------------
# Charts build on the sample without raising
# --------------------------------------------------------------------------

def test_every_new_chart_builds(company):
    assert charts.price_chart(company) is not None
    assert charts.beta_scatter(company) is not None
    assert charts.history_bars(company) is not None
    ps = sample_peer_set()
    summary = P.summarize(ps["rows"])
    implied = P.implied_values(company, summary)
    assert charts.football_field(
        views.football_rows(company, implied, {"point": 1, "p5": 0.5, "p95": 2}),
        company.price, "INR") is not None
    assert charts.peer_bars([P.self_row(company)] + ps["rows"], "pe", "P/E",
                            company.ticker, summary["pe"]["median"]) is not None
    view = S.get_segments("INFY.NS")["views"][0]
    groups, colours = views.donut_groups(view["periods"][0]["values"], view)
    assert charts.segment_donut(groups, colours, "Q4 FY26") is not None
    names = list(view["periods"][0]["values"])
    assert charts.segment_bars(names, [1.0] * len(names), ["x"] * len(names)) is not None
    assert charts.segment_shift(S.mix_shift(view), "Q4 FY25", "Q4 FY26") is not None


def test_history_chart_has_no_second_y_axis(company):
    """One axis per panel: the original dual-axis chart invented a
    relationship between revenue and margin that the data does not contain."""
    fig = charts.history_bars(company)
    assert fig.layout.yaxis2 is not None            # the lower panel
    assert not any(getattr(t, "yaxis", None) == "y3" for t in fig.data)
    overlaying = [getattr(fig.layout, k).overlaying for k in
                  ("yaxis", "yaxis2") if getattr(fig.layout, k).overlaying]
    assert overlaying == []


def test_charts_return_none_without_data(company):
    company.price_history = {}
    assert charts.price_chart(company) is None
    assert charts.beta_scatter(company) is None


def test_dcf_still_runs_on_the_sample_with_a_measured_beta(company):
    w = build_wacc(company)
    a, _ = baseline_assumptions(company, w.wacc)
    p = project(company, a)
    assert math.isfinite(p.value_per_share) and p.value_per_share > 0
