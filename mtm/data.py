"""Data layer: pull everything the model needs from Yahoo Finance.

Design rules
------------
1. One pass per ticker. Everything downstream is arithmetic.
2. Never trust a single label spelling. Yahoo renames line items between
   companies and filings, so every lookup tries a list of aliases.
3. Always degrade instead of crashing. A missing line item becomes None and
   the engine falls back to a documented default, with the fallback recorded
   in `Company.provenance` so the UI can show what was inferred.
4. Snapshots. `fetch()` writes a JSON snapshot; if the network is gone the
   app loads the snapshot instead. Demos do not depend on wifi.
5. One currency. Yahoo quotes a share in one currency and sometimes reports
   its statements in another (Infosys: INR price, USD financials). Every
   monetary figure is translated into the *trading* currency before it
   reaches the engine, and the translation is recorded in the provenance.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import beta as beta_mod
from .markets import Market, market_for

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"

# --------------------------------------------------------------------------
# Line-item aliases. Yahoo's labels drift; we try each in order.
# --------------------------------------------------------------------------
REVENUE = ["Total Revenue", "Operating Revenue", "Revenue"]
# Operating Income first. The "EBIT" row is pretax income plus interest, so it
# carries other income and one-off gains: TTML's FY26 "EBIT" was 99.6% of
# revenue because of an exceptional gain. Operating Income excludes all of
# that, which also stops treasury income being counted twice (once in the
# margin, once again when cash is added back to equity).
EBIT = ["Operating Income", "EBIT"]
PRETAX = ["Pretax Income", "Income Before Tax"]
TAX = ["Tax Provision", "Income Tax Expense"]
NET_INCOME = ["Net Income", "Net Income Common Stockholders",
              "Net Income Continuous Operations"]
DA = ["Depreciation And Amortization", "Depreciation Amortization Depletion",
      "Depreciation"]
CAPEX = ["Capital Expenditure", "Purchase Of PPE", "Net PPE Purchase And Sale"]
CHG_WC = ["Change In Working Capital", "Changes In Working Capital"]
OCF = ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]
FCF = ["Free Cash Flow"]
TOTAL_DEBT = ["Total Debt"]
LT_DEBT = ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]
ST_DEBT = ["Current Debt", "Current Debt And Capital Lease Obligation"]
CASH = ["Cash Cash Equivalents And Short Term Investments",
        "Cash And Cash Equivalents", "Cash Financial"]
EQUITY = ["Stockholders Equity", "Total Equity Gross Minority Interest"]
INVESTED_CAPITAL = ["Invested Capital"]
INTEREST_EXP = ["Interest Expense", "Interest Expense Non Operating"]

# What the Snapshot tab shows. Label -> aliases.
INCOME_LINES = [
    ("Revenue", REVENUE),
    ("Gross profit", ["Gross Profit"]),
    ("EBITDA", ["EBITDA", "Normalized EBITDA"]),
    ("Operating income", EBIT),
    ("Pretax income", PRETAX),
    ("Net income", NET_INCOME),
    ("Diluted EPS", ["Diluted EPS", "Basic EPS"]),
]
BALANCE_LINES = [
    ("Total assets", ["Total Assets"]),
    ("Cash and short-term investments", CASH),
    ("Receivables", ["Accounts Receivable", "Receivables"]),
    ("Inventory", ["Inventory"]),
    ("Current assets", ["Current Assets"]),
    ("Current liabilities", ["Current Liabilities"]),
    ("Total debt", TOTAL_DEBT),
    ("Shareholders' equity", EQUITY),
]
CASHFLOW_LINES = [
    ("Operating cash flow", OCF),
    ("Capital expenditure", CAPEX),
    ("Free cash flow", FCF),
    ("Dividends paid", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
    ("Share buybacks", ["Repurchase Of Capital Stock", "Common Stock Payments"]),
]
PER_SHARE_LINES = {"Diluted EPS"}

# Yahoo quotes some venues in a minor unit (pence, cents, agorot).
_MINOR_UNITS = {"GBp": ("GBP", 0.01), "GBX": ("GBP", 0.01),
                "ZAc": ("ZAR", 0.01), "ILA": ("ILS", 0.01)}


@dataclass
class Series:
    """A line item through time, newest first."""

    label: str
    years: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)

    @property
    def latest(self) -> float | None:
        return self.values[0] if self.values else None

    def cagr(self, periods: int | None = None) -> float | None:
        """Compound growth from oldest to newest, both must be positive."""
        v = self.values if periods is None else self.values[: periods + 1]
        if len(v) < 2:
            return None
        new, old = v[0], v[-1]
        n = len(v) - 1
        if old <= 0 or new <= 0:
            return None
        return (new / old) ** (1 / n) - 1

    def yoy(self) -> list[float]:
        out = []
        for newer, older in zip(self.values, self.values[1:]):
            if older and older > 0:
                out.append(newer / older - 1)
        return out

    def scaled(self, k: float) -> "Series":
        return Series(self.label, list(self.years),
                      [v * k for v in self.values])


@dataclass
class Company:
    """Everything the valuation engine needs, in one object."""

    ticker: str
    name: str
    sector: str
    industry: str
    currency: str
    price: float
    shares_out: float
    market_cap: float

    revenue: Series
    ebit: Series
    net_income: Series
    da: Series
    capex: Series
    chg_wc: Series
    ocf: Series
    fcf: Series

    total_debt: float
    cash: float
    equity_book: float
    invested_capital: float | None
    interest_expense: float | None

    beta: float | None
    trailing_pe: float | None
    forward_pe: float | None
    analyst_growth: float | None
    target_mean: float | None
    n_analysts: int | None

    fetched_at: str
    source: str = "yahoo"          # "yahoo" | "snapshot" | "sample"
    provenance: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # Everything below is optional so snapshots saved by an older build still
    # load. Each defaults to "nothing known" and the UI says so.
    financial_currency: str = ""    # what Yahoo reports statements in
    fx_rate: float = 1.0            # financial -> trading currency, spot
    market_key: str = ""            # "IN" | "US" | "OTHER:..."
    live_risk_free: float | None = None   # e.g. the live US 10-year yield
    beta_info: dict = field(default_factory=dict)
    profile: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    statements: dict = field(default_factory=dict)
    price_history: dict = field(default_factory=dict)
    industry_key: str = ""
    exchange_code: str = ""

    # ---------------- derived history, used to seed the sliders -----------

    @property
    def fiscal_years(self) -> list[int]:
        return self.revenue.years

    @property
    def market(self) -> Market:
        return market_for(self.ticker)

    def hist_revenue_growth(self) -> float | None:
        return self.revenue.cagr()

    def hist_margins(self) -> list[float]:
        """Operating margin per year where both lines exist."""
        out = []
        rev_by_year = dict(zip(self.revenue.years, self.revenue.values))
        for yr, e in zip(self.ebit.years, self.ebit.values):
            r = rev_by_year.get(yr)
            if r and r > 0:
                out.append(e / r)
        return out

    def latest_margin(self) -> float | None:
        m = self.hist_margins()
        return m[0] if m else None

    def median_margin(self) -> float | None:
        m = self.hist_margins()
        return statistics.median(m) if m else None

    def margin_stability(self) -> float | None:
        """Standard deviation of operating margin. Lower is more predictable."""
        m = self.hist_margins()
        return statistics.pstdev(m) if len(m) > 1 else None

    def effective_tax_rate(self, lo: float = 0.12, hi: float = 0.40) -> float:
        """Tax provision over pretax income, clamped to a believable band."""
        rates = []
        pre = dict(zip(self._pretax.years, self._pretax.values)) if self._pretax else {}
        for yr, t in zip(self._tax.years, self._tax.values) if self._tax else []:
            p = pre.get(yr)
            if p and p > 0 and t is not None:
                rates.append(t / p)
        if rates:
            r = statistics.median(rates)
            if lo <= r <= hi:
                return r
        self.provenance["tax_rate"] = (
            "defaulted to 25%: the reported tax rate was missing or outside "
            "the 12-40% band")
        return 0.25

    def sales_to_capital(self, lo: float = 0.8, hi: float = 8.0) -> float:
        """Revenue added per unit of currency reinvested.

        Reinvestment = capex - D&A + change in working capital.
        Asset-light services businesses sit high (3-6x); manufacturers low.
        """
        rev = dict(zip(self.revenue.years, self.revenue.values))
        capex = dict(zip(self.capex.years, self.capex.values))
        da = dict(zip(self.da.years, self.da.values))
        wc = dict(zip(self.chg_wc.years, self.chg_wc.values))

        ratios = []
        for newer, older in zip(self.revenue.years, self.revenue.years[1:]):
            d_rev = rev.get(newer, 0) - rev.get(older, 0)
            cx = abs(capex.get(newer, 0) or 0)
            dp = abs(da.get(newer, 0) or 0)
            # Yahoo reports change in WC as a cash-flow effect: a cash
            # outflow (working capital build) is negative. Reinvestment
            # needs the build as a positive number.
            d_wc = -(wc.get(newer, 0) or 0)
            reinvest = cx - dp + d_wc
            if d_rev > 0 and reinvest > 0:
                ratios.append(d_rev / reinvest)
        if ratios:
            r = statistics.median(ratios)
            if lo <= r <= hi:
                return r
        self.provenance["sales_to_capital"] = (
            "defaulted to 3.5x: reinvestment history was missing or gave a "
            "ratio outside 0.8-8x")
        return 3.5

    def roic(self) -> float | None:
        """NOPAT over invested capital."""
        e = self.ebit.latest
        if e is None:
            return None
        nopat = e * (1 - self.effective_tax_rate())
        ic = self.invested_capital
        if not ic or ic <= 0:
            # Fall back to book equity plus debt minus cash.
            ic = (self.equity_book or 0) + (self.total_debt or 0) - (self.cash or 0)
        if not ic or ic <= 0:
            return None
        return nopat / ic

    def fcf_conversion(self) -> float | None:
        """Free cash flow over net income. Near or above 1.0 is healthy."""
        f, n = self.fcf.latest, self.net_income.latest
        if f is None or not n or n <= 0:
            return None
        return f / n

    def net_cash_per_share(self) -> float | None:
        if not self.shares_out:
            return None
        return ((self.cash or 0) - (self.total_debt or 0)) / self.shares_out

    def cost_of_debt(self, risk_free: float) -> float:
        """Interest expense over total debt, floored at the risk-free rate."""
        if self.interest_expense and self.total_debt and self.total_debt > 0:
            r = abs(self.interest_expense) / self.total_debt
            if risk_free <= r <= 0.25:
                return r
        return risk_free + 0.015

    # Private series kept off the public surface but needed by the methods
    # above. Populated by `fetch`.
    _pretax: Series | None = None
    _tax: Series | None = None

    # ------------------------------ persistence --------------------------

    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, indent=2, default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Company":
        series_fields = ["revenue", "ebit", "net_income", "da", "capex",
                         "chg_wc", "ocf", "fcf", "_pretax", "_tax"]
        known = {f_.name for f_ in fields(cls)}
        # Ignore keys this build does not know, so a snapshot written by a
        # newer version never stops an older one from loading.
        kwargs = {k: v for k, v in d.items() if k in known}
        for f_ in series_fields:
            v = kwargs.get(f_)
            kwargs[f_] = Series(**v) if isinstance(v, dict) else None
        return cls(**kwargs)


# --------------------------------------------------------------------------
# Yahoo extraction
# --------------------------------------------------------------------------

def _num(x: Any) -> float | None:
    """A plain finite Python float, or None. Keeps JSON clean."""
    if isinstance(x, bool) or x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _pick_row(df, aliases: list[str]) -> Series | None:
    """Find the first alias present in the frame and return it as a Series."""
    if df is None or getattr(df, "empty", True):
        return None
    index = {str(i).strip().lower(): i for i in df.index}
    for alias in aliases:
        key = alias.strip().lower()
        if key in index:
            row = df.loc[index[key]]
            years, values = [], []
            for col, val in row.items():
                v = _num(val)
                if v is None:
                    continue
                years.append(int(getattr(col, "year", 0)) or 0)
                values.append(v)
            if years:
                order = sorted(range(len(years)), key=lambda i: years[i], reverse=True)
                return Series(alias,
                              [years[i] for i in order],
                              [values[i] for i in order])
    return None


def _sum_rows(df, alias_groups: list[list[str]]) -> float | None:
    """Latest value of the sum of several rows, e.g. short + long debt."""
    total, found = 0.0, False
    for group in alias_groups:
        s = _pick_row(df, group)
        if s and s.latest is not None:
            total += s.latest
            found = True
    return total if found else None


def _statement_table(df, lines, scale: float) -> dict:
    """A statement as {years, rows}, newest year first, in trading currency."""
    if df is None or getattr(df, "empty", True):
        return {}
    years = sorted({int(getattr(c, "year", 0)) for c in df.columns
                    if getattr(c, "year", 0)}, reverse=True)
    rows: dict[str, list[float | None]] = {}
    for label, aliases in lines:
        s = _pick_row(df, aliases)
        if s is None:
            continue
        by_year = dict(zip(s.years, s.values))
        rows[label] = [(by_year[y] * scale) if y in by_year else None
                       for y in years]
    # Drop trailing years where nothing was reported (Yahoo pads a NaN column).
    keep = [i for i in range(len(years))
            if any(r[i] is not None for r in rows.values())]
    if not keep:
        return {}
    return {"years": [years[i] for i in keep],
            "rows": {k: [v[i] for i in keep] for k, v in rows.items()}}


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _first_num(d: dict, keys: list[str]) -> float | None:
    for k in keys:
        v = _num(d.get(k))
        if v is not None and v != 0:
            return v
    return None


def _major(code: str) -> tuple[str, float]:
    """Map a minor-unit currency code (GBp) to its major unit and scale."""
    return _MINOR_UNITS.get(code, (code, 1.0))


def _fx_rate(yf, from_ccy: str, to_ccy: str) -> float:
    """Latest spot rate, `from` -> `to`. Raises if Yahoo cannot supply one."""
    f_major, f_scale = _major(from_ccy)
    t_major, t_scale = _major(to_ccy)
    if f_major == t_major:
        return f_scale / t_scale
    rate = None
    for pair, invert in ((f"{f_major}{t_major}=X", False),
                         (f"{t_major}{f_major}=X", True)):
        h = _safe(lambda p=pair: yf.Ticker(p).history(period="5d"))
        if h is not None and not h.empty:
            last = _num(h["Close"].dropna().iloc[-1])
            if last and last > 0:
                rate = 1.0 / last if invert else last
                break
    if rate is None:
        raise ValueError(
            f"Yahoo reports this company's statements in {from_ccy} but quotes "
            f"the share in {to_ccy}, and the {from_ccy}/{to_ccy} exchange rate "
            f"could not be fetched to translate them.")
    return rate * f_scale / t_scale


def _weekly_history(yf, symbol: str, years: int = 5):
    """Weekly bars as a DataFrame with `close` and `adj` columns, or None."""
    import pandas as pd

    h = _safe(lambda: yf.Ticker(symbol).history(
        period=f"{years}y", interval="1wk", auto_adjust=False))
    if h is None or h.empty or "Close" not in h:
        return None
    out = pd.DataFrame({
        "close": h["Close"],
        "adj": h["Adj Close"] if "Adj Close" in h else h["Close"],
    }).dropna()
    idx = pd.to_datetime(out.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    out.index = idx.normalize()
    return out[~out.index.duplicated(keep="last")]


def _beta_and_history(yf, ticker: str, market: Market,
                      yahoo_beta: float | None) -> tuple[dict, dict]:
    """Regression beta against the local index, plus the price series."""
    import pandas as pd

    stock = _weekly_history(yf, ticker)
    history: dict = {}
    if stock is not None and len(stock) > 8:
        history = {
            "dates": [d.strftime("%Y-%m-%d") for d in stock.index],
            "close": [round(float(v), 4) for v in stock["close"]],
        }
    bench = _weekly_history(yf, market.benchmark)
    est = None
    as_of = ""
    if stock is not None and bench is not None:
        joined = pd.concat([stock["adj"], bench["adj"]], axis=1,
                           join="inner").dropna()
        if len(joined) > 1:
            est = beta_mod.estimate_from_prices(joined.iloc[:, 0].to_numpy(),
                                                joined.iloc[:, 1].to_numpy())
            as_of = joined.index[-1].strftime("%Y-%m-%d")
            if est is not None:
                # Kept so the Snapshot tab can draw the regression itself.
                history["reg"] = {
                    "dates": [d.strftime("%Y-%m-%d") for d in joined.index],
                    "stock": [round(float(v), 4) for v in joined.iloc[:, 0]],
                    "bench": [round(float(v), 4) for v in joined.iloc[:, 1]],
                }
    return (beta_mod.bundle(est, market.benchmark, market.benchmark_name,
                            "weekly", 5, yahoo_beta, as_of), history)


def _live_risk_free(yf, market: Market) -> float | None:
    if not market.live_rf_symbol:
        return None
    h = _safe(lambda: yf.Ticker(market.live_rf_symbol).history(period="5d"))
    if h is None or h.empty:
        return None
    v = _num(h["Close"].dropna().iloc[-1])
    # Yahoo quotes these yields in percent (5.24 means 5.24%).
    return v / 100 if v and 0 < v < 25 else None


def _positive(x: float | None, cap: float) -> float | None:
    return x if x is not None and 0 < x < cap else None


def build_stats(info: dict, price: float, mcap: float, fx: float,
                net_debt: float | None, statements: dict) -> dict:
    """KPI figures for the Snapshot and Relative-value tabs.

    Ratios are taken from Yahoo where they are currency-free. Anything that
    divides a trading-currency number by a statement-currency number (EV over
    EBITDA is the classic) is rebuilt here after translation, because Yahoo's
    own version is wrong whenever the two currencies differ: it showed
    Infosys at 924x EBITDA.
    """
    def pick(*keys):
        return _first_num(info, list(keys))

    # Enterprise value is rebuilt rather than read. Yahoo's own figure mixes
    # currencies for foreign listings (an ADR's EV can be market cap in
    # dollars plus debt in rupees), so TSMC came out at 165x EBITDA and ASML
    # at 2,500x. Market cap plus translated net debt is consistent by design.
    debt_i, cash_i = _num(info.get("totalDebt")), _num(info.get("totalCash"))
    if mcap and debt_i is not None and cash_i is not None:
        ev = mcap + (debt_i - cash_i) * fx
    elif mcap and net_debt is not None:
        ev = mcap + net_debt
    elif fx == 1.0:
        ev = pick("enterpriseValue")
    else:
        ev = None

    ebitda = _num(info.get("ebitda"))
    ebitda = ebitda * fx if ebitda else None
    if not ebitda:
        row = statements.get("income", {}).get("rows", {}).get("EBITDA")
        ebitda = next((v for v in (row or []) if v), None)
    revenue_ttm = _num(info.get("totalRevenue"))
    revenue_ttm = revenue_ttm * fx if revenue_ttm else None
    if not revenue_ttm:
        row = statements.get("income", {}).get("rows", {}).get("Revenue")
        revenue_ttm = next((v for v in (row or []) if v), None)

    rate = _num(info.get("dividendRate"))
    if rate and price:
        div_yield = rate / price
    else:
        div_yield = _num(info.get("trailingAnnualDividendYield"))
        if div_yield is not None and div_yield > 0.3:
            div_yield = div_yield / 100      # a percent slipped through

    de = _num(info.get("debtToEquity"))
    pe = _positive(pick("trailingPE"), 500)
    fpe = _positive(pick("forwardPE"), 500)

    fcf = _num(info.get("freeCashflow"))
    fcf = fcf * fx if fcf else None

    return {
        "high_52w": pick("fiftyTwoWeekHigh"),
        "low_52w": pick("fiftyTwoWeekLow"),
        "avg_volume": pick("averageVolume", "averageDailyVolume3Month"),
        "dividend_yield": div_yield,
        "payout_ratio": _num(info.get("payoutRatio")),
        "pe": pe,
        "fwd_pe": fpe,
        "pb": _positive(pick("priceToBook"), 200),
        "ps": _positive(pick("priceToSalesTrailing12Months"), 500),
        "ev": ev,
        "ebitda": ebitda,
        "ev_ebitda": ev / ebitda if ev and ebitda and ebitda > 0 else None,
        "ev_sales": ev / revenue_ttm if ev and revenue_ttm else None,
        "revenue_ttm": revenue_ttm,
        "roe": _num(info.get("returnOnEquity")),
        "roa": _num(info.get("returnOnAssets")),
        "gross_margin": _num(info.get("grossMargins")),
        "op_margin": _num(info.get("operatingMargins")),
        "net_margin": _num(info.get("profitMargins")),
        "rev_growth": _num(info.get("revenueGrowth")),
        "earn_growth": _num(info.get("earningsGrowth")),
        "current_ratio": _num(info.get("currentRatio")),
        "quick_ratio": _num(info.get("quickRatio")),
        "debt_to_equity": de / 100 if de is not None else None,
        "fcf": fcf,
        "eps": price / pe if pe else None,
        "target_low": pick("targetLowPrice"),
        "target_high": pick("targetHighPrice"),
        "target_mean": pick("targetMeanPrice"),
        "recommendation": info.get("recommendationKey") or "",
    }


def build_profile(info: dict) -> dict:
    parts = [info.get("city"), info.get("state"), info.get("country")]
    return {
        "summary": (info.get("longBusinessSummary") or "").strip(),
        "website": info.get("website") or "",
        "employees": int(info["fullTimeEmployees"])
        if _num(info.get("fullTimeEmployees")) else None,
        "location": ", ".join(p for p in parts if p),
        "exchange": info.get("fullExchangeName") or info.get("exchange") or "",
        "quote_type": info.get("quoteType") or "",
    }


def fetch(ticker: str, write_snapshot: bool = True) -> Company:
    """Pull a company from Yahoo Finance. Raises on network failure."""
    import yfinance as yf

    ticker = ticker.strip()
    t = yf.Ticker(ticker)

    # `info` is the flakiest endpoint, so guard it and fall back.
    info: dict[str, Any] = {}
    try:
        info = t.info or {}
    except Exception:
        pass

    inc = _safe(lambda: t.income_stmt)
    bal = _safe(lambda: t.balance_sheet)
    cfs = _safe(lambda: t.cashflow)

    revenue = _pick_row(inc, REVENUE)
    if revenue is None or not revenue.values:
        raise ValueError(
            f"{ticker}: Yahoo returned no revenue history. Check the symbol "
            f"(Indian listings need a .NS or .BO suffix)."
        )

    price = _first_num(info, ["currentPrice", "regularMarketPrice",
                              "previousClose"])
    if price is None:
        hist = _safe(lambda: t.history(period="5d"))
        if hist is not None and not hist.empty:
            price = _num(hist["Close"].dropna().iloc[-1])
    if price is None:
        raise ValueError(f"{ticker}: could not resolve a market price.")

    shares = _first_num(info, ["sharesOutstanding", "impliedSharesOutstanding"])
    mcap = _first_num(info, ["marketCap"])
    if not shares and mcap:
        shares = mcap / price
    if not shares:
        raise ValueError(f"{ticker}: could not resolve shares outstanding.")

    warnings: list[str] = []
    prov: dict[str, str] = {}

    # ---- one currency ------------------------------------------------------
    trading = info.get("currency") or "INR"
    fin = info.get("financialCurrency") or trading
    fx = 1.0
    if _major(fin)[0] != _major(trading)[0] or _major(fin)[1] != _major(trading)[1]:
        fx = _fx_rate(yf, fin, trading)
        prov["currency"] = (
            f"Yahoo reports this company's statements in {fin} but the share "
            f"trades in {trading}. Every statement figure was translated at "
            f"today's spot rate of {fx:,.4f} {trading} per {fin}, so growth "
            f"rates are those of the {fin} accounts and absolute levels carry "
            f"today's exchange rate.")
        warnings.append(
            f"Statements are reported in {fin} and were translated to "
            f"{trading} at {fx:,.2f}. Growth reflects the {fin} accounts, so "
            f"it excludes any currency drift. Check the Audit tab.")
        if info.get("quoteType") == "EQUITY" and "." not in ticker:
            warnings.append(
                "This looks like a foreign listing (ADR). The share count and "
                "ADR ratio may not match the quoted price; prefer the home "
                "listing if there is one.")

    def sc(s: Series | None) -> Series | None:
        return s.scaled(fx) if s is not None and fx != 1.0 else s

    revenue = sc(revenue)

    debt = _pick_row(bal, TOTAL_DEBT)
    total_debt = debt.latest if debt else _sum_rows(bal, [LT_DEBT, ST_DEBT])
    total_debt = (total_debt or 0.0) * fx

    cash_s = _pick_row(bal, CASH)
    equity_s = _pick_row(bal, EQUITY)
    ic_s = _pick_row(bal, INVESTED_CAPITAL)
    int_s = _pick_row(inc, INTEREST_EXP)

    ebit = sc(_pick_row(inc, EBIT))
    if ebit is None:
        warnings.append(
            "No operating income line was reported, which is normal for banks "
            "and insurers. Operating margin and the DCF cannot be built.")
    else:
        prov["ebit"] = (
            f"Operating margin uses Yahoo's '{ebit.label}' line. "
            + ("It excludes interest and other non-operating income, so cash "
               "earnings are not counted twice."
               if ebit.label == "Operating Income" else
               "Operating Income was missing, so EBIT was used; it can include "
               "other income and one-off items."))

    fcf = sc(_pick_row(cfs, FCF))
    if fcf is None:
        # Derive it: operating cash flow less capex.
        ocf_s = sc(_pick_row(cfs, OCF))
        cx_s = sc(_pick_row(cfs, CAPEX))
        if ocf_s and cx_s:
            by_year = dict(zip(cx_s.years, cx_s.values))
            yrs, vals = [], []
            for y, o in zip(ocf_s.years, ocf_s.values):
                if y in by_year:
                    yrs.append(y)
                    vals.append(o - abs(by_year[y]))
            if yrs:
                fcf = Series("Derived FCF", yrs, vals)
                prov["fcf"] = "derived as operating cash flow less capex"

    market = market_for(ticker)
    yahoo_beta = _num(info.get("beta"))
    beta_info, history = _safe(
        lambda: _beta_and_history(yf, ticker, market, yahoo_beta)
    ) or (beta_mod.bundle(None, market.benchmark, market.benchmark_name,
                          "weekly", 5, yahoo_beta), {})

    beta = None
    reg = beta_info.get("raw")
    if reg is not None:
        beta = float(reg)
        beta_info["default"] = "regression"
        prov["beta"] = (
            f"{beta_info['years']}-year weekly regression against the "
            f"{market.benchmark_name} ({beta_info['n']} observations, "
            f"R-squared {beta_info['r2']:.2f}). Yahoo's own field said "
            f"{yahoo_beta if yahoo_beta is not None else 'nothing'}.")
    elif yahoo_beta is not None:
        beta = yahoo_beta
        beta_info["default"] = "yahoo"
        prov["beta"] = ("could not regress against the index, so Yahoo's "
                        "reported beta was used")
    else:
        beta_info["default"] = ""
        prov["beta"] = "not available; the WACC build falls back to 1.0"

    statements = {
        "income": _statement_table(inc, INCOME_LINES, fx),
        "balance": _statement_table(bal, BALANCE_LINES, fx),
        "cashflow": _statement_table(cfs, CASHFLOW_LINES, fx),
    }
    net_debt = total_debt - float((cash_s.latest if cash_s and cash_s.latest
                                   else 0.0) * fx)

    empty = Series("missing")
    c = Company(
        ticker=ticker.upper(),
        name=info.get("longName") or info.get("shortName") or ticker.upper(),
        sector=info.get("sector") or "Unclassified",
        industry=info.get("industry") or "",
        currency=trading,
        price=float(price),
        shares_out=float(shares),
        market_cap=float(mcap or price * shares),
        revenue=revenue,
        ebit=ebit or empty,
        net_income=sc(_pick_row(inc, NET_INCOME)) or empty,
        da=sc(_pick_row(cfs, DA)) or empty,
        capex=sc(_pick_row(cfs, CAPEX)) or empty,
        chg_wc=sc(_pick_row(cfs, CHG_WC)) or empty,
        ocf=sc(_pick_row(cfs, OCF)) or empty,
        fcf=fcf or empty,
        total_debt=float(total_debt or 0.0),
        cash=float((cash_s.latest if cash_s and cash_s.latest else 0.0) * fx),
        equity_book=float((equity_s.latest
                           if equity_s and equity_s.latest else 0.0) * fx),
        invested_capital=float(ic_s.latest * fx)
        if ic_s and ic_s.latest else None,
        interest_expense=float(int_s.latest * fx)
        if int_s and int_s.latest else None,
        beta=beta,
        trailing_pe=_positive(_first_num(info, ["trailingPE"]), 500),
        forward_pe=_positive(_first_num(info, ["forwardPE"]), 500),
        analyst_growth=_first_num(info, ["revenueGrowth"]),
        target_mean=_first_num(info, ["targetMeanPrice"]),
        n_analysts=int(info["numberOfAnalystOpinions"])
        if _num(info.get("numberOfAnalystOpinions")) else None,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source="yahoo",
        provenance=prov,
        warnings=warnings,
        financial_currency=fin,
        fx_rate=fx,
        market_key=market.key,
        live_risk_free=_safe(lambda: _live_risk_free(yf, market)),
        beta_info=beta_info,
        profile=build_profile(info),
        stats=build_stats(info, float(price), float(mcap or price * shares),
                          fx, net_debt, statements),
        statements=statements,
        price_history=history,
        industry_key=info.get("industryKey") or "",
        exchange_code=info.get("exchange") or "",
    )
    c._pretax = sc(_pick_row(inc, PRETAX))
    c._tax = sc(_pick_row(inc, TAX))

    if len(revenue.values) < 3:
        c.warnings.append(
            f"Only {len(revenue.values)} years of revenue history; growth and "
            "margin baselines are weakly supported."
        )

    if write_snapshot:
        try:
            save_snapshot(c)
        except OSError:
            pass
    return c


# --------------------------------------------------------------------------
# Snapshots: the offline path
# --------------------------------------------------------------------------

def save_snapshot(c: Company) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    p = SNAPSHOT_DIR / f"{c.ticker}.json"
    p.write_text(c.to_json(), encoding="utf-8")
    return p


def load_snapshot(ticker: str) -> Company:
    p = SNAPSHOT_DIR / f"{ticker.upper()}.json"
    if not p.exists():
        raise FileNotFoundError(f"No snapshot for {ticker} at {p}")
    d = json.loads(p.read_text(encoding="utf-8"))
    c = Company.from_dict(d)
    if c.source == "yahoo":
        c.source = "snapshot"
    return c


def available_snapshots() -> list[str]:
    if not SNAPSHOT_DIR.exists():
        return []
    return sorted(p.stem for p in SNAPSHOT_DIR.glob("*.json"))


def get_company(ticker: str, allow_network: bool = True) -> Company:
    """Live data when we can reach Yahoo, the snapshot when we cannot."""
    if allow_network:
        try:
            return fetch(ticker)
        except Exception as exc:
            try:
                c = load_snapshot(ticker)
                c.warnings.insert(
                    0,
                    f"Live fetch failed ({type(exc).__name__}); showing the "
                    f"snapshot saved {c.fetched_at[:10]}."
                )
                return c
            except FileNotFoundError:
                raise exc
    return load_snapshot(ticker)
