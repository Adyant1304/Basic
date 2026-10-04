"""Plotly figures. One template, one colour language, no chart junk."""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from . import theme as T
from .data import Company
from .engine import Assumptions, Projection

_TPL = T.plotly_template()


def _fig(height: int = 340, title: str | None = None,
         top: int = 34) -> go.Figure:
    """A figure with enough head room that a title never meets a legend."""
    f = go.Figure()
    f.update_layout(template=_TPL, height=height,
                    margin={"l": 8, "r": 8, "t": top, "b": 8})
    if title:
        f.update_layout(title={
            "text": title, "x": 0, "xanchor": "left",
            "y": 0.98, "yref": "container", "yanchor": "top",
            "font": {"size": 13, "color": T.INK},
        })
    return f


def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# --------------------------------------------------------------------------

def revenue_fan(c: Company, fan: dict, p: Projection) -> go.Figure:
    """Revenue cone: the point forecast with the simulated spread around it."""
    f = _fig(360, top=40)
    div = 1e7 if c.currency == "INR" else 1e9
    unit = "crore" if c.currency == "INR" else "bn"
    yrs = fan["years"]

    for lo, hi, alpha, name in (("p5", "p95", 0.10, "5th-95th percentile"),
                                ("p25", "p75", 0.20, "25th-75th percentile")):
        f.add_trace(go.Scatter(
            x=yrs + yrs[::-1],
            y=[v / div for v in fan[hi]] + [v / div for v in fan[lo]][::-1],
            fill="toself", fillcolor=_rgba(T.YOURS, alpha),
            line={"width": 0}, hoverinfo="skip", name=name,
        ))
    f.add_trace(go.Scatter(
        x=yrs, y=[v / div for v in p.revenue], mode="lines+markers",
        line={"color": T.YOURS, "width": 2.5},
        marker={"size": 5, "color": T.YOURS}, name="Your case",
        hovertemplate="Year %{x}<br>%{y:,.0f} " + unit + "<extra></extra>",
    ))
    f.add_hline(y=c.revenue.latest / div, line={"color": T.MARKET,
                                                "width": 1, "dash": "dot"})
    f.add_annotation(x=yrs[0], y=c.revenue.latest / div, text="today",
                     showarrow=False, yshift=11, xshift=4,
                     font={"size": 11, "color": T.MARKET})
    f.update_xaxes(title="Forecast year", dtick=1)
    f.update_yaxes(title=f"Revenue ({unit})")
    return f


def cash_flow_bars(c: Company, p: Projection) -> go.Figure:
    """Where the cash goes: NOPAT split into reinvestment and free cash flow."""
    f = _fig(360, "Operating profit after tax, split between<br>reinvestment and free cash flow", top=92)
    div = 1e7 if c.currency == "INR" else 1e9
    unit = "crore" if c.currency == "INR" else "bn"
    f.add_trace(go.Bar(
        x=p.years, y=[v / div for v in p.fcff], name="Free cash flow to the firm",
        marker={"color": T.YOURS},
        hovertemplate="Year %{x}<br>%{y:,.0f} " + unit + "<extra></extra>",
    ))
    f.add_trace(go.Bar(
        x=p.years, y=[v / div for v in p.reinvestment], name="Reinvestment",
        marker={"color": _rgba(T.CONSENSUS, 0.75)},
        hovertemplate="Year %{x}<br>%{y:,.0f} " + unit + "<extra></extra>",
    ))
    f.update_layout(barmode="stack", bargap=0.28)
    f.update_xaxes(title="Forecast year", dtick=1)
    f.update_yaxes(title=f"({unit})")
    return f


def margin_path(c: Company, p: Projection) -> go.Figure:
    """The assumed margin path against every margin the company has printed."""
    f = _fig(360, "Assumed EBIT margin against<br>the historical record", top=92)
    hist = c.hist_margins()
    if hist:
        f.add_hrect(y0=min(hist) * 100, y1=max(hist) * 100,
                    fillcolor=_rgba(T.MARKET, 0.10), line={"width": 0},
                    annotation_text="historical range",
                    annotation_position="top left",
                    annotation_font={"size": 11, "color": T.INK_SOFT})
    f.add_trace(go.Scatter(
        x=p.years, y=[m * 100 for m in p.margin], mode="lines+markers",
        line={"color": T.YOURS, "width": 2.5}, marker={"size": 5},
        name="Assumed", hovertemplate="Year %{x}<br>%{y:.1f}%<extra></extra>",
    ))
    f.update_xaxes(title="Forecast year", dtick=1)
    f.update_yaxes(title="EBIT margin (%)", ticksuffix="%")
    f.update_layout(showlegend=False)
    return f


def sensitivity_heatmap(grid: dict, price: float, currency: str) -> go.Figure:
    """WACC against terminal growth, shaded by upside to today's price."""
    f = _fig(400, top=16)
    f.update_layout(margin={"l": 60, "r": 8, "t": 16, "b": 46})
    z = np.array(grid["value"], dtype=float)
    upside = (z / price - 1) * 100
    span = float(np.nanmax(np.abs(upside))) if np.isfinite(upside).any() else 1.0
    span = max(span, 5.0)

    f.add_trace(go.Heatmap(
        z=upside,
        x=[v * 100 for v in grid["wacc"]],
        y=[v * 100 for v in grid["terminal_growth"]],
        text=[[T.per_share(v, currency) if np.isfinite(v) else ""
               for v in row] for row in z],
        texttemplate="%{text}",
        textfont={"size": 11},
        colorscale=[[0.0, T.DOWN], [0.5, T.PAPER], [1.0, T.YOURS]],
        zmid=0, zmin=-span, zmax=span,
        colorbar={"title": {"text": "Upside<br>to price", "font": {"size": 11}},
                  "ticksuffix": "%", "thickness": 12, "len": 0.75,
                  "outlinewidth": 0, "tickfont": {"size": 10}},
        hovertemplate=("WACC %{x:.2f}%<br>Terminal growth %{y:.2f}%"
                       "<br>%{text} per share<extra></extra>"),
    ))
    f.update_xaxes(title="WACC (%)", ticksuffix="%", showgrid=False)
    f.update_yaxes(title="Terminal growth (%)", ticksuffix="%", showgrid=False)
    return f


def tornado_chart(rows: list[dict], price: float, currency: str) -> go.Figure:
    """Which assumption moves the answer most."""
    rows = rows[::-1]                      # widest at the top
    f = _fig(max(300, 46 * len(rows) + 90), top=40)
    base = rows[0]["base"] if rows else 0.0
    labels = [f"{r['label']}  ±{delta_label(r)}" for r in rows]

    f.add_trace(go.Bar(
        y=labels, x=[r["low"] - base for r in rows], base=base,
        orientation="h", name="Assumption lower",
        marker={"color": _rgba(T.DOWN, 0.75)},
        hovertemplate="%{y}<br>lower: %{base:,.0f}<extra></extra>",
    ))
    f.add_trace(go.Bar(
        y=labels, x=[r["high"] - base for r in rows], base=base,
        orientation="h", name="Assumption higher",
        marker={"color": _rgba(T.YOURS, 0.8)},
        hovertemplate="%{y}<br>higher: %{base:,.0f}<extra></extra>",
    ))
    f.add_vline(x=base, line={"color": T.INK, "width": 1.5})
    f.add_vline(x=price, line={"color": T.MARKET, "width": 1, "dash": "dash"})
    f.add_annotation(x=price, y=1.0, yref="paper", text="market price",
                     showarrow=False, yshift=8,
                     font={"size": 11, "color": T.MARKET})
    f.update_layout(barmode="overlay", bargap=0.42)
    f.update_xaxes(title=f"Value per share ({T.symbol(currency)})")
    f.update_yaxes(showgrid=False, ticks="")
    return f


def delta_label(r: dict) -> str:
    d = r["delta"]
    return f"{d:.1f}x" if r["field"] == "sales_to_capital" else f"{d * 100:.1f}pt"


def mc_distribution(mc: dict, price: float, currency: str,
                    point: float) -> go.Figure:
    """The distribution of outcomes, with the price marked on it."""
    f = _fig(360, top=46)
    vals = mc["values"]
    f.add_trace(go.Histogram(
        x=vals, nbinsx=64, marker={"color": _rgba(T.YOURS, 0.42),
                                   "line": {"width": 0}},
        hovertemplate="%{x:,.0f}<br>%{y} draws<extra></extra>",
        name="Simulated outcomes",
    ))
    for p_, dash, label in ((5, "dot", "5th"), (50, "solid", "median"),
                            (95, "dot", "95th")):
        v = mc["percentiles"][p_]
        f.add_vline(x=v, line={"color": T.YOURS, "width": 1.4, "dash": dash})
        f.add_annotation(x=v, y=1.0, yref="paper", text=label, showarrow=False,
                         yshift=9, font={"size": 10, "color": T.YOURS})
    f.add_vline(x=price, line={"color": T.MARKET, "width": 2})
    f.add_annotation(x=price, y=1.0, yref="paper",
                     text=f"market {T.per_share(price, currency)}",
                     showarrow=False, yshift=26,
                     font={"size": 11, "color": T.MARKET})
    f.update_xaxes(title=f"Value per share ({T.symbol(currency)})")
    f.update_yaxes(title="Simulated draws", showgrid=True)
    f.update_layout(showlegend=False, bargap=0.02)
    return f


def history_bars(c: Company) -> go.Figure:
    """The actual record: revenue bars with the EBIT margin over them."""
    f = _fig(340, "Reported revenue and EBIT margin", top=76)
    div = 1e7 if c.currency == "INR" else 1e9
    unit = "crore" if c.currency == "INR" else "bn"
    yrs = c.revenue.years[::-1]
    rev = [v / div for v in c.revenue.values[::-1]]
    f.add_trace(go.Bar(
        x=yrs, y=rev, name=f"Revenue ({unit})",
        marker={"color": _rgba(T.MARKET, 0.35)},
        hovertemplate="%{x}<br>%{y:,.0f} " + unit + "<extra></extra>",
    ))
    rev_by_year = dict(zip(c.revenue.years, c.revenue.values))
    mx, my = [], []
    for yr, e in zip(c.ebit.years, c.ebit.values):
        r = rev_by_year.get(yr)
        if r:
            mx.append(yr)
            my.append(e / r * 100)
    if mx:
        order = sorted(range(len(mx)), key=lambda i: mx[i])
        f.add_trace(go.Scatter(
            x=[mx[i] for i in order], y=[my[i] for i in order],
            mode="lines+markers", name="EBIT margin", yaxis="y2",
            line={"color": T.YOURS, "width": 2.5}, marker={"size": 6},
            hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>",
        ))
    f.update_layout(
        yaxis2={"overlaying": "y", "side": "right", "showgrid": False,
                "ticksuffix": "%", "tickfont": {"size": 11, "color": T.YOURS},
                "title": {"text": "EBIT margin", "font": {"size": 12,
                                                          "color": T.YOURS}}},
        bargap=0.45,
    )
    f.update_xaxes(title="Fiscal year", dtick=1)
    f.update_yaxes(title=f"Revenue ({unit})")
    return f
