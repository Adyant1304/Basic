"""Diagnostics: ratios, each with a reading, not just a number.

Every metric carries four things: the value, which direction is better, a
reference band, and a sentence saying what this particular value means for
this particular company. A number without a reading is a number the user
has to go and interpret somewhere else.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .data import Company
from .engine import Assumptions, Projection, WaccBuild


@dataclass
class Metric:
    label: str
    value: float | None
    fmt: str                     # "pct" | "x" | "num" | "cur"
    direction: str               # "higher" | "lower" | "stable"
    band: str                    # the reference range, in words
    reading: str                 # what this value means here
    status: str = "neutral"      # "good" | "watch" | "poor" | "neutral"

    def display(self, currency: str = "INR") -> str:
        if self.value is None or (isinstance(self.value, float)
                                  and not math.isfinite(self.value)):
            return "n/a"
        if self.fmt == "pct":
            return f"{self.value:.1%}"
        if self.fmt == "x":
            return f"{self.value:.1f}x"
        if self.fmt == "cur":
            return f"{_sym(currency)}{self.value:,.0f}"
        return f"{self.value:,.1f}"


def _sym(currency: str) -> str:
    return {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}.get(
        currency, currency + " ")


# --------------------------------------------------------------------------

def quality_metrics(c: Company, a: Assumptions, p: Projection,
                    w: WaccBuild) -> list[Metric]:
    """The business-quality panel: does this company earn its cost of capital?"""
    out: list[Metric] = []

    # ---- ROIC vs WACC: the single most important quality test ----------
    roic = c.roic()
    if roic is not None:
        spread = roic - w.wacc
        if spread > 0.10:
            st, read = "good", (
                f"ROIC beats WACC by {spread*100:.1f} percentage points. Every "
                "rupee reinvested creates value, which is what justifies "
                "paying for growth at all."
            )
        elif spread > 0.02:
            st, read = "good", (
                f"ROIC clears WACC by {spread*100:.1f} points — a real but "
                "modest spread. Growth adds value, though not dramatically."
            )
        elif spread > -0.02:
            st, read = "watch", (
                "ROIC and WACC are roughly equal, so growth is value-neutral: "
                "the company is running to stand still."
            )
        else:
            st, read = "poor", (
                f"ROIC is {abs(spread)*100:.1f} points below WACC. Growth "
                "destroys value here, and a higher growth assumption should "
                "lower the valuation, not raise it."
            )
        out.append(Metric("ROIC", roic, "pct", "higher",
                          "must exceed WACC; asset-light services often 25%+",
                          read, st))

    # ---- EBIT margin and its stability ---------------------------------
    m = c.latest_margin()
    if m is not None:
        med = c.median_margin()
        read = f"Latest EBIT margin of {m:.1%}"
        if med is not None:
            gap = m - med
            if abs(gap) < 0.01:
                read += f", sitting right on its {len(c.hist_margins())}-year median."
            elif gap > 0:
                read += (f", {gap*100:.1f} points above the median — the model "
                         "fades it back toward normal rather than extrapolating "
                         "a peak.")
            else:
                read += (f", {abs(gap)*100:.1f} points below the median, so "
                         "there is recovery room if the pressure is cyclical.")
        out.append(Metric("EBIT margin", m, "pct", "higher",
                          "varies by industry; stability matters as much as level",
                          read, "neutral"))

    sd = c.margin_stability()
    if sd is not None:
        if sd < 0.015:
            st, read = "good", (
                f"Margin has moved in a band of about {sd*100:.1f} points. That "
                "predictability is what makes a DCF defensible here."
            )
        elif sd < 0.035:
            st, read = "watch", (
                f"Margin swings around {sd*100:.1f} points year to year. Treat a "
                "single-year margin as noise and use the median."
            )
        else:
            st, read = "poor", (
                f"Margin volatility of {sd*100:.1f} points is high. A point "
                "estimate is close to meaningless; read the Monte Carlo range "
                "instead of the headline value."
            )
        out.append(Metric("Margin volatility", sd, "pct", "lower",
                          "under 1.5 points is stable; over 3.5 is erratic",
                          read, st))

    # ---- Cash conversion -----------------------------------------------
    conv = c.fcf_conversion()
    if conv is not None:
        if conv > 0.9:
            st, read = "good", (
                f"{conv:.0%} of accounting profit arrives as free cash. Reported "
                "earnings are backed by cash, not working-capital timing."
            )
        elif conv > 0.6:
            st, read = "watch", (
                f"Only {conv:.0%} of profit converts to cash. Worth checking "
                "receivables and capex before trusting the earnings line."
            )
        else:
            st, read = "poor", (
                f"Cash conversion of {conv:.0%} is weak. Either the company is "
                "investing heavily or profit is not real cash yet."
            )
        out.append(Metric("FCF conversion", conv, "pct", "higher",
                          "90-100%+ is healthy; under 60% needs explaining",
                          read, st))

    # ---- Balance sheet --------------------------------------------------
    ncps = c.net_cash_per_share()
    if ncps is not None and c.price:
        share = ncps / c.price
        if ncps > 0:
            read = (f"Net cash of {_sym(c.currency)}{ncps:,.0f} per share is "
                    f"{share:.1%} of the share price, so that much of what you "
                    "pay is cash rather than future earnings.")
            st = "good"
        else:
            read = (f"Net debt of {_sym(c.currency)}{abs(ncps):,.0f} per share. "
                    "Leverage raises equity risk, which is why the debt weight "
                    "feeds the WACC build.")
            st = "watch" if abs(share) < 0.3 else "poor"
        out.append(Metric("Net cash per share", ncps, "cur", "higher",
                          "positive is a cushion; negative adds equity risk",
                          read, st))

    return out


def valuation_metrics(c: Company, a: Assumptions, p: Projection,
                      w: WaccBuild) -> list[Metric]:
    """The valuation panel: is this output believable?"""
    out: list[Metric] = []

    # ---- Implied P/E at fair value --------------------------------------
    ni = c.net_income.latest
    if ni and ni > 0 and c.shares_out:
        eps = ni / c.shares_out
        implied = p.value_per_share / eps
        read = f"At fair value the stock would trade on {implied:.1f}x trailing earnings"
        st = "neutral"
        if c.trailing_pe:
            gap = implied / c.trailing_pe - 1
            read += (f", versus {c.trailing_pe:.1f}x today — a "
                     f"{'re-rating' if gap > 0 else 'de-rating'} of {abs(gap):.0%}. "
                     "If that re-rating looks implausible, the growth or margin "
                     "assumption is doing too much work.")
            st = "watch" if abs(gap) > 0.5 else "good"
        out.append(Metric("Implied P/E at fair value", implied, "x", "lower",
                          "compare to the stock's own multiple history",
                          read, st))

    # ---- Terminal value share: the honesty check ------------------------
    ts = p.terminal_share
    if math.isfinite(ts):
        if ts < 0.6:
            st, read = "good", (
                f"{ts:.0%} of the value sits in the terminal value, so most of "
                "the answer comes from cash flows you can actually see."
            )
        elif ts < 0.78:
            st, read = "watch", (
                f"{ts:.0%} of value is terminal — normal for a growing company, "
                "but it means the perpetual-growth and WACC assumptions carry "
                "most of the weight."
            )
        else:
            st, read = "poor", (
                f"{ts:.0%} of the value is terminal value. The explicit forecast "
                "is almost decorative; the answer is really a function of two "
                "assumptions. Lengthen the forecast or widen the ranges."
            )
        out.append(Metric("Terminal value share", ts, "pct", "lower",
                          "under 60% is comfortable; over 78% is fragile",
                          read, st))

    # ---- Implied exit multiple -----------------------------------------
    if math.isfinite(p.implied_exit_multiple):
        iem = p.implied_exit_multiple
        if iem > 30:
            st, read = "poor", (
                f"The terminal value implies an exit at {iem:.0f}x EBIT, which is "
                "a demanding multiple to assume in perpetuity. Lower terminal "
                "growth or raise WACC."
            )
        elif iem > 18:
            st, read = "watch", (
                f"Exit multiple of {iem:.0f}x EBIT is full but not absurd for a "
                "high-return business."
            )
        else:
            st, read = "good", (
                f"The terminal value implies {iem:.0f}x EBIT — a conservative "
                "exit, so the valuation is not leaning on multiple expansion."
            )
        out.append(Metric("Implied terminal EBIT multiple", iem, "x", "lower",
                          "under 18x is conservative; over 30x is aggressive",
                          read, st))

    # ---- WACC sanity ----------------------------------------------------
    if 0.08 <= w.wacc <= 0.16:
        st, read = "good", (
            f"WACC of {w.wacc:.2%} sits in the normal band for Indian large caps "
            f"(beta {w.beta:.2f} on a {w.risk_free:.2%} risk-free rate and a "
            f"{w.equity_risk_premium:.1%} equity risk premium)."
        )
    elif w.wacc < 0.08:
        st, read = "watch", (
            f"WACC of {w.wacc:.2%} is low for this market, which flatters the "
            "valuation. Check the beta and risk-free inputs."
        )
    else:
        st, read = "watch", (
            f"WACC of {w.wacc:.2%} is demanding and suppresses the value. "
            "Reasonable for a high-beta or small-cap name, aggressive otherwise."
        )
    out.append(Metric("WACC", w.wacc, "pct", "lower",
                      "roughly 10-12% for Indian large caps",
                      read, st))

    return out


# --------------------------------------------------------------------------
# Sanity flags: catch an assumption that history will not support
# --------------------------------------------------------------------------

@dataclass
class Flag:
    severity: str   # "error" | "warn" | "info"
    title: str
    detail: str


def sanity_flags(c: Company, a: Assumptions, p: Projection,
                 w: WaccBuild, risk_free: float) -> list[Flag]:
    """Check each assumption against the company's own record and basic theory."""
    flags: list[Flag] = []

    # Growth versus what the company has ever achieved.
    yoy = c.revenue.yoy()
    if yoy:
        best = max(yoy)
        if a.growth_near > best + 0.02:
            flags.append(Flag(
                "warn", "Growth above anything in the record",
                f"You are assuming {a.growth_near:.1%} a year, but the best year "
                f"in this company's available history was {best:.1%}. That needs "
                "a reason — a new product, an acquisition, a cycle turning — not "
                "just optimism."
            ))
        worst = min(yoy)
        if a.growth_near < worst - 0.02:
            flags.append(Flag(
                "info", "Growth below the worst year on record",
                f"At {a.growth_near:.1%} you are assuming conditions worse than "
                f"the weakest year in the data ({worst:.1%}), which is a "
                "defensible bear case but should be deliberate."
            ))

    # Margin versus the historical band.
    margins = c.hist_margins()
    if margins:
        hi, lo = max(margins), min(margins)
        if a.margin_target > hi + 0.015:
            flags.append(Flag(
                "warn", "Margin above the historical peak",
                f"A {a.margin_target:.1%} target exceeds the best margin on "
                f"record ({hi:.1%}). Margin expansion is the easiest assumption "
                "to make and the hardest to deliver."
            ))
        elif a.margin_target < lo - 0.015:
            flags.append(Flag(
                "info", "Margin below the historical trough",
                f"A {a.margin_target:.1%} target is below the worst year "
                f"({lo:.1%}) — a severe but legitimate downside case."
            ))

    # Terminal growth versus the risk-free rate.
    if a.growth_terminal > risk_free:
        flags.append(Flag(
            "error", "Terminal growth exceeds the risk-free rate",
            f"Perpetual growth of {a.growth_terminal:.2%} above the "
            f"{risk_free:.2%} risk-free rate implies the company eventually "
            "outgrows the economy. Cap terminal growth at or below the "
            "risk-free rate."
        ))

    # WACC-to-terminal-growth spread.
    spread = w.wacc - a.growth_terminal
    if spread < 0.02:
        flags.append(Flag(
            "error", "WACC and terminal growth are too close",
            f"A spread of {spread*100:.1f} points makes the terminal value "
            "explode: the denominator approaches zero, so the answer is an "
            "artefact of arithmetic rather than a valuation."
        ))

    # Terminal ROIC versus WACC.
    if a.roic_terminal < w.wacc:
        flags.append(Flag(
            "warn", "Terminal ROIC below WACC",
            f"Terminal ROIC of {a.roic_terminal:.1%} under a {w.wacc:.1%} WACC "
            "means perpetual growth destroys value, so a higher terminal "
            "growth rate should reduce the valuation."
        ))

    # Terminal value dominance.
    if math.isfinite(p.terminal_share) and p.terminal_share > 0.80:
        flags.append(Flag(
            "warn", "Terminal value dominates",
            f"{p.terminal_share:.0%} of the valuation comes from the period "
            "beyond the explicit forecast."
        ))

    # Data sufficiency.
    if len(c.revenue.values) < 3:
        flags.append(Flag(
            "warn", "Thin history",
            f"Yahoo returned only {len(c.revenue.values)} years of financials, "
            "so every baseline here rests on a very short record."
        ))

    return flags


def consensus_implied(c: Company, a: Assumptions) -> dict | None:
    """What growth would justify the analyst target price?

    Imported from Yahoo's `targetMeanPrice`. It is a crowd-sourced number of
    uneven quality, which is exactly why it belongs on the chart as a third
    mark rather than as the answer.
    """
    if not c.target_mean or not c.n_analysts:
        return None
    from .engine import project

    lo, hi = -0.25, 0.60

    def gap(x: float) -> float:
        return project(c, a.with_(growth_near=x)).value_per_share - c.target_mean

    f_lo, f_hi = gap(lo), gap(hi)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo * f_hi > 0:
        return {"target": c.target_mean, "n": c.n_analysts, "growth": None}
    for _ in range(60):
        mid = (lo + hi) / 2
        f_mid = gap(mid)
        if abs(f_mid) < 0.01:
            break
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return {"target": c.target_mean, "n": c.n_analysts,
            "growth": (lo + hi) / 2}
