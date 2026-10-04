"""The home screen: what someone sees before they have picked a company.

Its job is to teach the idea in one screen. The product's whole argument is
that a share price is a bet on a growth rate, so the hero is not a headline
over a stock photo — it is the gap bar itself, annotated, using exactly the
visual language the app will use once a ticker is loaded. Someone who reads
this screen already knows how to read the app.
"""

from __future__ import annotations

import html

import streamlit as st

from . import theme as T
from .components import masthead

PRESETS = {
    "Infosys": "INFY.NS",
    "HCLTech": "HCLTECH.NS",
    "Wipro": "WIPRO.NS",
    "TCS": "TCS.NS",
    "Asian Paints": "ASIANPAINT.NS",
    "Titan": "TITAN.NS",
}


# --------------------------------------------------------------------------
# The teaching diagram
# --------------------------------------------------------------------------

def concept_svg() -> str:
    """The gap bar, annotated. Numbers are the worked example's."""
    W, H = 1000.0, 292.0
    AX = 176.0
    L, R = 92.0, 908.0
    x_you, x_mkt = 352.0, 648.0

    s = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="100%" '
         f'style="display:block" role="img" '
         f'aria-label="A share price marked against a valuation, '
         f'showing the growth each one implies">']

    # Axis.
    s.append(f'<line x1="{L}" y1="{AX}" x2="{R}" y2="{AX}" '
             f'stroke="{T.RULE}" stroke-width="1.5"/>')

    # The gap between the two, on the axis.
    s.append(f'<rect x="{x_you}" y="{AX - 2.5:.0f}" '
             f'width="{x_mkt - x_you:.0f}" height="5" fill="{T.DOWN}"/>')

    # Your case.
    s.append(f'<line x1="{x_you}" y1="{AX - 4:.0f}" x2="{x_you}" '
             f'y2="{AX - 86:.0f}" stroke="{T.YOURS}" stroke-width="1.25"/>')
    s.append(f'<path d="M {x_you} {AX - 94:.0f} L {x_you + 8:.0f} '
             f'{AX - 82:.0f} L {x_you - 8:.0f} {AX - 82:.0f} Z" '
             f'fill="{T.YOURS}"/>')
    s.append(f'<text x="{x_you}" y="{AX - 118:.0f}" font-size="30" '
             f'font-weight="700" fill="{T.YOURS}" text-anchor="middle" '
             f'letter-spacing="-0.8">₹1,025</text>')
    s.append(f'<text x="{x_you}" y="{AX - 102:.0f}" font-size="13" '
             f'fill="{T.INK_SOFT}" text-anchor="middle">'
             f'what you think it is worth</text>')

    # Market price.
    s.append(f'<line x1="{x_mkt}" y1="{AX - 4:.0f}" x2="{x_mkt}" '
             f'y2="{AX - 44:.0f}" stroke="{T.MARKET}" stroke-width="1.25"/>')
    s.append(f'<circle cx="{x_mkt}" cy="{AX - 44:.0f}" r="7" '
             f'fill="{T.MARKET}"/>')
    s.append(f'<text x="{x_mkt}" y="{AX - 68:.0f}" font-size="24" '
             f'font-weight="600" fill="{T.MARKET}" text-anchor="middle" '
             f'letter-spacing="-0.6">₹1,148</text>')
    s.append(f'<text x="{x_mkt}" y="{AX - 54:.0f}" font-size="13" '
             f'fill="{T.INK_SOFT}" text-anchor="middle">'
             f'what it trades at today</text>')

    # Leaders down to the growth each one implies.
    for x, y_end, colour, growth, who in (
        (x_you, 238.0, T.YOURS, "9.1%", "your assumption"),
        (x_mkt, 238.0, T.MARKET, "12.0%", "the price’s assumption"),
    ):
        s.append(f'<line x1="{x}" y1="{AX + 6:.0f}" x2="{x}" y2="{y_end:.0f}" '
                 f'stroke="{colour}" stroke-width="1" stroke-dasharray="2 3" '
                 f'opacity="0.65"/>')
        s.append(f'<text x="{x}" y="{y_end + 22:.0f}" font-size="21" '
                 f'font-weight="600" fill="{colour}" text-anchor="middle" '
                 f'letter-spacing="-0.4">{growth}</text>')
        s.append(f'<text x="{x}" y="{y_end + 39:.0f}" font-size="12.5" '
                 f'fill="{T.INK_FAINT}" text-anchor="middle">{who}</text>')

    s.append(f'<text x="{(x_you + x_mkt) / 2:.0f}" y="{AX + 26:.0f}" '
             f'font-size="13" fill="{T.DOWN}" text-anchor="middle" '
             f'font-family="{T.FONT_SERIF}" font-style="italic">'
             f'the gap is the claim you are making</text>')

    # Captions at the far ends, so the axis reads as a price line.
    s.append(f'<text x="{L}" y="{AX + 22:.0f}" font-size="12" '
             f'fill="{T.INK_FAINT}">cheaper</text>')
    s.append(f'<text x="{R}" y="{AX + 22:.0f}" font-size="12" '
             f'fill="{T.INK_FAINT}" text-anchor="end">dearer</text>')

    s.append("</svg>")
    return "".join(s)


# --------------------------------------------------------------------------

_STEPS = [
    ("Fetch",
     "One call to Yahoo Finance brings back five years of income statement, "
     "balance sheet and cash flow, plus the current price, share count and "
     "beta. Every line item is looked up through a list of aliases, because "
     "Yahoo renames them between companies."),
    ("Anchor",
     "Each assumption is derived from the company's own record: growth from "
     "its revenue CAGR, margin from its historical median, the tax rate from "
     "tax paid over pretax income, reinvestment from the revenue it added per "
     "rupee spent. The Audit tab prints the rule behind every one."),
    ("Argue",
     "Then you disagree with it. Drag growth, margin, WACC or terminal growth "
     "and the valuation moves as fast as the slider does, because the whole "
     "model is local arithmetic rather than a call to anything."),
]

_COMPUTES = [
    ("Reverse DCF",
     "Solves for the growth rate that makes the model print today's price. "
     "Turns “is this cheap” into “what would have to be true”."),
    ("Sensitivity grid",
     "Value per share across WACC and terminal growth, the two assumptions "
     "that between them decide most of any DCF."),
    ("Tornado",
     "Which assumption moves the answer most, ranked. Tells you where the "
     "research time belongs."),
    ("Monte Carlo",
     "Six thousand runs drawing growth, margin and WACC from distributions "
     "around your case, so the point estimate never stands alone."),
    ("Assumption checks",
     "Flags a growth rate above anything in the record, a margin above the "
     "historical peak, and terminal growth above the risk-free rate."),
]

_LIMITS = [
    ("Yahoo Finance is unofficial",
     "Figures are occasionally stale or wrong, and coverage of Indian mid "
     "and small caps is patchy. The Audit tab shows exactly what was "
     "fetched so you can check it against the filings."),
    ("A DCF suits stable, cash-generative businesses",
     "It is a poor tool for loss-makers, for financials, and for anything "
     "cyclical enough that the last five years say little about the next ten."),
    ("The simulation draws independently",
     "A demand shock and a margin shock usually arrive together, so the real "
     "distribution has fatter tails than the one shown."),
]


def render() -> None:
    """Draw the home screen. Returns once the page is laid out."""
    st.markdown(masthead("no company loaded"), unsafe_allow_html=True)

    st.markdown(
        '<div class="lp-hero">'
        '<h2 class="lp-h1">What does the price<br>have to believe?</h2>'
        '<p class="lp-lede">Every share price is a bet on a growth rate. '
        'Mark to Market reads a company’s reported financials, works out '
        'which rate today’s price is paying for, and then lets you argue '
        'with it.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ---- the one thing on this page that asks for an action --------------
    st.markdown('<div class="lp-ask">Open a company</div>',
                unsafe_allow_html=True)
    f1, f2, _ = st.columns([24, 8, 28])
    typed = f1.text_input(
        "Ticker", key="landing_ticker", placeholder="INFY.NS",
        label_visibility="collapsed")
    opened = f2.button("Open", use_container_width=True, type="primary")
    st.markdown(
        '<p class="lp-hint">Any Yahoo Finance symbol. Indian listings need '
        'the exchange suffix: INFY.NS on the NSE, INFY.BO on the BSE. '
        'US tickers work bare.</p>',
        unsafe_allow_html=True)

    if opened and typed.strip():
        st.session_state.ticker = typed.strip().upper()
        st.rerun()

    st.markdown('<div class="lp-or">Or start from one of these</div>',
                unsafe_allow_html=True)
    cols = st.columns(6)
    for i, (label, sym) in enumerate(PRESETS.items()):
        if cols[i].button(label, use_container_width=True, key=f"lp_{sym}"):
            st.session_state.ticker = sym
            st.rerun()

    st.markdown('<div class="lp-rule"></div>', unsafe_allow_html=True)
    s1, s2, _ = st.columns([30, 13, 17])
    s1.markdown(
        '<p class="lp-hint" style="margin-top:.45rem">No connection? The '
        'worked example runs on invented figures, so the whole tool is '
        'visible without fetching anything.</p>',
        unsafe_allow_html=True)
    if s2.button("See the worked example", use_container_width=True,
                 key="lp_sample"):
        st.session_state.show_sample = True
        st.rerun()

    # ---- the teaching diagram -------------------------------------------
    st.markdown(
        '<div class="lp-diagram">' + concept_svg() + '</div>'
        '<p class="lp-cap">Infosys, say, trades at a price that only makes '
        'sense if revenue compounds at 12% a year. You think 9% is more '
        'likely. The tool exists to find that difference and let you defend '
        'it — not to hand you a price target.</p>',
        unsafe_allow_html=True,
    )

    # ---- how it works: a real sequence, so numbered ----------------------
    st.markdown('<div class="lp-sec">How it reads a company</div>',
                unsafe_allow_html=True)
    cols = st.columns(3, gap="large")
    for col, (i, (title, body)) in zip(cols, enumerate(_STEPS, start=1)):
        col.markdown(
            f'<div class="lp-step"><div class="lp-num">{i}</div>'
            f'<div class="lp-st">{html.escape(title)}</div>'
            f'<p class="lp-sb">{html.escape(body)}</p></div>',
            unsafe_allow_html=True)

    # ---- what it computes ------------------------------------------------
    st.markdown('<div class="lp-sec">What it computes</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<div class="lp-list">' + "".join(
            f'<div class="lp-row"><div class="lp-rk">{html.escape(k)}</div>'
            f'<div class="lp-rv">{v}</div></div>'
            for k, v in _COMPUTES
        ) + '</div>', unsafe_allow_html=True)

    # ---- the honest part -------------------------------------------------
    st.markdown('<div class="lp-sec">What it will not do</div>',
                unsafe_allow_html=True)
    st.markdown(
        '<p class="lp-note">A valuation tool that does not state its own '
        'limits is selling something.</p>'
        '<div class="lp-list">' + "".join(
            f'<div class="lp-row"><div class="lp-rk">{html.escape(k)}</div>'
            f'<div class="lp-rv">{html.escape(v)}</div></div>'
            for k, v in _LIMITS
        ) + '</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="lp-foot"><p>Built for a business analytics course. '
        'Educational use only, not investment advice. Nothing in the '
        'valuation path is produced by a language model: the financials come '
        'from Yahoo Finance and every figure after that is arithmetic the '
        'Audit tab will show you.</p></div>',
        unsafe_allow_html=True)
