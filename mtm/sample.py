"""A synthetic company, for tests and for a first run with no network.

These figures are invented. They are shaped like a mid-sized Indian IT
services firm so the UI and the engine can be exercised end to end, but
nothing here is real data about any real company, and the app labels it
clearly whenever it is in use.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np

from . import beta as beta_mod
from .data import Company, Series

_YEARS = [2026, 2025, 2024, 2023, 2022]

# Revenue in rupees, newest first: a business compounding around 9%.
_REVENUE = [412_000_000_000, 379_000_000_000, 348_000_000_000,
            314_000_000_000, 281_000_000_000]
_EBIT = [86_500_000_000, 77_800_000_000, 73_100_000_000,
         68_100_000_000, 63_800_000_000]
_NET = [66_900_000_000, 60_200_000_000, 56_400_000_000,
        52_600_000_000, 49_300_000_000]
_DA = [11_200_000_000, 10_400_000_000, 9_800_000_000,
       9_100_000_000, 8_400_000_000]
_CAPEX = [-14_800_000_000, -13_200_000_000, -12_600_000_000,
          -11_400_000_000, -10_900_000_000]
_CHG_WC = [-6_200_000_000, -5_400_000_000, -7_100_000_000,
           -4_800_000_000, -5_900_000_000]
_OCF = [74_100_000_000, 67_300_000_000, 61_900_000_000,
        58_200_000_000, 54_100_000_000]
_FCF = [59_300_000_000, 54_100_000_000, 49_300_000_000,
        46_800_000_000, 43_200_000_000]
_PRETAX = [88_300_000_000, 79_400_000_000, 74_600_000_000,
           69_500_000_000, 65_100_000_000]
_TAX = [21_400_000_000, 19_200_000_000, 18_200_000_000,
        16_900_000_000, 15_800_000_000]

_PRICE = 1_148.0
_SHARES = 1_040_000_000
_TRUE_BETA = 0.82


def _synthetic_prices(n: int = 261) -> dict:
    """Five years of weekly prices with a known beta of about 0.82.

    Seeded, so every run is identical. The beta printed in the app is then
    *measured* from these returns by the same regression used on real data,
    which keeps the demo honest about how the number is produced.
    """
    rng = np.random.default_rng(42)
    mkt = rng.normal(0.0016, 0.022, n - 1)
    stk = 0.0004 + _TRUE_BETA * mkt + rng.normal(0.0, 0.017, n - 1)

    def levels(returns, end_level):
        path = np.concatenate([[1.0], np.cumprod(1 + returns)])
        return path / path[-1] * end_level

    px, bx = levels(stk, _PRICE), levels(mkt, 24_800.0)
    last = date(2026, 10, 5)
    dates = [(last - timedelta(weeks=n - 1 - i)).isoformat() for i in range(n)]
    return {"dates": dates, "stock": [float(v) for v in px],
            "bench": [float(v) for v in bx]}


def sample_company() -> Company:
    # Copy every list. Handing out the module-level lists would let one
    # caller's mutation leak into every later call.
    def s(label: str, values: list[float]) -> Series:
        return Series(label, list(_YEARS), list(values))

    syn = _synthetic_prices()
    est = beta_mod.estimate_from_prices(syn["stock"], syn["bench"])
    beta_info = beta_mod.bundle(est, "^NSEI", "Nifty 50 (synthetic)",
                                "weekly", 5, 0.12, syn["dates"][-1])
    beta_info["default"] = "regression"

    ebitda = [e + d for e, d in zip(_EBIT, _DA)]
    income_rows = {
        "Revenue": list(_REVENUE),
        "Gross profit": [r * 0.31 for r in _REVENUE],
        "EBITDA": ebitda,
        "Operating income": list(_EBIT),
        "Pretax income": list(_PRETAX),
        "Net income": list(_NET),
        "Diluted EPS": [n / _SHARES for n in _NET],
    }
    equity = [288e9, 262e9, 238e9, 217e9, 199e9]
    balance_rows = {
        "Total assets": [e * 1.42 for e in equity],
        "Cash and short-term investments": [132e9, 121e9, 108e9, 99e9, 91e9],
        "Receivables": [r * 0.19 for r in _REVENUE],
        "Current assets": [e * 0.93 for e in equity],
        "Current liabilities": [e * 0.27 for e in equity],
        "Total debt": [18.4e9, 17.9e9, 16.8e9, 16.1e9, 15.6e9],
        "Shareholders' equity": equity,
    }
    cash_rows = {
        "Operating cash flow": list(_OCF),
        "Capital expenditure": list(_CAPEX),
        "Free cash flow": list(_FCF),
        "Dividends paid": [-28e9, -25e9, -23e9, -21e9, -19e9],
        "Share buybacks": [-12e9, -9e9, -10e9, 0.0, 0.0],
    }

    c = Company(
        ticker="SAMPLE.NS",
        name="Sample Services Ltd (illustrative data)",
        sector="Technology",
        industry="Information Technology Services",
        currency="INR",
        price=_PRICE,
        shares_out=_SHARES,
        market_cap=_PRICE * _SHARES,
        revenue=s("Total Revenue", _REVENUE),
        ebit=s("Operating Income", _EBIT),
        net_income=s("Net Income", _NET),
        da=s("Depreciation And Amortization", _DA),
        capex=s("Capital Expenditure", _CAPEX),
        chg_wc=s("Change In Working Capital", _CHG_WC),
        ocf=s("Operating Cash Flow", _OCF),
        fcf=s("Free Cash Flow", _FCF),
        total_debt=18_400_000_000,
        cash=132_000_000_000,
        equity_book=288_000_000_000,
        invested_capital=241_000_000_000,
        interest_expense=1_480_000_000,
        beta=est.beta if est else _TRUE_BETA,
        trailing_pe=17.9,
        forward_pe=16.3,
        analyst_growth=0.082,
        target_mean=1_242.0,
        n_analysts=34,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source="sample",
        financial_currency="INR",
        market_key="IN",
        beta_info=beta_info,
        profile={
            "summary": (
                "Sample Services Ltd is an invented company used to show the "
                "tool without a network connection. It resembles a mid-sized "
                "Indian IT services firm: asset-light, cash-rich, growing in "
                "the high single digits. None of the figures describe a real "
                "business."),
            "website": "", "employees": 128_000,
            "location": "Bengaluru, Karnataka, India",
            "exchange": "NSE (illustrative)", "quote_type": "EQUITY",
        },
        stats={
            "high_52w": 1_322.0, "low_52w": 1_011.0, "avg_volume": 5.2e6,
            "dividend_yield": 0.027, "payout_ratio": 0.42,
            "pe": 17.9, "fwd_pe": 16.3, "pb": _PRICE * _SHARES / 288e9,
            "ps": _PRICE * _SHARES / _REVENUE[0],
            "ev": _PRICE * _SHARES + 18.4e9 - 132e9, "ebitda": ebitda[0],
            "ev_ebitda": (_PRICE * _SHARES + 18.4e9 - 132e9) / ebitda[0],
            "ev_sales": (_PRICE * _SHARES + 18.4e9 - 132e9) / _REVENUE[0],
            "revenue_ttm": _REVENUE[0], "roe": 0.232, "roa": 0.131,
            "gross_margin": 0.31, "op_margin": _EBIT[0] / _REVENUE[0],
            "net_margin": _NET[0] / _REVENUE[0], "rev_growth": 0.087,
            "earn_growth": 0.111, "current_ratio": 3.4, "quick_ratio": 3.3,
            "debt_to_equity": 18.4 / 288, "fcf": _FCF[0], "eps": _PRICE / 17.9,
            "target_low": 1_010.0, "target_high": 1_460.0,
            "target_mean": 1_242.0, "recommendation": "buy",
        },
        statements={
            "income": {"years": list(_YEARS), "rows": income_rows},
            "balance": {"years": list(_YEARS), "rows": balance_rows},
            "cashflow": {"years": list(_YEARS), "rows": cash_rows},
        },
        price_history={
            "dates": syn["dates"], "close": syn["stock"],
            "reg": {"dates": syn["dates"], "stock": syn["stock"],
                    "bench": syn["bench"]},
        },
        industry_key="information-technology-services",
        exchange_code="NSI",
    )
    c._pretax = s("Pretax Income", _PRETAX)
    c._tax = s("Tax Provision", _TAX)
    return c


def sample_peer_set() -> dict:
    """Invented peers, shaped like the rows the live screener returns."""
    def row(ticker, name, mcap, pe, fpe, pb, eveb, evs, roe, om, g, dy):
        return {"ticker": ticker, "name": name,
                "industry": "Information Technology Services",
                "currency": "INR", "price": 100.0, "market_cap": mcap,
                "pe": pe, "fwd_pe": fpe, "pb": pb, "ev_ebitda": eveb,
                "ev_sales": evs, "roe": roe, "op_margin": om,
                "net_margin": om * 0.78, "rev_growth": g,
                "dividend_yield": dy}

    rows = [
        row("ALPHA.NS", "Alpha Systems (invented)", 4.1e12, 21.4, 18.9, 5.6, 14.1, 3.0, 0.27, 0.22, 0.09, 0.021),
        row("BRAVO.NS", "Bravo Digital (invented)", 2.6e12, 19.8, 17.2, 4.9, 12.8, 2.6, 0.24, 0.21, 0.07, 0.025),
        row("CHARLIE.NS", "Charlie Infotech (invented)", 1.9e12, 16.2, 14.8, 3.4, 10.4, 2.0, 0.19, 0.18, 0.06, 0.031),
        row("DELTA.NS", "Delta Software (invented)", 1.5e12, 24.9, 21.5, 6.8, 16.9, 3.4, 0.29, 0.23, 0.12, 0.014),
        row("ECHO.NS", "Echo Services (invented)", 1.1e12, 14.9, 13.1, 2.9, 9.2, 1.7, 0.17, 0.16, 0.05, 0.036),
        row("FOXTROT.NS", "Foxtrot Tech (invented)", 8.6e11, 28.3, 23.4, 7.5, 19.2, 3.9, 0.31, 0.24, 0.14, 0.009),
    ]
    return {"method": "Invented peers for the worked example. Not real companies.",
            "rows": rows, "fetched_at": "", "source": "sample", "custom": False}
