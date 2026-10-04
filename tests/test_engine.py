"""Engine tests. The point of a deterministic model is that it can be checked.

The key test is `test_matches_hand_calculation`, which verifies the DCF
against a figure worked out independently from the formula. If that passes,
the engine is doing arithmetic rather than something that merely looks like
arithmetic.
"""

import math

import pytest

from mtm.engine import (Assumptions, build_wacc, baseline_assumptions,
                        project, reverse_dcf, sensitivity_grid, tornado,
                        monte_carlo, fan_chart)
from mtm.metrics import (quality_metrics, valuation_metrics, sanity_flags,
                         consensus_implied)
from mtm.sample import sample_company


@pytest.fixture
def company():
    return sample_company()


@pytest.fixture
def setup(company):
    w = build_wacc(company)
    a, _ = baseline_assumptions(company, w.wacc)
    return company, a, w


# --------------------------------------------------------------------------
# Correctness of the arithmetic
# --------------------------------------------------------------------------

def test_matches_hand_calculation():
    """Check the engine against a DCF computed independently here.

    A deliberately simple case: flat 10% growth for 3 years, constant 20%
    margin, 25% tax, sales-to-capital 4.0, WACC 10%, terminal growth 4%,
    terminal ROIC 20%.
    """
    c = sample_company()
    c.revenue.values[0] = 1_000.0          # clean base
    c.total_debt = 0.0
    c.cash = 0.0
    c.shares_out = 100.0

    a = Assumptions(growth_near=0.10, margin_target=0.20, wacc=0.10,
                    growth_terminal=0.04, tax_rate=0.25,
                    sales_to_capital=4.0, roic_terminal=0.20,
                    years=3, margin_start=0.20)
    p = project(c, a)

    # Revenue: 1100, 1210, 1331  (3 years held at 10%, no taper room)
    assert p.revenue == pytest.approx([1100.0, 1210.0, 1331.0])

    # NOPAT = revenue x 0.20 x 0.75
    expected_nopat = [r * 0.20 * 0.75 for r in (1100.0, 1210.0, 1331.0)]
    assert p.nopat == pytest.approx(expected_nopat)

    # Reinvestment = delta revenue / 4
    expected_reinvest = [100.0 / 4, 110.0 / 4, 121.0 / 4]
    assert p.reinvestment == pytest.approx(expected_reinvest)

    expected_fcff = [n - r for n, r in zip(expected_nopat, expected_reinvest)]
    assert p.fcff == pytest.approx(expected_fcff)

    pv = sum(f / 1.10 ** t for t, f in enumerate(expected_fcff, start=1))
    assert p.pv_explicit == pytest.approx(pv)

    # Terminal value, with growth funded at 20% ROIC -> 20% reinvestment rate
    nopat_next = expected_nopat[-1] * 1.04
    fcff_next = nopat_next * (1 - 0.04 / 0.20)
    tv = fcff_next / (0.10 - 0.04)
    assert p.terminal_value == pytest.approx(tv)
    assert p.pv_terminal == pytest.approx(tv / 1.10 ** 3)
    assert p.enterprise_value == pytest.approx(pv + tv / 1.10 ** 3)
    assert p.value_per_share == pytest.approx((pv + tv / 1.10 ** 3) / 100.0)


def test_deterministic(setup):
    """Same inputs, same output. Every time."""
    c, a, _ = setup
    first = project(c, a).value_per_share
    for _ in range(25):
        assert project(c, a).value_per_share == first


def test_zero_growth_is_a_perpetuity(setup):
    """With no growth there is no reinvestment, so FCFF equals NOPAT."""
    c, a, _ = setup
    a = a.with_(growth_near=0.0, growth_terminal=0.0,
                margin_start=0.20, margin_target=0.20)
    p = project(c, a)
    assert all(abs(r) < 1e-6 for r in p.reinvestment)
    assert p.fcff == pytest.approx(p.nopat)


def test_higher_growth_raises_value_when_roic_beats_wacc(setup):
    c, a, w = setup
    assert a.roic_terminal > w.wacc
    lo = project(c, a.with_(growth_near=a.growth_near - 0.02)).value_per_share
    hi = project(c, a.with_(growth_near=a.growth_near + 0.02)).value_per_share
    assert hi > lo


def test_higher_wacc_lowers_value(setup):
    c, a, _ = setup
    lo = project(c, a.with_(wacc=a.wacc + 0.02)).value_per_share
    hi = project(c, a.with_(wacc=a.wacc - 0.02)).value_per_share
    assert hi > lo


def test_wacc_floor_prevents_blowup(setup):
    """Terminal growth above WACC must not produce a negative or infinite value."""
    c, a, _ = setup
    p = project(c, a.with_(wacc=0.05, growth_terminal=0.09))
    assert math.isfinite(p.value_per_share)
    assert p.value_per_share > 0


def test_growth_taper_reaches_terminal(setup):
    c, a, _ = setup
    p = project(c, a.with_(years=10))
    assert p.growth[0] == pytest.approx(a.growth_near)
    assert p.growth[2] == pytest.approx(a.growth_near)   # held 3 years
    assert p.growth[-1] < p.growth[0]                     # tapering down
    assert p.growth[-1] > a.growth_terminal               # not yet terminal


def test_margin_taper_endpoints(setup):
    c, a, _ = setup
    p = project(c, a.with_(margin_start=0.18, margin_target=0.24, years=6))
    assert p.margin[-1] == pytest.approx(0.24)
    assert 0.18 < p.margin[0] < 0.24


# --------------------------------------------------------------------------
# Reverse DCF
# --------------------------------------------------------------------------

def test_reverse_dcf_recovers_the_price(setup):
    """Feed the solved growth back in and the model should print the price."""
    c, a, _ = setup
    g = reverse_dcf(c, a, "growth_near")
    assert g is not None
    back = project(c, a.with_(growth_near=g)).value_per_share
    assert back == pytest.approx(c.price, rel=1e-3)


def test_reverse_dcf_on_wacc(setup):
    c, a, _ = setup
    w = reverse_dcf(c, a, "wacc")
    assert w is not None
    back = project(c, a.with_(wacc=w)).value_per_share
    assert back == pytest.approx(c.price, rel=1e-3)


def test_reverse_dcf_returns_none_when_unreachable(setup):
    """An absurd price is out of range, and the solver says so rather than lying."""
    c, a, _ = setup
    c.price = 1e12
    assert reverse_dcf(c, a, "growth_near") is None


# --------------------------------------------------------------------------
# WACC
# --------------------------------------------------------------------------

def test_wacc_build(company):
    w = build_wacc(company, risk_free=0.065, erp=0.07)
    assert w.cost_of_equity == pytest.approx(0.065 + 0.82 * 0.07)
    assert 0.0 <= w.weight_debt < 0.05        # the sample is nearly debt-free
    assert w.weight_equity + w.weight_debt == pytest.approx(1.0)
    assert w.wacc < w.cost_of_equity + 1e-9


def test_beta_is_clamped(company):
    company.beta = 9.0
    assert build_wacc(company).beta == 2.5
    company.beta = None
    w = build_wacc(company)
    assert w.beta == 1.0
    assert any("Beta" in n for n in w.notes)


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------

def test_baseline_is_grounded_in_history(company):
    w = build_wacc(company)
    a, prov = baseline_assumptions(company, w.wacc)
    assert 0.0 < a.growth_near < 0.25
    assert 0.0 < a.margin_target < 0.5
    assert a.growth_terminal < w.risk_free      # capped below risk-free
    assert a.roic_terminal > w.wacc
    # Every assumption explains itself.
    for k in ("growth_near", "margin_target", "growth_terminal",
              "roic_terminal", "sales_to_capital", "tax_rate"):
        assert k in prov and prov[k]


def test_effective_tax_rate_is_sane(company):
    assert 0.12 <= company.effective_tax_rate() <= 0.40


def test_sales_to_capital_is_sane(company):
    assert 0.8 <= company.sales_to_capital() <= 8.0


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------

def test_sensitivity_grid_shape(setup):
    c, a, _ = setup
    g = sensitivity_grid(c, a, steps=5)
    assert len(g["value"]) == 5 and len(g["value"][0]) == 5
    # Along a row (rising WACC) value must fall.
    row = [v for v in g["value"][2] if math.isfinite(v)]
    assert row == sorted(row, reverse=True)


def test_tornado_is_ranked_and_nonempty(setup):
    c, a, _ = setup
    t = tornado(c, a)
    assert len(t) >= 4
    assert [d["swing"] for d in t] == sorted(
        [d["swing"] for d in t], reverse=True)


def test_monte_carlo_distribution(setup):
    c, a, _ = setup
    mc = monte_carlo(c, a, n=2000)
    p = mc["percentiles"]
    assert p[5] < p[25] < p[50] < p[75] < p[95]
    assert 0.0 <= mc["prob_above_price"] <= 1.0
    assert mc["n"] > 1900


def test_monte_carlo_is_reproducible(setup):
    c, a, _ = setup
    first = monte_carlo(c, a, n=1000, seed=3)["percentiles"]
    second = monte_carlo(c, a, n=1000, seed=3)["percentiles"]
    assert first == second


def test_monte_carlo_centre_tracks_the_point_estimate(setup):
    """The median draw should land near the deterministic answer."""
    c, a, _ = setup
    point = project(c, a).value_per_share
    median = monte_carlo(c, a, n=4000)["percentiles"][50]
    assert median == pytest.approx(point, rel=0.12)


def test_fan_chart_bands_are_ordered(setup):
    c, a, _ = setup
    f = fan_chart(c, a, n=500)
    for i in range(len(f["years"])):
        assert f["p5"][i] <= f["p25"][i] <= f["p50"][i] <= f["p75"][i] <= f["p95"][i]


# --------------------------------------------------------------------------
# Metrics and flags
# --------------------------------------------------------------------------

def test_metrics_all_carry_a_reading(setup):
    c, a, w = setup
    p = project(c, a)
    for m in quality_metrics(c, a, p, w) + valuation_metrics(c, a, p, w):
        assert m.reading and len(m.reading) > 20
        assert m.direction in ("higher", "lower", "stable")
        assert m.band
        assert m.display(c.currency) != ""


def test_flags_catch_terminal_growth_above_risk_free(setup):
    c, a, w = setup
    a = a.with_(growth_terminal=0.09)
    p = project(c, a)
    flags = sanity_flags(c, a, p, w, risk_free=0.065)
    assert any(f.severity == "error" and "risk-free" in f.title
               for f in flags)


def test_flags_catch_margin_above_peak(setup):
    c, a, w = setup
    a = a.with_(margin_target=0.50)
    p = project(c, a)
    flags = sanity_flags(c, a, p, w, risk_free=0.065)
    assert any("historical peak" in f.title for f in flags)


def test_flags_catch_growth_above_record(setup):
    c, a, w = setup
    a = a.with_(growth_near=0.45)
    p = project(c, a)
    flags = sanity_flags(c, a, p, w, risk_free=0.065)
    assert any("record" in f.title for f in flags)


def test_baseline_is_mostly_clean(setup):
    """A history-seeded baseline should not trip hard errors."""
    c, a, w = setup
    p = project(c, a)
    flags = sanity_flags(c, a, p, w, risk_free=0.0655)
    assert not [f for f in flags if f.severity == "error"]


def test_consensus_implied(setup):
    c, a, _ = setup
    ci = consensus_implied(c, a)
    assert ci is not None
    assert ci["target"] == c.target_mean
    assert ci["n"] == c.n_analysts


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------

def test_snapshot_round_trip(tmp_path, monkeypatch, company):
    from mtm import data as data_mod
    monkeypatch.setattr(data_mod, "SNAPSHOT_DIR", tmp_path)
    data_mod.save_snapshot(company)
    back = data_mod.load_snapshot(company.ticker)
    assert back.name == company.name
    assert back.revenue.values == company.revenue.values
    assert back.source == "sample"
    w1, w2 = build_wacc(company), build_wacc(back)
    assert w1.wacc == pytest.approx(w2.wacc)
