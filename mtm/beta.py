"""Company-specific beta, estimated from the company's own price history.

Why this exists
---------------
Yahoo's `beta` field is not usable for Indian listings. On the day this was
written it reported 0.12 for Infosys, 0.18 for TCS and -0.06 for ITC, none of
which is a believable sensitivity to the market, and the original app hid the
problem by clamping every beta into 0.3-2.5 so that almost every Indian stock
ended up with the same discount rate.

The fix is the textbook one. Regress the stock's weekly returns on the weekly
returns of its local index:

    r_stock = alpha + beta x r_market + error

    beta = Cov(r_stock, r_market) / Var(r_market)

The regression also gives R-squared and a standard error, so the number can be
shown with its own uncertainty rather than as a bare point. Everything here is
pure arithmetic on two return series; fetching the prices is data.py's job.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

MIN_OBS = 52            # a year of weekly returns; below this we refuse
THIN_OBS = 104          # under two years: usable, but flagged
BLUME_WEIGHT = 2 / 3    # adjusted = 2/3 x raw + 1/3 x 1.0


@dataclass
class BetaEstimate:
    beta: float
    alpha: float        # weekly intercept
    r2: float
    se: float           # standard error of the slope
    n: int

    @property
    def adjusted(self) -> float:
        return blume(self.beta)

    @property
    def ci95(self) -> tuple[float, float]:
        return (self.beta - 1.96 * self.se, self.beta + 1.96 * self.se)


def blume(beta: float) -> float:
    """Shrink a raw beta toward 1.0, the long-run average for any stock.

    Raw betas are noisy and mean-revert, so a stock measured at 0.5 is on
    average closer to 0.7 in the following period. Bloomberg's default beta
    uses exactly this adjustment.
    """
    return BLUME_WEIGHT * beta + (1 - BLUME_WEIGHT) * 1.0


def regress(stock: np.ndarray, market: np.ndarray) -> BetaEstimate | None:
    """Ordinary least squares of stock returns on market returns."""
    s = np.asarray(stock, dtype=float)
    m = np.asarray(market, dtype=float)
    ok = np.isfinite(s) & np.isfinite(m)
    s, m = s[ok], m[ok]
    n = int(s.size)
    if n < MIN_OBS:
        return None
    var_m = float(np.var(m, ddof=1))
    if var_m <= 0:
        return None

    cov = float(np.cov(s, m, ddof=1)[0, 1])
    beta = cov / var_m
    alpha = float(np.mean(s) - beta * np.mean(m))

    resid = s - (alpha + beta * m)
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((s - np.mean(s)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    se = math.sqrt(ss_res / (n - 2) / float(np.sum((m - np.mean(m)) ** 2)))
    return BetaEstimate(beta=beta, alpha=alpha, r2=r2, se=se, n=n)


def simple_returns(prices) -> np.ndarray:
    p = np.asarray(prices, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return p[1:] / p[:-1] - 1.0


def estimate_from_prices(stock_prices, market_prices) -> BetaEstimate | None:
    """Beta from two price series that are already aligned on the same dates."""
    return regress(simple_returns(stock_prices), simple_returns(market_prices))


def bundle(est: BetaEstimate | None, benchmark: str, benchmark_name: str,
           frequency: str, years: int, yahoo_beta: float | None,
           as_of: str = "") -> dict:
    """Flatten an estimate into the JSON-safe dict stored on the Company."""
    out: dict = {
        "benchmark": benchmark, "benchmark_name": benchmark_name,
        "frequency": frequency, "years": years, "as_of": as_of,
        "yahoo": float(yahoo_beta) if yahoo_beta is not None else None,
        "raw": None, "adjusted": None, "r2": None, "se": None, "n": 0,
        "ci_low": None, "ci_high": None,
    }
    if est is not None:
        lo, hi = est.ci95
        out.update(raw=est.beta, adjusted=est.adjusted, r2=est.r2,
                   se=est.se, n=est.n, ci_low=lo, ci_high=hi)
    return out


def quality_note(b: dict) -> str | None:
    """A plain-English caution when the regression is weak, else None."""
    if not b or b.get("raw") is None:
        return None
    notes = []
    if b["n"] < THIN_OBS:
        notes.append(f"only {b['n']} weekly observations")
    if b["r2"] is not None and b["r2"] < 0.10:
        notes.append(f"the index explains just {b['r2']:.0%} of its moves")
    if b["se"] is not None and b["se"] > 0.25:
        notes.append(f"the standard error is wide ({b['se']:.2f})")
    if not notes:
        return None
    return ("Treat this beta with care: " + ", and ".join(notes) +
            ". The Blume-adjusted figure shrinks it toward 1.0.")


def options(b: dict) -> dict[str, float]:
    """The betas a user can choose from, keyed by method. Missing ones omitted."""
    out: dict[str, float] = {}
    if b:
        if b.get("raw") is not None:
            out["regression"] = float(b["raw"])
            out["adjusted"] = float(b["adjusted"])
        if b.get("yahoo") is not None:
            out["yahoo"] = float(b["yahoo"])
    return out
