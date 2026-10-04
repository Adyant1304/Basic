"""Valuation engine: a pure, deterministic FCFF model.

Nothing here touches the network, a model, or global state. Same inputs,
same output, every time — which is the whole argument against asking a
chatbot for a projection.

The model
---------
    Revenue_t   = Revenue_(t-1) x (1 + g_t)
    g_t         tapers linearly from g_near (years 1-3) to g_term by year N
    Margin_t    tapers linearly from the starting margin to the target
    EBIT_t      = Revenue_t x Margin_t
    NOPAT_t     = EBIT_t x (1 - tax)
    Reinvest_t  = (Revenue_t - Revenue_(t-1)) / sales_to_capital
    FCFF_t      = NOPAT_t - Reinvest_t

    TV          = FCFF_(N+1) / (WACC - g_term)
    FCFF_(N+1)  = NOPAT_N x (1 + g_term) x (1 - g_term / ROIC_term)

    EV          = sum FCFF_t / (1+WACC)^t  +  TV / (1+WACC)^N
    Equity      = EV - debt + cash
    Per share   = Equity / shares

The terminal reinvestment rate is tied to a terminal ROIC rather than left
free, so perpetual growth has to be paid for. That is the single most common
place a student DCF inflates itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

from .data import Company

MIN_WACC_SPREAD = 0.005   # WACC must exceed terminal growth by this much


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Assumptions:
    """Every number a user can move. Frozen so results are cacheable."""

    growth_near: float          # revenue CAGR, years 1-3
    margin_target: float        # EBIT margin reached by the final year
    wacc: float
    growth_terminal: float
    tax_rate: float
    sales_to_capital: float
    roic_terminal: float
    years: int = 10
    margin_start: float = 0.20  # current margin, the taper's starting point

    def with_(self, **kw) -> "Assumptions":
        return replace(self, **kw)

    def key(self) -> tuple:
        return (round(self.growth_near, 6), round(self.margin_target, 6),
                round(self.wacc, 6), round(self.growth_terminal, 6),
                round(self.tax_rate, 6), round(self.sales_to_capital, 6),
                round(self.roic_terminal, 6), self.years,
                round(self.margin_start, 6))


@dataclass
class WaccBuild:
    """The CAPM build-up, kept visible so the number can be defended."""

    risk_free: float
    equity_risk_premium: float
    beta: float
    cost_of_equity: float
    cost_of_debt: float
    tax_rate: float
    weight_equity: float
    weight_debt: float
    wacc: float
    notes: list[str] = field(default_factory=list)


@dataclass
class Projection:
    """One run of the model."""

    years: list[int]
    revenue: list[float]
    growth: list[float]
    margin: list[float]
    ebit: list[float]
    nopat: list[float]
    reinvestment: list[float]
    fcff: list[float]
    discount_factors: list[float]
    pv_fcff: list[float]

    pv_explicit: float
    terminal_value: float
    pv_terminal: float
    enterprise_value: float
    net_debt: float
    equity_value: float
    value_per_share: float

    price: float
    upside: float               # value_per_share / price - 1
    terminal_share: float       # PV of TV as a share of EV
    implied_exit_multiple: float


# --------------------------------------------------------------------------
# WACC
# --------------------------------------------------------------------------

def build_wacc(c: Company, risk_free: float = 0.0655,
               erp: float = 0.070, beta_override: float | None = None,
               tax_rate: float | None = None) -> WaccBuild:
    """CAPM cost of equity, blended with after-tax cost of debt.

    Defaults are India-specific: a ~6.5% 10-year G-sec yield and a ~7.0%
    equity risk premium. Both are inputs in the UI because both move.
    """
    notes: list[str] = []
    beta = beta_override if beta_override is not None else c.beta
    if beta is None:
        beta = 1.0
        notes.append("Beta not reported by Yahoo; assumed 1.0.")
    beta = float(min(max(beta, 0.3), 2.5))

    t = tax_rate if tax_rate is not None else c.effective_tax_rate()
    coe = risk_free + beta * erp
    cod = c.cost_of_debt(risk_free)

    e = c.market_cap
    d = c.total_debt or 0.0
    total = e + d
    we, wd = (1.0, 0.0) if total <= 0 else (e / total, d / total)
    if wd < 0.02:
        notes.append("Effectively debt-free, so WACC is the cost of equity.")

    wacc = we * coe + wd * cod * (1 - t)
    return WaccBuild(risk_free, erp, beta, coe, cod, t, we, wd, wacc, notes)


# --------------------------------------------------------------------------
# Baseline: what the sliders start at
# --------------------------------------------------------------------------

def baseline_assumptions(c: Company, wacc: float,
                         risk_free: float = 0.0655,
                         years: int = 10) -> tuple[Assumptions, dict[str, str]]:
    """Seed every assumption from history, and say where each came from."""
    prov: dict[str, str] = {}

    hist = c.hist_revenue_growth()
    analyst = c.analyst_growth
    if hist is not None and -0.10 < hist < 0.60:
        g = hist
        prov["growth_near"] = (
            f"{len(c.revenue.values)}-year historical revenue CAGR "
            f"({hist:.1%})"
        )
        if analyst and 0 < analyst < 0.60:
            g = 0.5 * hist + 0.5 * analyst
            prov["growth_near"] = (
                f"average of the historical CAGR ({hist:.1%}) and Yahoo's "
                f"reported revenue growth ({analyst:.1%})"
            )
    elif analyst and 0 < analyst < 0.60:
        g = analyst
        prov["growth_near"] = f"Yahoo's reported revenue growth ({analyst:.1%})"
    else:
        g = 0.08
        prov["growth_near"] = "no usable history; defaulted to 8%"

    m_now = c.latest_margin()
    m_med = c.median_margin()
    if m_now is not None and m_med is not None:
        margin_start = m_now
        margin_target = 0.5 * m_now + 0.5 * m_med
        prov["margin_target"] = (
            f"midpoint of the latest margin ({m_now:.1%}) and the "
            f"{len(c.hist_margins())}-year median ({m_med:.1%})"
        )
    elif m_now is not None:
        margin_start = margin_target = m_now
        prov["margin_target"] = f"held at the latest margin ({m_now:.1%})"
    else:
        margin_start = margin_target = 0.15
        prov["margin_target"] = "no margin history; defaulted to 15%"

    tax = c.effective_tax_rate()
    prov.setdefault("tax_rate", "median of tax provision over pretax income")

    s2c = c.sales_to_capital()
    prov.setdefault(
        "sales_to_capital",
        "median revenue added per rupee reinvested (capex less D&A plus "
        "working capital)"
    )

    # Terminal growth cannot exceed the risk-free rate: a company growing
    # faster than the economy forever eventually becomes the economy.
    g_term = min(0.05, risk_free - 0.005, max(wacc - 0.03, 0.02))
    prov["growth_terminal"] = (
        f"capped below the risk-free rate ({risk_free:.2%}), the standard "
        "ceiling on perpetual growth"
    )

    current_roic = c.roic()
    if current_roic and current_roic > wacc:
        roic_term = min(current_roic, wacc + 0.08)
        prov["roic_terminal"] = (
            f"current ROIC is {current_roic:.1%}; faded toward WACC to "
            f"{roic_term:.1%} to reflect competition"
        )
    else:
        roic_term = wacc + 0.02
        prov["roic_terminal"] = "set at WACC + 2%, a mild residual advantage"

    a = Assumptions(
        growth_near=float(g),
        margin_target=float(margin_target),
        wacc=float(wacc),
        growth_terminal=float(g_term),
        tax_rate=float(tax),
        sales_to_capital=float(s2c),
        roic_terminal=float(roic_term),
        years=years,
        margin_start=float(margin_start),
    )
    return a, prov


# --------------------------------------------------------------------------
# The DCF
# --------------------------------------------------------------------------

def _growth_path(a: Assumptions) -> list[float]:
    """Flat for three years, then a straight line down to terminal growth."""
    n = a.years
    hold = min(3, n)
    path = [a.growth_near] * hold
    remaining = n - hold
    for i in range(1, remaining + 1):
        w = i / (remaining + 1)
        path.append(a.growth_near + (a.growth_terminal - a.growth_near) * w)
    return path[:n]


def _margin_path(a: Assumptions) -> list[float]:
    n = a.years
    return [a.margin_start + (a.margin_target - a.margin_start) * ((i + 1) / n)
            for i in range(n)]


def project(c: Company, a: Assumptions) -> Projection:
    """Run the model. Pure arithmetic — no network, no model, no state."""
    rev0 = c.revenue.latest
    if not rev0 or rev0 <= 0:
        raise ValueError("Cannot project without a positive base revenue.")

    wacc = max(a.wacc, a.growth_terminal + MIN_WACC_SPREAD)

    g_path, m_path = _growth_path(a), _margin_path(a)
    years = list(range(1, a.years + 1))

    revenue, growth, margin = [], [], []
    ebit, nopat, reinvest, fcff = [], [], [], []
    prev = rev0
    for i in range(a.years):
        r = prev * (1 + g_path[i])
        m = m_path[i]
        e = r * m
        np_ = e * (1 - a.tax_rate)
        ri = (r - prev) / a.sales_to_capital if a.sales_to_capital > 0 else 0.0
        revenue.append(r)
        growth.append(g_path[i])
        margin.append(m)
        ebit.append(e)
        nopat.append(np_)
        reinvest.append(ri)
        fcff.append(np_ - ri)
        prev = r

    dfs = [1 / (1 + wacc) ** t for t in years]
    pv = [f * d for f, d in zip(fcff, dfs)]
    pv_explicit = float(sum(pv))

    # Terminal value. Growth must be funded: reinvestment rate = g / ROIC.
    roic_t = max(a.roic_terminal, wacc + 0.001)
    reinvest_rate = min(max(a.growth_terminal / roic_t, 0.0), 0.95)
    nopat_next = nopat[-1] * (1 + a.growth_terminal)
    fcff_next = nopat_next * (1 - reinvest_rate)
    tv = fcff_next / (wacc - a.growth_terminal)
    pv_tv = tv * dfs[-1]

    ev = pv_explicit + pv_tv
    net_debt = (c.total_debt or 0.0) - (c.cash or 0.0)
    equity = ev - net_debt
    per_share = equity / c.shares_out if c.shares_out else float("nan")

    return Projection(
        years=years, revenue=revenue, growth=growth, margin=margin,
        ebit=ebit, nopat=nopat, reinvestment=reinvest, fcff=fcff,
        discount_factors=dfs, pv_fcff=pv,
        pv_explicit=pv_explicit, terminal_value=tv, pv_terminal=pv_tv,
        enterprise_value=ev, net_debt=net_debt, equity_value=equity,
        value_per_share=per_share, price=c.price,
        upside=(per_share / c.price - 1) if c.price else float("nan"),
        terminal_share=(pv_tv / ev) if ev else float("nan"),
        implied_exit_multiple=(tv / ebit[-1]) if ebit[-1] else float("nan"),
    )


# --------------------------------------------------------------------------
# Reverse DCF: what is the market already assuming?
# --------------------------------------------------------------------------

def reverse_dcf(c: Company, a: Assumptions, solve_for: str = "growth_near",
                lo: float | None = None, hi: float | None = None,
                tol: float = 1e-5, max_iter: int = 80) -> float | None:
    """Solve for the assumption that makes the model print today's price.

    This is the insight the tool exists for: not "is it cheap", but
    "what would have to be true for today's price to be right".
    """
    bounds = {
        "growth_near": (-0.25, 0.60),
        "margin_target": (0.01, 0.70),
        "wacc": (a.growth_terminal + 0.01, 0.35),
    }
    lo = bounds.get(solve_for, (-0.25, 0.60))[0] if lo is None else lo
    hi = bounds.get(solve_for, (-0.25, 0.60))[1] if hi is None else hi

    def gap(x: float) -> float:
        try:
            return project(c, a.with_(**{solve_for: x})).value_per_share - c.price
        except Exception:
            return float("nan")

    f_lo, f_hi = gap(lo), gap(hi)
    if math.isnan(f_lo) or math.isnan(f_hi) or f_lo * f_hi > 0:
        return None  # price lies outside what this assumption can reach

    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f_mid = gap(mid)
        if math.isnan(f_mid):
            return None
        if abs(f_mid) < tol * max(c.price, 1.0):
            return mid
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


# --------------------------------------------------------------------------
# Sensitivity, tornado, Monte Carlo
# --------------------------------------------------------------------------

def sensitivity_grid(c: Company, a: Assumptions,
                     wacc_range: tuple[float, float] = (-0.02, 0.02),
                     tg_range: tuple[float, float] = (-0.015, 0.015),
                     steps: int = 7) -> dict:
    """Value per share across WACC x terminal growth."""
    waccs = np.linspace(a.wacc + wacc_range[0], a.wacc + wacc_range[1], steps)
    tgs = np.linspace(a.growth_terminal + tg_range[0],
                      a.growth_terminal + tg_range[1], steps)
    z = []
    for tg in tgs:
        row = []
        for w in waccs:
            if w <= tg + MIN_WACC_SPREAD:
                row.append(float("nan"))
                continue
            try:
                row.append(project(c, a.with_(wacc=float(w),
                                              growth_terminal=float(tg)))
                           .value_per_share)
            except Exception:
                row.append(float("nan"))
        z.append(row)
    return {"wacc": [float(w) for w in waccs],
            "terminal_growth": [float(t) for t in tgs],
            "value": z}


TORNADO_VARS = [
    ("growth_near", "Revenue growth, years 1-3", 0.02),
    ("margin_target", "Target EBIT margin", 0.02),
    ("wacc", "WACC", 0.01),
    ("growth_terminal", "Terminal growth", 0.005),
    ("sales_to_capital", "Sales to capital", 0.5),
    ("tax_rate", "Tax rate", 0.03),
]


def tornado(c: Company, a: Assumptions) -> list[dict]:
    """Which assumption moves the answer most? Ranked, widest first."""
    base = project(c, a).value_per_share
    out = []
    for field_, label, delta in TORNADO_VARS:
        lo_a = a.with_(**{field_: getattr(a, field_) - delta})
        hi_a = a.with_(**{field_: getattr(a, field_) + delta})
        try:
            lo_v = project(c, lo_a).value_per_share
            hi_v = project(c, hi_a).value_per_share
        except Exception:
            continue
        if math.isnan(lo_v) or math.isnan(hi_v):
            continue
        out.append({
            "field": field_, "label": label, "delta": delta,
            "low": lo_v, "high": hi_v, "base": base,
            "swing": abs(hi_v - lo_v),
            "pct_swing": abs(hi_v - lo_v) / base if base else float("nan"),
        })
    return sorted(out, key=lambda d: d["swing"], reverse=True)


def monte_carlo(c: Company, a: Assumptions, n: int = 6000,
                growth_sd: float = 0.02, margin_sd: float = 0.015,
                wacc_sd: float = 0.01, seed: int = 7) -> dict:
    """Vectorised simulation of the value distribution.

    Growth, margin and WACC are drawn from independent normals around the
    current assumptions. Independence is a simplification worth stating out
    loud: in practice a growth shock and a margin shock arrive together, so
    the real distribution has fatter tails than this one.
    """
    rng = np.random.default_rng(seed)
    g = rng.normal(a.growth_near, growth_sd, n)
    m = rng.normal(a.margin_target, margin_sd, n)
    w = rng.normal(a.wacc, wacc_sd, n)

    g = np.clip(g, -0.20, 0.50)
    m = np.clip(m, 0.01, 0.65)
    w = np.clip(w, a.growth_terminal + MIN_WACC_SPREAD * 2, 0.30)

    rev0 = c.revenue.latest
    n_years = a.years
    hold = min(3, n_years)
    rem = n_years - hold

    # Growth path per draw: (n, years)
    paths = np.empty((n, n_years))
    paths[:, :hold] = g[:, None]
    for i in range(1, rem + 1):
        wt = i / (rem + 1)
        paths[:, hold + i - 1] = g + (a.growth_terminal - g) * wt

    revenue = rev0 * np.cumprod(1 + paths, axis=1)
    prev = np.concatenate([np.full((n, 1), rev0), revenue[:, :-1]], axis=1)

    steps = np.arange(1, n_years + 1) / n_years
    margins = a.margin_start + (m[:, None] - a.margin_start) * steps[None, :]

    nopat = revenue * margins * (1 - a.tax_rate)
    reinvest = (revenue - prev) / a.sales_to_capital
    fcff = nopat - reinvest

    dfs = 1.0 / np.power(1 + w[:, None], np.arange(1, n_years + 1)[None, :])
    pv_explicit = np.sum(fcff * dfs, axis=1)

    roic_t = np.maximum(a.roic_terminal, w + 0.001)
    rr = np.clip(a.growth_terminal / roic_t, 0, 0.95)
    fcff_next = nopat[:, -1] * (1 + a.growth_terminal) * (1 - rr)
    tv = fcff_next / (w - a.growth_terminal)
    pv_tv = tv * dfs[:, -1]

    ev = pv_explicit + pv_tv
    equity = ev - ((c.total_debt or 0) - (c.cash or 0))
    per_share = equity / c.shares_out

    per_share = per_share[np.isfinite(per_share)]
    pcts = [5, 25, 50, 75, 95]
    return {
        "values": per_share,
        "percentiles": {p: float(np.percentile(per_share, p)) for p in pcts},
        "mean": float(np.mean(per_share)),
        "prob_above_price": float(np.mean(per_share > c.price)),
        "n": int(per_share.size),
    }


def fan_chart(c: Company, a: Assumptions, n: int = 1200,
              growth_sd: float = 0.02, seed: int = 11) -> dict:
    """Revenue percentile bands, for showing the cone of outcomes."""
    rng = np.random.default_rng(seed)
    g = np.clip(rng.normal(a.growth_near, growth_sd, n), -0.20, 0.50)
    n_years = a.years
    hold = min(3, n_years)
    rem = n_years - hold
    paths = np.empty((n, n_years))
    paths[:, :hold] = g[:, None]
    for i in range(1, rem + 1):
        wt = i / (rem + 1)
        paths[:, hold + i - 1] = g + (a.growth_terminal - g) * wt
    revenue = c.revenue.latest * np.cumprod(1 + paths, axis=1)
    return {
        "years": list(range(1, n_years + 1)),
        "p5": np.percentile(revenue, 5, axis=0).tolist(),
        "p25": np.percentile(revenue, 25, axis=0).tolist(),
        "p50": np.percentile(revenue, 50, axis=0).tolist(),
        "p75": np.percentile(revenue, 75, axis=0).tolist(),
        "p95": np.percentile(revenue, 95, axis=0).tolist(),
    }
