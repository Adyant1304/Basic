"""Data layer: pull everything the model needs from Yahoo Finance.

Design rules
------------
1. One network trip per ticker. Everything downstream is arithmetic.
2. Never trust a single label spelling. Yahoo renames line items between
   companies and filings, so every lookup tries a list of aliases.
3. Always degrade instead of crashing. A missing line item becomes None and
   the engine falls back to a documented default, with the fallback recorded
   in `Company.provenance` so the UI can show what was inferred.
4. Snapshots. `fetch()` writes a JSON snapshot; if the network is gone the
   app loads the snapshot instead. Demos do not depend on wifi.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"

# --------------------------------------------------------------------------
# Line-item aliases. Yahoo's labels drift; we try each in order.
# --------------------------------------------------------------------------
REVENUE = ["Total Revenue", "Operating Revenue", "Revenue"]
EBIT = ["EBIT", "Operating Income", "Operating Revenue"]
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

    # ---------------- derived history, used to seed the sliders -----------

    @property
    def fiscal_years(self) -> list[int]:
        return self.revenue.years

    def hist_revenue_growth(self) -> float | None:
        return self.revenue.cagr()

    def hist_margins(self) -> list[float]:
        """EBIT margin per year where both lines exist."""
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
        """Standard deviation of EBIT margin. Lower means more predictable."""
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
        self.provenance["tax_rate"] = "defaulted to 25% (statutory India)"
        return 0.25

    def sales_to_capital(self, lo: float = 0.8, hi: float = 8.0) -> float:
        """Revenue added per rupee reinvested.

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
        self.provenance["sales_to_capital"] = "defaulted to 3.5x (asset-light services)"
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
    # above. Populated by `_build`.
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
        kwargs = dict(d)
        for f_ in series_fields:
            v = kwargs.get(f_)
            kwargs[f_] = Series(**v) if isinstance(v, dict) else None
        return cls(**kwargs)


# --------------------------------------------------------------------------
# Yahoo extraction
# --------------------------------------------------------------------------

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
                try:
                    if val is None or (isinstance(val, float) and math.isnan(val)):
                        continue
                    years.append(int(getattr(col, "year", 0)) or 0)
                    values.append(float(val))
                except (TypeError, ValueError):
                    continue
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


def fetch(ticker: str, write_snapshot: bool = True) -> Company:
    """Pull a company from Yahoo Finance. Raises on network failure."""
    import yfinance as yf

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
            price = float(hist["Close"].dropna().iloc[-1])
    if price is None:
        raise ValueError(f"{ticker}: could not resolve a market price.")

    shares = _first_num(info, ["sharesOutstanding", "impliedSharesOutstanding"])
    mcap = _first_num(info, ["marketCap"])
    if not shares and mcap:
        shares = mcap / price
    if not shares:
        raise ValueError(f"{ticker}: could not resolve shares outstanding.")

    debt = _pick_row(bal, TOTAL_DEBT)
    total_debt = debt.latest if debt else _sum_rows(bal, [LT_DEBT, ST_DEBT])

    cash_s = _pick_row(bal, CASH)
    equity_s = _pick_row(bal, EQUITY)
    ic_s = _pick_row(bal, INVESTED_CAPITAL)
    int_s = _pick_row(inc, INTEREST_EXP)

    warnings: list[str] = []
    prov: dict[str, str] = {}

    ebit = _pick_row(inc, EBIT)
    if ebit is None:
        warnings.append("No EBIT or operating income line; margins unavailable.")
    fcf = _pick_row(cfs, FCF)
    if fcf is None:
        # Derive it: operating cash flow less capex.
        ocf_s = _pick_row(cfs, OCF)
        cx_s = _pick_row(cfs, CAPEX)
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

    empty = Series("missing")
    c = Company(
        ticker=ticker.upper(),
        name=info.get("longName") or info.get("shortName") or ticker.upper(),
        sector=info.get("sector") or "Unclassified",
        industry=info.get("industry") or "",
        currency=info.get("currency") or "INR",
        price=float(price),
        shares_out=float(shares),
        market_cap=float(mcap or price * shares),
        revenue=revenue,
        ebit=ebit or empty,
        net_income=_pick_row(inc, NET_INCOME) or empty,
        da=_pick_row(cfs, DA) or empty,
        capex=_pick_row(cfs, CAPEX) or empty,
        chg_wc=_pick_row(cfs, CHG_WC) or empty,
        ocf=_pick_row(cfs, OCF) or empty,
        fcf=fcf or empty,
        total_debt=float(total_debt or 0.0),
        cash=float(cash_s.latest if cash_s and cash_s.latest else 0.0),
        equity_book=float(equity_s.latest if equity_s and equity_s.latest else 0.0),
        invested_capital=float(ic_s.latest) if ic_s and ic_s.latest else None,
        interest_expense=float(int_s.latest) if int_s and int_s.latest else None,
        beta=_first_num(info, ["beta", "beta3Year"]),
        trailing_pe=_first_num(info, ["trailingPE"]),
        forward_pe=_first_num(info, ["forwardPE"]),
        analyst_growth=_first_num(info, ["revenueGrowth"]),
        target_mean=_first_num(info, ["targetMeanPrice"]),
        n_analysts=int(info["numberOfAnalystOpinions"])
        if info.get("numberOfAnalystOpinions") else None,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source="yahoo",
        provenance=prov,
        warnings=warnings,
    )
    c._pretax = _pick_row(inc, PRETAX)
    c._tax = _pick_row(inc, TAX)

    if len(revenue.values) < 3:
        c.warnings.append(
            f"Only {len(revenue.values)} years of revenue history; growth and "
            "margin baselines are weakly supported."
        )
    if not c.beta:
        c.provenance["beta"] = "not reported; defaulted to 1.0 in the WACC build"

    if write_snapshot:
        try:
            save_snapshot(c)
        except OSError:
            pass
    return c


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _first_num(d: dict, keys: list[str]) -> float | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if not math.isnan(float(v)) and float(v) != 0:
                return float(v)
    return None


# --------------------------------------------------------------------------
# Snapshots: the offline path
# --------------------------------------------------------------------------

def save_snapshot(c: Company) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    p = SNAPSHOT_DIR / f"{c.ticker}.json"
    p.write_text(c.to_json())
    return p


def load_snapshot(ticker: str) -> Company:
    p = SNAPSHOT_DIR / f"{ticker.upper()}.json"
    if not p.exists():
        raise FileNotFoundError(f"No snapshot for {ticker} at {p}")
    d = json.loads(p.read_text())
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
