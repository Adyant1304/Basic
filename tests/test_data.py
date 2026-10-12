"""Data-layer regressions, each one a bug found by running on live Yahoo data.

`fetch` is exercised against a fake `yfinance` module so these run offline
and deterministically. The fake reproduces the failure shapes seen live:
Infosys quoted in rupees but reported in dollars, a bank with no operating
income line, and a company whose "EBIT" row includes a one-off gain.
"""

import sys
import types
from dataclasses import asdict

import numpy as np
import pandas as pd
import pytest

from mtm import data as D
from mtm.sample import sample_company


# --------------------------------------------------------------------------
# Row picking
# --------------------------------------------------------------------------

def _frame(rows: dict, years=(2026, 2025, 2024, 2023)):
    cols = [pd.Timestamp(f"{y}-03-31") for y in years]
    return pd.DataFrame(rows, index=cols).T


def test_operating_income_is_preferred_over_ebit():
    """TTML's 'EBIT' was 99.6% of revenue because of a one-off gain; the
    Operating Income row is the one that excludes it."""
    df = _frame({"EBIT": [11450, 4154, 3927, 3538],
                 "Operating Income": [4766, 4047, 3778, 3461],
                 "Total Revenue": [11501, 13009, 11868, 11012]})
    s = D._pick_row(df, D.EBIT)
    assert s.label == "Operating Income"
    assert s.values[0] == 4766


def test_ebit_is_used_only_when_operating_income_is_missing():
    df = _frame({"EBIT": [10, 9, 8, 7]})
    assert D._pick_row(df, D.EBIT).label == "EBIT"


def test_revenue_is_never_mistaken_for_ebit():
    """The original alias list ended with 'Operating Revenue', so a bank with
    no EBIT row came out with an operating margin of exactly 100%."""
    df = _frame({"Total Revenue": [100, 90, 80, 70],
                 "Operating Revenue": [100, 90, 80, 70]})
    assert D._pick_row(df, D.EBIT) is None


def test_pick_row_skips_nan_and_orders_newest_first():
    df = _frame({"Total Revenue": [np.nan, 90.0, 80.0, 70.0]})
    s = D._pick_row(df, D.REVENUE)
    assert s.years == [2025, 2024, 2023]
    assert s.values == [90.0, 80.0, 70.0]


def test_statement_table_drops_the_padded_nan_year():
    df = _frame({"Total Revenue": [10.0, 9.0, 8.0, np.nan],
                 "Net Income": [2.0, 1.8, 1.5, np.nan]})
    t = D._statement_table(df, D.INCOME_LINES, 1.0)
    assert t["years"] == [2026, 2025, 2024]
    assert t["rows"]["Revenue"] == [10.0, 9.0, 8.0]


def test_statement_table_scales_every_value():
    df = _frame({"Total Revenue": [10.0, 9.0, 8.0, 7.0]})
    t = D._statement_table(df, D.INCOME_LINES, 95.0)
    assert t["rows"]["Revenue"][0] == pytest.approx(950.0)


# --------------------------------------------------------------------------
# Currency
# --------------------------------------------------------------------------

class _FxTicker:
    def __init__(self, pairs):
        self.pairs = pairs

    def __call__(self, symbol):
        pairs = self.pairs

        class T:
            def history(self, period="5d"):
                if symbol in pairs:
                    return pd.DataFrame({"Close": [pairs[symbol] - 1, pairs[symbol]]})
                return pd.DataFrame()
        return T()


def _fake_fx(pairs):
    return types.SimpleNamespace(Ticker=_FxTicker(pairs))


def test_fx_direct_pair():
    assert D._fx_rate(_fake_fx({"USDINR=X": 95.7}), "USD", "INR") == pytest.approx(95.7)


def test_fx_inverts_when_only_the_reverse_pair_exists():
    assert D._fx_rate(_fake_fx({"INRUSD=X": 0.01}), "USD", "INR") == pytest.approx(100.0)


def test_fx_same_currency_is_one():
    assert D._fx_rate(_fake_fx({}), "INR", "INR") == 1.0


def test_fx_pence_to_pounds():
    """London prices are in pence (GBp) while statements are in pounds."""
    assert D._fx_rate(_fake_fx({}), "GBP", "GBp") == pytest.approx(100.0)


def test_fx_failure_is_loud_not_silent():
    with pytest.raises(ValueError, match="exchange rate"):
        D._fx_rate(_fake_fx({}), "USD", "INR")


# --------------------------------------------------------------------------
# Stats: the multiples Yahoo gets wrong
# --------------------------------------------------------------------------

INFY_INFO = {
    "marketCap": 4.10e12, "enterpriseValue": 4.14e12, "ebitda": 4.48e9,
    "totalRevenue": 20.3e9, "totalDebt": 1.0e9, "totalCash": 4.0e9,
    "trailingPE": 13.79, "forwardPE": 12.65, "priceToBook": 4.42,
    "dividendYield": 4.89, "trailingAnnualDividendYield": 0.0005,
    "dividendRate": 50.0, "debtToEquity": 9.5, "returnOnEquity": 0.32,
}


def test_ev_to_ebitda_is_rebuilt_in_one_currency():
    """Yahoo printed 924x for Infosys because it divided a rupee EV by a
    dollar EBITDA. After translation the multiple is sane."""
    s = D.build_stats(INFY_INFO, 1012.0, 4.10e12, 95.7, None, {})
    assert s["ev_ebitda"] == pytest.approx(
        (4.10e12 + (1.0e9 - 4.0e9) * 95.7) / (4.48e9 * 95.7))
    assert 5 < s["ev_ebitda"] < 15


def test_dividend_yield_comes_from_the_rate_not_the_stale_field():
    s = D.build_stats(INFY_INFO, 1012.0, 4.10e12, 95.7, None, {})
    assert s["dividend_yield"] == pytest.approx(50.0 / 1012.0)


def test_dividend_yield_percent_slipping_through_is_corrected():
    info = {"trailingAnnualDividendYield": 2.5}          # 2.5 meaning 2.5%
    s = D.build_stats(info, 100.0, 1e9, 1.0, None, {})
    assert s["dividend_yield"] == pytest.approx(0.025)


def test_debt_to_equity_is_a_ratio_not_a_percentage():
    s = D.build_stats(INFY_INFO, 1012.0, 4.10e12, 95.7, None, {})
    assert s["debt_to_equity"] == pytest.approx(0.095)


def test_nonsense_multiples_are_dropped():
    s = D.build_stats({"trailingPE": -5.0, "forwardPE": 9000.0,
                       "priceToBook": -0.3}, 10.0, 1e9, 1.0, None, {})
    assert s["pe"] is None and s["fwd_pe"] is None and s["pb"] is None


def test_ev_is_not_trusted_from_yahoo_when_currencies_differ():
    info = {"enterpriseValue": 1e12}                     # no debt/cash fields
    assert D.build_stats(info, 10.0, 1e9, 95.0, None, {})["ev"] is None
    assert D.build_stats(info, 10.0, 1e9, 1.0, None, {})["ev"] == 1e12


# --------------------------------------------------------------------------
# End to end against a fake yfinance
# --------------------------------------------------------------------------

def _weekly(seed, n=270, drift=0.001):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, 0.02, n)
    return r


class _FakeTicker:
    SPOT = {"USDINR=X": 95.0}

    def __init__(self, symbol, spec):
        self.symbol, self.spec = symbol, spec

    @property
    def info(self):
        return self.spec["info"]

    @property
    def income_stmt(self):
        return self.spec["inc"]

    @property
    def balance_sheet(self):
        return self.spec["bal"]

    @property
    def cashflow(self):
        return self.spec["cfs"]

    def history(self, period="5d", interval="1d", auto_adjust=True):
        if self.symbol in self.SPOT:
            return pd.DataFrame({"Close": [self.SPOT[self.symbol]] * 3},
                                index=pd.date_range("2026-10-01", periods=3))
        n = 261
        idx = pd.date_range(end="2026-10-05", periods=n, freq="7D", tz="Asia/Kolkata")
        if self.symbol.startswith("^"):
            r = _weekly(1)
            lvl = 20000 * np.concatenate([[1.0], np.cumprod(1 + r[: n - 1])])
        else:
            m = _weekly(1)[: n - 1]
            r = 0.9 * m + np.random.default_rng(7).normal(0, 0.01, n - 1)
            lvl = 1000 * np.concatenate([[1.0], np.cumprod(1 + r)])
        return pd.DataFrame({"Close": lvl, "Adj Close": lvl}, index=idx)


def _install_fake_yf(monkeypatch, spec):
    mod = types.ModuleType("yfinance")
    mod.Ticker = lambda symbol: _FakeTicker(symbol, spec)
    monkeypatch.setitem(sys.modules, "yfinance", mod)


def _spec(financial_ccy="INR", with_ebit=True, bank=False):
    inc_rows = {"Total Revenue": [200.0, 190.0, 180.0, 170.0],
                "Pretax Income": [40.0, 38.0, 36.0, 34.0],
                "Tax Provision": [10.0, 9.5, 9.0, 8.5],
                "Net Income": [30.0, 28.5, 27.0, 25.5]}
    if with_ebit:
        inc_rows["Operating Income"] = [44.0, 41.0, 39.0, 37.0]
    bal_rows = {"Total Debt": [10.0, 9.0, 8.0, 7.0],
                "Cash Cash Equivalents And Short Term Investments": [50.0, 45.0, 40.0, 35.0],
                "Stockholders Equity": [120.0, 110.0, 100.0, 90.0]}
    cf_rows = {"Operating Cash Flow": [40.0, 38.0, 36.0, 34.0],
               "Capital Expenditure": [-8.0, -7.0, -6.5, -6.0],
               "Depreciation And Amortization": [6.0, 5.5, 5.0, 4.5],
               "Change In Working Capital": [-3.0, -2.5, -2.0, -2.0]}
    mk = lambda rows: _frame(rows)
    info = {"currency": "INR", "financialCurrency": financial_ccy,
            "currentPrice": 1000.0, "sharesOutstanding": 4e9,
            "marketCap": 4e12, "longName": "Test Co", "sector": "Technology",
            "industry": "Banks - Regional" if bank else "Information Technology Services",
            "exchange": "NSI", "beta": 0.116, "trailingPE": 14.0,
            "dividendRate": 20.0, "fiftyTwoWeekHigh": 1200.0,
            "fiftyTwoWeekLow": 900.0, "longBusinessSummary": "A test company.",
            "fullTimeEmployees": 1000, "website": "https://example.com"}
    return {"info": info, "inc": mk(inc_rows), "bal": mk(bal_rows), "cfs": mk(cf_rows)}


def test_fetch_translates_dollar_statements_into_the_quote_currency(monkeypatch):
    """The Infosys bug: revenue 200 (USD) against a rupee price made every
    per-share figure about 95x too small."""
    _install_fake_yf(monkeypatch, _spec(financial_ccy="USD"))
    c = D.fetch("TEST.NS", write_snapshot=False)
    assert c.currency == "INR" and c.financial_currency == "USD"
    assert c.fx_rate == pytest.approx(95.0)
    assert c.revenue.latest == pytest.approx(200.0 * 95.0)
    assert c.total_debt == pytest.approx(10.0 * 95.0)
    assert c.cash == pytest.approx(50.0 * 95.0)
    assert c.ebit.latest == pytest.approx(44.0 * 95.0)
    assert any("translated" in w for w in c.warnings)
    assert "currency" in c.provenance
    # growth is a ratio, so translation must not change it
    assert c.revenue.cagr() == pytest.approx((200 / 170) ** (1 / 3) - 1)
    # the statements shown on the Overview are translated too
    assert c.statements["income"]["rows"]["Revenue"][0] == pytest.approx(19000.0)


def test_fetch_leaves_matching_currencies_alone(monkeypatch):
    _install_fake_yf(monkeypatch, _spec(financial_ccy="INR"))
    c = D.fetch("TEST.NS", write_snapshot=False)
    assert c.fx_rate == 1.0
    assert c.revenue.latest == 200.0
    assert "currency" not in c.provenance


def test_fetch_measures_beta_instead_of_using_yahoos(monkeypatch):
    _install_fake_yf(monkeypatch, _spec())
    c = D.fetch("TEST.NS", write_snapshot=False)
    assert c.beta_info["raw"] is not None
    assert c.beta == pytest.approx(c.beta_info["raw"])
    assert c.beta == pytest.approx(0.9, abs=0.12)        # built to have ~0.9
    assert c.beta != 0.116                                # not Yahoo's number
    assert c.beta_info["yahoo"] == pytest.approx(0.116)
    assert c.beta_info["default"] == "regression"
    assert c.beta_info["benchmark"] == "^NSEI"
    assert c.price_history["reg"]["stock"]               # kept for the chart


def test_fetch_uses_operating_income_for_margins(monkeypatch):
    _install_fake_yf(monkeypatch, _spec())
    c = D.fetch("TEST.NS", write_snapshot=False)
    assert c.ebit.label == "Operating Income"
    assert c.latest_margin() == pytest.approx(44.0 / 200.0)


def test_fetch_a_bank_has_no_ebit_and_says_so(monkeypatch):
    _install_fake_yf(monkeypatch, _spec(with_ebit=False, bank=True))
    c = D.fetch("BANK.NS", write_snapshot=False)
    assert c.ebit.values == []
    assert c.latest_margin() is None                      # not 100%
    assert any("operating income" in w.lower() for w in c.warnings)


def test_fetch_populates_the_overview_fields(monkeypatch):
    _install_fake_yf(monkeypatch, _spec())
    c = D.fetch("TEST.NS", write_snapshot=False)
    assert c.profile["summary"] == "A test company."
    assert c.profile["employees"] == 1000
    assert c.stats["dividend_yield"] == pytest.approx(0.02)
    assert c.stats["high_52w"] == 1200.0
    assert set(c.statements) == {"income", "balance", "cashflow"}
    assert c.statements["income"]["years"] == [2026, 2025, 2024, 2023]
    assert len(c.price_history["close"]) > 200
    assert c.market_key == "IN"


def test_fetch_raises_a_helpful_error_for_an_unknown_symbol(monkeypatch):
    spec = _spec()
    spec["inc"] = pd.DataFrame()
    spec["info"] = {}
    _install_fake_yf(monkeypatch, spec)
    with pytest.raises(ValueError, match=r"\.NS or \.BO"):
        D.fetch("NOTREAL", write_snapshot=False)


# --------------------------------------------------------------------------
# Snapshot compatibility
# --------------------------------------------------------------------------

def test_a_snapshot_from_an_older_build_still_loads():
    """Snapshots written before the Overview existed lack every new field."""
    d = asdict(sample_company())
    for k in ("financial_currency", "fx_rate", "market_key", "live_risk_free",
              "beta_info", "profile", "stats", "statements", "price_history",
              "industry_key", "exchange_code"):
        d.pop(k)
    c = D.Company.from_dict(d)
    assert c.beta_info == {} and c.statements == {} and c.fx_rate == 1.0


def test_a_snapshot_from_a_newer_build_is_not_rejected():
    d = asdict(sample_company())
    d["some_future_field"] = 123
    assert D.Company.from_dict(d).name == sample_company().name


def test_new_fields_survive_a_json_round_trip():
    c = sample_company()
    back = D.Company.from_dict(__import__("json").loads(c.to_json()))
    assert back.beta_info["raw"] == pytest.approx(c.beta_info["raw"])
    assert back.statements["income"]["rows"]["Revenue"] == c.statements["income"]["rows"]["Revenue"]
    assert back.price_history["reg"]["stock"] == c.price_history["reg"]["stock"]
