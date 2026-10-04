"""HTML and SVG pieces that Streamlit's widgets cannot express.

The gap bar is the one bold element in the app. It answers the question the
whole tool exists for — what is the market assuming, and where does your own
case sit against it — on a single axis, with the simulated range drawn
behind it so a point estimate never looks more certain than it is.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from . import theme as T
from .metrics import Flag, Metric


# --------------------------------------------------------------------------
# Masthead and company line
# --------------------------------------------------------------------------

def masthead(stamp: str) -> str:
    return (
        '<div class="mast">'
        '<h1>Mark to Market</h1>'
        '<span class="tag">what the price has to believe</span>'
        f'<span class="stamp">{html.escape(stamp)}</span>'
        '</div>'
    )


def company_line(name: str, ticker: str, sector: str, industry: str,
                 currency: str, price: float, mcap: float,
                 source_label: str) -> str:
    bits = [f"<b>{html.escape(ticker)}</b>"]
    if industry:
        bits.append(html.escape(industry))
    elif sector:
        bits.append(html.escape(sector))
    bits.append(f"{T.per_share(price, currency)} per share")
    bits.append(f"{T.money(mcap, currency)} market value")
    bits.append(html.escape(source_label))
    return (
        '<div class="co">'
        f'<p class="nm">{html.escape(name)}</p>'
        f'<div class="meta">{" &nbsp;·&nbsp; ".join(bits)}</div>'
        '</div>'
    )


# --------------------------------------------------------------------------
# The gap bar
# --------------------------------------------------------------------------

@dataclass
class Mark:
    value: float
    label: str
    sub: str
    colour: str
    stem: float          # pixel height of the stem above the axis
    glyph: str           # "circle" | "triangle" | "diamond"


def gap_bar(price: float, your_value: float, currency: str,
            consensus: float | None = None,
            band: tuple[float, float] | None = None,
            inner_band: tuple[float, float] | None = None,
            implied_growth: float | None = None,
            your_growth: float | None = None,
            consensus_n: int | None = None) -> str:
    """One axis, three marks, the simulated range on a rail beneath it."""
    W, H = 1000.0, 212.0
    AX = 132.0                      # axis baseline
    L, R = 76.0, 924.0

    marks = [
        Mark(price, T.per_share(price, currency), "market price",
             T.MARKET, 26.0, "circle"),
        Mark(your_value, T.per_share(your_value, currency), "your case",
             T.YOURS, 92.0, "triangle"),
    ]
    if consensus is not None:
        sub = "analyst target"
        if consensus_n:
            sub = f"analyst target, n={consensus_n}"
        marks.append(Mark(consensus, T.per_share(consensus, currency), sub,
                          T.CONSENSUS, 58.0, "diamond"))

    pts = [m.value for m in marks]
    if band:
        pts += list(band)
    lo_v, hi_v = min(pts), max(pts)
    pad = max((hi_v - lo_v) * 0.18, hi_v * 0.04, 1e-9)
    lo_v, hi_v = lo_v - pad, hi_v + pad

    def x(v: float) -> float:
        if hi_v <= lo_v:
            return (L + R) / 2
        return L + (v - lo_v) / (hi_v - lo_v) * (R - L)

    up = your_value >= price
    gap_colour = T.YOURS if up else T.DOWN
    s: list[str] = [
        f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" '
        f'style="display:block;max-height:220px" '
        f'role="img" aria-label="Fair value against market price">'
    ]

    # Axis.
    s.append(
        f'<line x1="{L}" y1="{AX}" x2="{R}" y2="{AX}" '
        f'stroke="{T.RULE}" stroke-width="1.5"/>'
    )

    # The gap itself: a solid span on the axis from price to your case.
    gx0, gx1 = sorted((x(price), x(your_value)))
    s.append(
        f'<rect x="{gx0:.1f}" y="{AX - 2:.1f}" width="{max(gx1 - gx0, 1):.1f}" '
        f'height="4" fill="{gap_colour}"/>'
    )

    # The simulated range sits on its own rail below the axis, so the spread
    # is never confused with the gap it surrounds.
    if band:
        bx0, bx1 = x(band[0]), x(band[1])
        s.append(
            f'<rect x="{bx0:.1f}" y="{AX + 12:.1f}" '
            f'width="{max(bx1 - bx0, 1):.1f}" height="11" '
            f'fill="{T.YOURS}" opacity="0.16" rx="1.5"/>'
        )
        if inner_band:
            ix0, ix1 = x(inner_band[0]), x(inner_band[1])
            s.append(
                f'<rect x="{ix0:.1f}" y="{AX + 12:.1f}" '
                f'width="{max(ix1 - ix0, 1):.1f}" height="11" '
                f'fill="{T.YOURS}" opacity="0.34" rx="1.5"/>'
            )
        s.append(
            f'<line x1="{x(your_value):.1f}" y1="{AX + 10:.1f}" '
            f'x2="{x(your_value):.1f}" y2="{AX + 25:.1f}" '
            f'stroke="{T.YOURS}" stroke-width="1.25"/>'
        )
        s.append(
            f'<text x="{L}" y="{AX + 42:.1f}" font-size="11.5" '
            f'fill="{T.INK_FAINT}">Simulated range: the darker band is the '
            f'middle half of outcomes, the lighter one the 5th to 95th '
            f'percentile</text>'
        )

    # Marks, drawn in value order so the stems read cleanly.
    for m in sorted(marks, key=lambda k: k.value):
        mx = x(m.value)
        anchor = "middle"
        if mx < L + 70:
            anchor = "start"
        elif mx > R - 70:
            anchor = "end"

        if m.stem > 0:
            s.append(
                f'<line x1="{mx:.1f}" y1="{AX - 4:.1f}" x2="{mx:.1f}" '
                f'y2="{AX - m.stem:.1f}" stroke="{m.colour}" '
                f'stroke-width="1.25"/>'
            )
        gy = AX - m.stem
        if m.glyph == "circle":
            s.append(f'<circle cx="{mx:.1f}" cy="{gy:.1f}" r="6.5" '
                     f'fill="{m.colour}"/>')
        elif m.glyph == "triangle":
            s.append(
                f'<path d="M {mx:.1f} {gy - 8:.1f} L {mx + 7.5:.1f} {gy + 4:.1f} '
                f'L {mx - 7.5:.1f} {gy + 4:.1f} Z" fill="{m.colour}"/>'
            )
        else:
            s.append(
                f'<path d="M {mx:.1f} {gy - 7.5:.1f} L {mx + 7:.1f} {gy:.1f} '
                f'L {mx:.1f} {gy + 7.5:.1f} L {mx - 7:.1f} {gy:.1f} Z" '
                f'fill="{m.colour}"/>'
            )

        weight = 700 if m.glyph == "triangle" else 600
        size = 22 if m.glyph == "triangle" else 17
        s.append(
            f'<text x="{mx:.1f}" y="{gy - 24:.1f}" font-size="{size}" '
            f'font-weight="{weight}" fill="{m.colour}" '
            f'text-anchor="{anchor}" letter-spacing="-0.5">'
            f'{html.escape(m.label)}</text>'
        )
        s.append(
            f'<text x="{mx:.1f}" y="{gy - 11:.1f}" font-size="11.5" '
            f'fill="{T.INK_SOFT}" text-anchor="{anchor}">'
            f'{html.escape(m.sub)}</text>'
        )

    # The sentence under the axis: the actual finding.
    if implied_growth is not None and your_growth is not None:
        verdict = (
            f"Today's price is paid for by {T.pct(implied_growth)} revenue "
            f"growth a year. You are assuming {T.pct(your_growth)}."
        )
        s.append(
            f'<text x="{L}" y="{H - 8:.1f}" font-size="14.5" '
            f'fill="{T.INK}" font-family="Source Serif 4, Georgia, serif">'
            f'{html.escape(verdict)}</text>'
        )
    s.append("</svg>")
    return (
        '<div style="background:var(--paper-2);border:1px solid var(--rule);'
        'border-radius:2px;padding:1.1rem 1rem .6rem 1rem;margin:.9rem 0 0 0;">'
        + "".join(s) + "</div>"
    )


# --------------------------------------------------------------------------
# Verdict sentence
# --------------------------------------------------------------------------

def verdict(value: float, price: float, currency: str,
            prob_above: float | None = None) -> str:
    up = value >= price
    cls = "up" if up else "dn"
    word = "above" if up else "below"
    gap = abs(value / price - 1) if price else 0.0
    out = (
        f'<p class="verdict">On your assumptions the business is worth '
        f'<span class="big {cls}">{T.per_share(value, currency)}</span> a share, '
        f'{T.pct(gap)} {word} the market. '
    )
    if prob_above is not None:
        out += (
            f'Across simulated outcomes it closes above today\'s price '
            f'{T.pct(prob_above, 0)} of the time.'
        )
    return out + "</p>"


# --------------------------------------------------------------------------
# Metric rows
# --------------------------------------------------------------------------

def metric_row(m: Metric, currency: str) -> str:
    colour = T.STATUS.get(m.status, T.INK_SOFT)
    arrow = {"higher": "Higher is better",
             "lower": "Lower is better",
             "stable": "Stability matters more than level"}[m.direction]
    return (
        f'<div class="mrow" style="--edge:{colour}">'
        '<div>'
        f'<div class="lab">{html.escape(m.label)}</div>'
        f'<div class="val">{m.display(currency)}</div>'
        f'<div class="band">{html.escape(m.band)}</div>'
        f'<div class="dir">{arrow}</div>'
        '</div>'
        f'<div class="read">{html.escape(m.reading)}</div>'
        '</div>'
    )


def metric_block(metrics: list[Metric], currency: str) -> str:
    return ('<div style="border-top:1px solid var(--rule);margin-top:.6rem">'
            + "".join(metric_row(m, currency) for m in metrics) + "</div>")


# --------------------------------------------------------------------------
# Flags and provenance
# --------------------------------------------------------------------------

_FLAG_COLOUR = {"error": T.POOR, "warn": T.WATCH, "info": T.INK_SOFT}


def flag_block(flags: list[Flag]) -> str:
    if not flags:
        return (
            f'<div class="flag" style="--fc:{T.GOOD}">'
            '<div class="ft">Every assumption is inside its historical range</div>'
            '<div class="fd">Growth, margin and terminal growth all sit within '
            'what this company has done before and what theory allows. Nothing '
            'here needs a special explanation.</div></div>'
        )
    return "".join(
        f'<div class="flag" style="--fc:{_FLAG_COLOUR[f.severity]}">'
        f'<div class="ft">{html.escape(f.title)}</div>'
        f'<div class="fd">{html.escape(f.detail)}</div></div>'
        for f in flags
    )


_PROV_LABELS = {
    "growth_near": "Revenue growth",
    "margin_target": "Target EBIT margin",
    "growth_terminal": "Terminal growth",
    "roic_terminal": "Terminal ROIC",
    "sales_to_capital": "Sales to capital",
    "tax_rate": "Tax rate",
    "beta": "Beta",
    "fcf": "Free cash flow",
}


def provenance_block(prov: dict[str, str]) -> str:
    rows = []
    for k, v in prov.items():
        label = _PROV_LABELS.get(k, k.replace("_", " ").capitalize())
        rows.append(
            f'<div class="pr"><div class="k">{html.escape(label)}</div>'
            f'<div class="v">{html.escape(v)}</div></div>'
        )
    return f'<div class="prov">{"".join(rows)}</div>'


def section(title: str, note: str | None = None) -> str:
    out = f'<div class="sec">{html.escape(title)}</div>'
    if note:
        out += f'<p class="note">{html.escape(note)}</p>'
    return out


def sidebar_head(title: str, note: str | None = None) -> str:
    out = f'<div class="sb-h">{html.escape(title)}</div>'
    if note:
        out += f'<p class="sb-n">{html.escape(note)}</p>'
    return out
