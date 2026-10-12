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
    f.update_layout(template=_TPL, height=height, title=title,
                    margin={"l": 8, "r": 8, "t": top, "b": 8})
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
    """The actual record: revenue on top, the margins beneath it.

    Two panels sharing the year axis rather than one chart with two y-scales.
    A second axis lets the eye find a correlation the data does not contain,
    because where the two scales cross is arbitrary. The original build used
    a dual axis here.
    """
    from plotly.subplots import make_subplots

    div, unit = T.unit_for(c.currency)
    f = make_subplots(rows=2, cols=1, shared_xaxes=True,
                      row_heights=[0.58, 0.42], vertical_spacing=0.1)
    f.update_layout(template=_TPL, height=400,
                    margin={"l": 8, "r": 8, "t": 44, "b": 8},
                    title="Reported revenue, and the margins it earned",
                    bargap=0.45)

    yrs = c.revenue.years[::-1]
    f.add_trace(go.Bar(
        x=yrs, y=[v / div for v in c.revenue.values[::-1]],
        name=f"Revenue ({unit})", marker={"color": _rgba(T.MARKET, 0.4)},
        hovertemplate="%{x}<br>%{y:,.0f} " + unit + "<extra></extra>",
    ), row=1, col=1)

    def margin_series(series):
        by_year = dict(zip(c.revenue.years, c.revenue.values))
        pts = sorted((yr, v / by_year[yr] * 100)
                     for yr, v in zip(series.years, series.values)
                     if by_year.get(yr))
        return [p[0] for p in pts], [p[1] for p in pts]

    for series, name, colour in ((c.ebit, "Operating margin", T.YOURS),
                                 (c.net_income, "Net margin", T.CONSENSUS)):
        x, y = margin_series(series)
        if x:
            f.add_trace(go.Scatter(
                x=x, y=y, mode="lines+markers", name=name,
                line={"color": colour, "width": 2.25},
                marker={"size": 7, "color": colour,
                        "line": {"color": T.PAPER, "width": 2}},
                hovertemplate="%{x}<br>" + name + " %{y:.1f}%<extra></extra>",
            ), row=2, col=1)

    f.update_xaxes(dtick=1, row=2, col=1, title="Fiscal year")
    f.update_yaxes(title=f"Revenue ({unit})", row=1, col=1)
    f.update_yaxes(title="Margin (%)", ticksuffix="%", row=2, col=1)
    return f


# --------------------------------------------------------------------------
# Snapshot tab
# --------------------------------------------------------------------------

def price_chart(c: Company) -> go.Figure | None:
    """Five years of weekly closes. The market's own record, in market slate."""
    h = c.price_history or {}
    if not h.get("dates"):
        return None
    dates, close = list(h["dates"]), list(h["close"])
    # Weekly bars end on the last completed week, so the chart would finish
    # a few rupees away from the price in the header. Close the series on
    # the live price so the two agree.
    today = (c.fetched_at or "")[:10]
    if today > dates[-1] and c.price:
        dates.append(today)
        close.append(c.price)
    f = _fig(300, top=16)
    f.add_trace(go.Scatter(
        x=dates, y=close, mode="lines", name="Weekly close",
        line={"color": T.MARKET, "width": 1.8},
        hovertemplate="%{x|%d %b %Y}<br>" + T.symbol(c.currency)
        + "%{y:,.0f}<extra></extra>",
    ))
    f.add_trace(go.Scatter(
        x=[dates[-1]], y=[close[-1]], mode="markers",
        marker={"size": 9, "color": T.YOURS,
                "line": {"color": T.PAPER, "width": 2}},
        hoverinfo="skip", showlegend=False,
    ))
    f.add_annotation(x=dates[-1], y=close[-1],
                     text=T.per_share(close[-1], c.currency),
                     showarrow=False, xanchor="left", xshift=10,
                     font={"size": 12, "color": T.YOURS})
    f.update_layout(showlegend=False, hovermode="x unified",
                    margin={"l": 8, "r": 64, "t": 16, "b": 8})
    f.update_yaxes(title=f"Price ({T.symbol(c.currency).strip()})")
    return f


def beta_scatter(c: Company) -> go.Figure | None:
    """Weekly stock returns against weekly index returns, with the fitted line.

    The slope of the line is the beta. Drawing it, rather than quoting a
    number, shows where the figure comes from and how loose the fit is.
    """
    reg = (c.price_history or {}).get("reg")
    b = c.beta_info or {}
    if not reg or b.get("raw") is None:
        return None
    s = np.array(reg["stock"], dtype=float)
    m = np.array(reg["bench"], dtype=float)
    rs, rm = (s[1:] / s[:-1] - 1) * 100, (m[1:] / m[:-1] - 1) * 100
    f = _fig(340, top=16)
    f.add_trace(go.Scatter(
        x=rm, y=rs, mode="markers", name="Weekly returns",
        marker={"size": 6, "color": _rgba(T.MARKET, 0.5),
                "line": {"width": 0}},
        hovertemplate=f"{b['benchmark_name']} %{{x:.1f}}%<br>"
                      "Stock %{y:.1f}%<extra></extra>",
    ))
    lo, hi = float(rm.min()), float(rm.max())
    alpha = (rs.mean() - b["raw"] * rm.mean())
    f.add_trace(go.Scatter(
        x=[lo, hi], y=[alpha + b["raw"] * lo, alpha + b["raw"] * hi],
        mode="lines", name=f"Fitted line, slope {b['raw']:.2f}",
        line={"color": T.YOURS, "width": 2.5}, hoverinfo="skip",
    ))
    f.add_trace(go.Scatter(
        x=[lo, hi], y=[lo, hi], mode="lines", name="Slope 1.00 (moves with the index)",
        line={"color": T.INK_FAINT, "width": 1}, hoverinfo="skip",
    ))
    f.update_xaxes(title=f"{b['benchmark_name']} weekly return",
                   ticksuffix="%", zeroline=True, zerolinecolor=T.RULE)
    f.update_yaxes(title="Stock weekly return", ticksuffix="%",
                   zeroline=True, zerolinecolor=T.RULE)
    f.update_layout(margin={"l": 8, "r": 8, "t": 46, "b": 8})
    return f


# --------------------------------------------------------------------------
# Segments tab
# --------------------------------------------------------------------------

def segment_donut(groups: dict[str, float], colours: dict[str, str],
                  centre: str = "") -> go.Figure:
    """Part-to-whole at a glance. Six slices at most, tail folded upstream."""
    f = _fig(400, top=10)
    names = list(groups)
    f.add_trace(go.Pie(
        labels=names, values=[groups[n] for n in names], hole=0.6,
        sort=False, direction="clockwise", rotation=0,
        marker={"colors": [colours.get(n, T.OTHER_COLOUR) for n in names],
                "line": {"color": T.PAPER, "width": 2}},
        textinfo="percent", textposition="outside",
        textfont={"size": 12, "color": T.INK},
        domain={"x": [0.12, 0.88], "y": [0.2, 1.0]},
        hovertemplate="%{label}<br>%{percent}<extra></extra>",
    ))
    if centre:
        f.add_annotation(text=centre, showarrow=False, x=0.5, y=0.6,
                         font={"size": 14, "color": T.INK_SOFT})
    # The legend sits under the ring, not beside it: a side legend squeezed
    # the ring until its percentage labels collided.
    f.update_layout(
        showlegend=True,
        legend={"orientation": "h", "x": 0.5, "y": 0.0, "xanchor": "center",
                "yanchor": "top", "font": {"size": 11.5, "color": T.INK},
                "entrywidth": 0, "tracegroupgap": 4},
        margin={"l": 8, "r": 8, "t": 22, "b": 8},
    )
    return f


def segment_bars(names: list[str], values: list[float], labels: list[str]
                 ) -> go.Figure:
    """Every segment ranked, one colour: the length is the message."""
    order = sorted(range(len(names)), key=lambda i: values[i])
    f = _fig(max(260, 40 * len(names) + 50), top=10)
    f.add_trace(go.Bar(
        y=[names[i] for i in order], x=[values[i] for i in order],
        orientation="h", marker={"color": T.YOURS},
        text=[labels[i] for i in order], textposition="outside",
        textfont={"size": 11.5, "color": T.INK}, cliponaxis=False,
        hovertemplate="%{y}<br>%{text}<extra></extra>",
    ))
    f.update_layout(bargap=0.42, showlegend=False,
                    margin={"l": 8, "r": 110, "t": 10, "b": 8})
    f.update_xaxes(visible=False, showgrid=False)
    f.update_yaxes(showgrid=False, ticks="", automargin=True)
    return f


def segment_shift(rows: list[dict], old_label: str, new_label: str
                  ) -> go.Figure:
    """Share of revenue then and now, one row per segment.

    A dumbbell, because the question is "what moved". Rows arrive ordered by
    the size of the move, largest at the top.
    """
    rows = rows[::-1]
    names = [r["segment"] for r in rows]
    f = _fig(max(280, 42 * len(rows) + 90), top=34)
    xs, ys = [], []
    for r in rows:
        xs += [r["old"] * 100, r["new"] * 100, None]
        ys += [r["segment"], r["segment"], None]
    f.add_trace(go.Scatter(x=xs, y=ys, mode="lines", showlegend=False,
                           line={"color": T.RULE, "width": 3},
                           hoverinfo="skip"))
    f.add_trace(go.Scatter(
        x=[r["old"] * 100 for r in rows], y=names, mode="markers",
        name=old_label, marker={"size": 10, "color": T.MARKET,
                                "line": {"color": T.PAPER, "width": 2}},
        hovertemplate="%{y}<br>" + old_label + " %{x:.1f}%<extra></extra>"))
    f.add_trace(go.Scatter(
        x=[r["new"] * 100 for r in rows], y=names, mode="markers",
        name=new_label, marker={"size": 12, "color": T.YOURS,
                                "line": {"color": T.PAPER, "width": 2}},
        hovertemplate="%{y}<br>" + new_label + " %{x:.1f}%<extra></extra>"))
    top = max(max(r["old"], r["new"]) for r in rows) * 100
    for r in rows:
        f.add_annotation(
            x=top * 1.12, y=r["segment"], showarrow=False, xanchor="left",
            text=T.points(r["shift"]),
            font={"size": 11.5,
                  "color": T.YOURS if r["shift"] > 0.05 else
                  T.DOWN if r["shift"] < -0.05 else T.INK_FAINT})
    f.update_xaxes(title="Share of revenue (%)", ticksuffix="%", rangemode="tozero")
    f.update_yaxes(showgrid=True, ticks="", automargin=True)
    f.update_layout(margin={"l": 8, "r": 70, "t": 34, "b": 8})
    return f


# --------------------------------------------------------------------------
# Relative value tab
# --------------------------------------------------------------------------

def football_field(rows: list[dict], price: float, currency: str
                   ) -> go.Figure:
    """Every method's value range for one share, on a single price axis.

    DCF is the one case in teal, the analyst range in ochre and the peer
    multiples in neutral grey: emphasis rather than five competing hues. The
    market price is the vertical line they are all being compared with.
    """
    rows = rows[::-1]
    f = _fig(max(300, 52 * len(rows) + 90), top=40)
    tone = {"dcf": T.YOURS, "consensus": T.CONSENSUS, "market": T.MARKET,
            "relative": T.INK_FAINT}
    f.add_trace(go.Bar(
        y=[r["label"] for r in rows],
        x=[r["high"] - r["low"] for r in rows],
        base=[r["low"] for r in rows], orientation="h",
        marker={"color": [_rgba(tone[r["group"]], 0.85) for r in rows]},
        customdata=[[r["low"], r["high"]] for r in rows],
        hovertemplate="%{y}<br>" + T.symbol(currency) +
        "%{customdata[0]:,.0f} to " + T.symbol(currency) +
        "%{customdata[1]:,.0f}<extra></extra>",
        showlegend=False,
    ))
    mids = [(r["label"], r["mid"], r["group"]) for r in rows
            if r.get("mid") is not None]
    if mids:
        f.add_trace(go.Scatter(
            y=[m[0] for m in mids], x=[m[1] for m in mids], mode="markers",
            marker={"symbol": "diamond", "size": 10, "color": T.INK,
                    "line": {"color": T.PAPER, "width": 2}},
            hovertemplate="%{y}<br>mid " + T.symbol(currency) +
            "%{x:,.0f}<extra></extra>", showlegend=False))
    f.add_vline(x=price, line={"color": T.MARKET, "width": 2})
    f.add_annotation(x=price, y=1.0, yref="paper", showarrow=False, yshift=14,
                     text=f"market {T.per_share(price, currency)}",
                     font={"size": 11.5, "color": T.MARKET})
    f.update_layout(bargap=0.55)
    f.update_xaxes(title=f"Value per share ({T.symbol(currency).strip()})",
                   rangemode="tozero")
    f.update_yaxes(showgrid=False, ticks="", automargin=True)
    return f


def peer_bars(rows: list[dict], key: str, label: str, self_ticker: str,
              median: float | None) -> go.Figure:
    """One multiple across the peer set, the company picked out in teal."""
    pts = [(r["name"], r["ticker"], r.get(key)) for r in rows
           if r.get(key) is not None and r[key] > 0]
    pts.sort(key=lambda p: p[2])
    f = _fig(max(280, 38 * len(pts) + 90), top=36)
    f.add_trace(go.Bar(
        y=[p[0][:26] for p in pts], x=[p[2] for p in pts], orientation="h",
        marker={"color": [T.YOURS if p[1].upper() == self_ticker.upper()
                          else _rgba(T.MARKET, 0.5) for p in pts]},
        text=[f"{p[2]:.1f}x" for p in pts], textposition="outside",
        textfont={"size": 11.5, "color": T.INK}, cliponaxis=False,
        hovertemplate="%{y}<br>" + label + " %{x:.1f}x<extra></extra>",
    ))
    if median:
        f.add_vline(x=median, line={"color": T.CONSENSUS, "width": 1.6})
        f.add_annotation(x=median, y=1.0, yref="paper", showarrow=False,
                         yshift=12, text=f"peer median {median:.1f}x",
                         font={"size": 11.5, "color": T.CONSENSUS})
    f.update_layout(bargap=0.4, showlegend=False,
                    margin={"l": 8, "r": 60, "t": 36, "b": 8})
    f.update_xaxes(title=f"{label} (x)", rangemode="tozero")
    f.update_yaxes(showgrid=False, ticks="", automargin=True)
    return f
