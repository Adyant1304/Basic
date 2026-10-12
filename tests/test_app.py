"""Drive the real Streamlit script and click its real widgets.

Unit tests of the engine cannot catch the failures that only exist in the
page: the "Market-implied" button raised StreamlitWidgetAlreadyInstantiatedError
for as long as it existed, and a loss-maker's margin seeded a slider outside
its range. Both are Streamlit rules about widgets, so only running the app
checks them.

Every company here is injected by patching `get_company`, so nothing touches
the network. Each test uses its own ticker because the app caches loads by
ticker.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from mtm import data as D
from mtm import peers as P
from mtm.data import Series
from mtm.sample import sample_company, sample_peer_set

APP = str(Path(__file__).resolve().parent.parent / "app.py")


@pytest.fixture(autouse=True)
def _offline_and_isolated(monkeypatch, tmp_path):
    """No test may touch the network or write into the project's data folder.

    Companies injected below claim to come from Yahoo, so without this the
    Relative value tab would call the live screener for a made-up ticker and
    save the result as a snapshot next to the real ones.
    """
    monkeypatch.setattr(D, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(P, "PEER_DIR", tmp_path / "peers")
    monkeypatch.setattr(P, "load_peer_set",
                        lambda c, custom=None, n=8: sample_peer_set())


def run(state=None, company=None, monkeypatch=None, timeout=90):
    if company is not None:
        monkeypatch.setattr(D, "get_company", lambda t, allow_network=True: company)
    at = AppTest.from_file(APP, default_timeout=timeout)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    return at.run()


def clean(at):
    assert len(at.exception) == 0, [e.value for e in at.exception]


def tab_names(at):
    return [t.label for t in at.tabs]


def text(at):
    out = [m.value for m in at.markdown] + [c.value for c in at.caption]
    out += [w.value for w in at.warning] + [i.value for i in at.info]
    return "\n".join(str(x) for x in out)


def named(ticker, **changes):
    """The sample company under another ticker, with fields overridden."""
    c = sample_company()
    c.ticker = ticker
    c.source = "yahoo"
    for k, v in changes.items():
        setattr(c, k, v)
    return c


# --------------------------------------------------------------------------
# Screens
# --------------------------------------------------------------------------

def test_the_home_screen_renders():
    at = run()
    clean(at)
    assert "What does the price" in text(at)
    assert not at.tabs                                  # no tabs before a company


def test_the_worked_example_renders_every_tab():
    at = run({"show_sample": True})
    clean(at)
    assert tab_names(at) == ["Overview", "Segments", "Relative value",
                             "Projection", "Sensitivity", "Risk",
                             "Business quality", "Audit"]
    body = text(at)
    assert "Where the beta comes from" in body
    assert "Where the revenue comes from" in body
    assert "What similar companies are priced at" in body
    assert "Peer median" in body


def test_the_overview_shows_the_business_and_the_key_figures():
    at = run({"show_sample": True})
    body = text(at)
    for needle in ("Key figures", "Financial snapshot", "Income statement",
                   "Balance sheet", "Cash flow", "Return on invested capital",
                   "Sample Services Ltd is an invented company"):
        assert needle in body, needle


# --------------------------------------------------------------------------
# The buttons that used to crash
# --------------------------------------------------------------------------

def test_market_implied_button_moves_the_growth_slider():
    at = run({"show_sample": True})
    before = at.session_state["g"]
    assert not at.button(key="snap_market").disabled
    at.button(key="snap_market").click().run()
    clean(at)
    assert at.session_state["g"] != before
    assert at.slider(key="g").value == pytest.approx(at.session_state["g"])


def test_history_button_resets_a_moved_slider():
    at = run({"show_sample": True})
    seeded = at.session_state["g"]
    at.slider(key="g").set_value(25.0).run()
    assert at.session_state["g"] == 25.0
    at.button(key="snap_history").click().run()
    clean(at)
    assert at.session_state["g"] == pytest.approx(seeded)


def test_snapping_to_market_makes_the_model_print_the_price():
    """After 'Market-implied' your growth equals the price's, so the verdict
    sentence should say the two are effectively the same."""
    at = run({"show_sample": True})
    at.button(key="snap_market").click().run()
    clean(at)
    assert "effectively the same" in text(at)


def test_a_preset_button_changes_the_company(monkeypatch):
    c = named("PRESET.NS")
    monkeypatch.setattr(D, "get_company", lambda t, allow_network=True: c)
    at = AppTest.from_file(APP, default_timeout=90)
    at.session_state["show_sample"] = True
    at.run()
    at.button(key="p_INFY.NS").click().run()
    clean(at)
    assert at.session_state["ticker"] == "INFY.NS"
    assert at.session_state["show_sample"] is False


def test_the_home_button_goes_back_to_the_home_screen():
    at = run({"show_sample": True})
    at.button(key="go_home").click().run()
    clean(at)
    assert not at.tabs and "What does the price" in text(at)


# --------------------------------------------------------------------------
# Beta
# --------------------------------------------------------------------------

def test_beta_selector_offers_every_estimate_and_defaults_to_regression():
    at = run({"show_sample": True})
    sel = at.selectbox(key="beta_src_SAMPLE.NS")
    # `.options` holds the labels the user reads; `.value` the underlying key.
    assert len(sel.options) == 4
    assert sel.options[0].startswith("Regression") and ": 0." in sel.options[0]
    assert sel.options[1].startswith("Blume-adjusted")
    assert sel.options[2].startswith("Yahoo Finance reported")
    assert sel.options[3] == "Custom"
    assert sel.value == "regression"


def test_changing_the_beta_source_changes_the_discount_rate():
    at = run({"show_sample": True})
    base_wacc = at.session_state["wacc"]
    at.selectbox(key="beta_src_SAMPLE.NS").set_value("adjusted").run()
    clean(at)
    adj = at.session_state["wacc"]
    assert adj != base_wacc
    at.selectbox(key="beta_src_SAMPLE.NS").set_value("custom").run()
    clean(at)
    at.slider(key="beta_custom_SAMPLE.NS").set_value(2.4).run()
    clean(at)
    assert at.session_state["wacc"] > adj              # higher beta, higher WACC


def test_the_custom_beta_is_not_confined_to_the_old_range():
    """The old override slider stopped at 0.3-2.5."""
    at = run({"show_sample": True})
    at.selectbox(key="beta_src_SAMPLE.NS").set_value("custom").run()
    s = at.slider(key="beta_custom_SAMPLE.NS")
    assert s.min < 0.3 and s.max > 2.5
    s.set_value(3.2).run()
    clean(at)


def test_each_company_gets_its_own_beta(monkeypatch):
    """Different companies, different betas: the thing the professor asked for."""
    lo = named("LOWBETA.NS")
    lo.beta_info = {**lo.beta_info, "raw": 0.45, "adjusted": 0.63, "default": "regression"}
    lo.beta = 0.45
    hi = named("HIGHBETA.NS")
    hi.beta_info = {**hi.beta_info, "raw": 1.65, "adjusted": 1.43, "default": "regression"}
    hi.beta = 1.65
    waccs = []
    for co in (lo, hi):
        at = run({"ticker": co.ticker}, company=co, monkeypatch=monkeypatch)
        clean(at)
        waccs.append(at.session_state["wacc"])
    assert waccs[1] > waccs[0] + 4.0                   # percentage points apart


# --------------------------------------------------------------------------
# Market-aware rates
# --------------------------------------------------------------------------

def test_a_us_stock_is_not_discounted_at_the_indian_rate(monkeypatch):
    us = named("TESTUS", currency="USD", market_key="US", live_risk_free=0.0524)
    at = run({"ticker": "TESTUS"}, company=us, monkeypatch=monkeypatch)
    clean(at)
    assert at.slider(key="rf_US").value == pytest.approx(5.24)
    assert at.slider(key="erp_US").value == pytest.approx(4.5)
    assert "live yield from Yahoo" in text(at)


def test_an_indian_stock_keeps_the_indian_defaults(monkeypatch):
    c = named("TESTIN.NS")
    at = run({"ticker": "TESTIN.NS"}, company=c, monkeypatch=monkeypatch)
    clean(at)
    assert at.slider(key="rf_IN").value == pytest.approx(6.55)
    assert at.slider(key="erp_IN").value == pytest.approx(7.0)


# --------------------------------------------------------------------------
# Slider seeds outside the slider's range
# --------------------------------------------------------------------------

def test_a_loss_makers_margin_does_not_crash_the_slider(monkeypatch):
    """A margin target below the slider's 1% floor made Streamlit raise."""
    thin = named("THIN.NS")
    thin.ebit = Series("Operating Income", list(thin.revenue.years),
                       [r * 0.003 for r in thin.revenue.values])
    at = run({"ticker": "THIN.NS"}, company=thin, monkeypatch=monkeypatch)
    clean(at)
    assert at.session_state["m"] == 1.0
    assert "slider only reaches 1 to 60" in text(at)   # and the Audit says why


def test_hypergrowth_above_the_slider_ceiling_does_not_crash(monkeypatch):
    rocket = named("ROCKET.NS")
    vals = [100.0 * 1.55 ** (4 - i) * 1e9 for i in range(5)]      # newest first
    rocket.revenue = Series("Total Revenue", list(rocket.revenue.years), vals)
    at = run({"ticker": "ROCKET.NS"}, company=rocket, monkeypatch=monkeypatch)
    clean(at)
    assert at.session_state["g"] <= 40.0


# --------------------------------------------------------------------------
# Banks and other companies a DCF does not suit
# --------------------------------------------------------------------------

def _bank(ticker):
    return named(ticker, industry="Banks - Regional", sector="Financial Services",
                 ebit=Series("missing"))


def test_a_bank_is_told_a_dcf_does_not_apply_and_the_dcf_tabs_are_hidden(monkeypatch):
    at = run({"ticker": "BANKA.NS"}, company=_bank("BANKA.NS"), monkeypatch=monkeypatch)
    clean(at)
    assert tab_names(at) == ["Overview", "Segments", "Relative value", "Audit"]
    assert "not the right tool" in text(at)
    with pytest.raises(KeyError):                 # no assumption sliders at all
        at.slider(key="g")
    # and no per-share DCF verdict was printed for it
    assert "the business is worth" not in text(at)


def test_a_bank_shows_pe_and_pb_but_not_ev_multiples(monkeypatch):
    at = run({"ticker": "BANKB.NS"}, company=_bank("BANKB.NS"), monkeypatch=monkeypatch)
    clean(at)
    assert "financial company" in text(at)
    table = next(m.value for m in at.markdown if "Peer median" in m.value)
    assert ">P/E</th>" in table and ">P/B</th>" in table
    assert "EV/EBITDA" not in table and "EV/Sales" not in table


def test_the_dcf_can_still_be_forced_on_a_bank(monkeypatch):
    c = _bank("BANKC.NS")
    at = run({"ticker": "BANKC.NS"}, company=c, monkeypatch=monkeypatch)
    at.checkbox(key="force_BANKC.NS").check().run()
    clean(at)
    assert "Projection" in tab_names(at)
    assert "treat its output as an exercise" in text(at)


# --------------------------------------------------------------------------
# Failure paths
# --------------------------------------------------------------------------

def test_an_unknown_ticker_shows_a_helpful_error_not_a_traceback(monkeypatch):
    def boom(t, allow_network=True):
        raise ValueError("NOPE: Yahoo returned no revenue history. Check the symbol "
                         "(Indian listings need a .NS or .BO suffix).")
    monkeypatch.setattr(D, "get_company", boom)
    at = run({"ticker": "NOPE"})
    assert len(at.exception) == 0
    assert any("Could not load" in e.value for e in at.error)
    assert any(".NS" in e.value for e in at.error)


def test_currency_translation_is_disclosed_on_the_page(monkeypatch):
    c = named("FXTEST.NS", financial_currency="USD", fx_rate=95.0,
              warnings=["Statements are reported in USD and were translated to INR at 95.00."])
    c.provenance = {"currency": "Yahoo reports this company's statements in USD ..."}
    at = run({"ticker": "FXTEST.NS"}, company=c, monkeypatch=monkeypatch)
    clean(at)
    assert "translated to INR at 95.00" in text(at)
    assert "Currency translation" in text(at)
