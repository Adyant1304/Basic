"""Mark to Market — what the price has to believe.

Type a ticker. Yahoo Finance supplies the financials, the engine builds a
baseline out of the company's own history, and every number downstream is
arithmetic you can audit. The sliders never call a model or the network, so
the value moves as fast as you can drag.

Run:  streamlit run app.py
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import streamlit as st

from mtm import charts, components as ui, theme as T
from mtm.data import Company, available_snapshots, get_company
from mtm.engine import (Assumptions, baseline_assumptions, build_wacc,
                        fan_chart, monte_carlo, project, reverse_dcf,
                        sensitivity_grid, tornado)
from mtm.metrics import (consensus_implied, quality_metrics, sanity_flags,
                         valuation_metrics)
from mtm.sample import sample_company
from mtm import landing

_at_home = not (st.session_state.get("ticker")
                or st.session_state.get("show_sample"))
st.set_page_config(
    page_title="Mark to Market", layout="wide",
    initial_sidebar_state="collapsed" if _at_home else "expanded")
st.markdown(T.CSS, unsafe_allow_html=True)

# The home screen owns the whole page: no sidebar, no tabs, nothing to
# configure until a company is on the table.
if _at_home:
    landing.render()
    st.stop()

PRESETS = {
    "Infosys": "INFY.NS",
    "HCLTech": "HCLTECH.NS",
    "Wipro": "WIPRO.NS",
    "TCS": "TCS.NS",
    "Asian Paints": "ASIANPAINT.NS",
    "Titan": "TITAN.NS",
}

# Slider keys, in percent units where the underlying value is a rate.
RATE_KEYS = ("g", "m", "wacc", "gt", "tax", "roic")
ALL_KEYS = RATE_KEYS + ("s2c", "yrs")


# --------------------------------------------------------------------------
# Cached data access. One network trip per ticker per hour; everything
# downstream is arithmetic, cached on the assumption tuple.
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False, ttl=3600)
def load(ticker: str) -> tuple[dict, list[str]]:
    c = get_company(ticker)
    return json.loads(c.to_json()), c.warnings


def _co(payload: dict) -> Company:
    return Company.from_dict(payload)


def _assumptions(key: tuple) -> Assumptions:
    g, m, w, gt, t, s2c, roic, yrs, m0 = key
    return Assumptions(growth_near=g, margin_target=m, wacc=w,
                       growth_terminal=gt, tax_rate=t, sales_to_capital=s2c,
                       roic_terminal=roic, years=int(yrs), margin_start=m0)


@st.cache_data(show_spinner=False)
def cached_mc(payload: dict, key: tuple, n: int) -> dict:
    mc = monte_carlo(_co(payload), _assumptions(key), n=n)
    return {**mc, "values": mc["values"].tolist()}


@st.cache_data(show_spinner=False)
def cached_grid(payload: dict, key: tuple, steps: int) -> dict:
    return sensitivity_grid(_co(payload), _assumptions(key), steps=steps)


@st.cache_data(show_spinner=False)
def cached_fan(payload: dict, key: tuple, n: int) -> dict:
    return fan_chart(_co(payload), _assumptions(key), n=n)


# --------------------------------------------------------------------------
# Company
# --------------------------------------------------------------------------

def _pick(symbol: str) -> None:
    """Change company from a button.

    This runs as an on_click callback rather than inline, because Streamlit
    refuses a write to a widget's own session_state key once that widget has
    been instantiated this run — and the ticker text input is created just
    above these buttons. Callbacks run before the next run's widgets, so the
    assignment lands safely.
    """
    st.session_state.ticker = symbol
    st.session_state.show_sample = False



st.session_state.setdefault("ticker", "")

with st.sidebar:
    st.markdown(ui.sidebar_head(
        "Company",
        "Any Yahoo Finance symbol. Indian listings need the exchange "
        "suffix: INFY.NS on the NSE, INFY.BO on the BSE."
    ), unsafe_allow_html=True)

    typed = st.text_input("Ticker", key="ticker", placeholder="INFY.NS",
                          label_visibility="collapsed")
    cols = st.columns(2)
    for i, (label, sym) in enumerate(PRESETS.items()):
        cols[i % 2].button(label, use_container_width=True, key=f"p_{sym}",
                           on_click=_pick, args=(sym,))
    st.button("Back to the home screen", use_container_width=True,
              key="go_home", on_click=_pick, args=("",))

ticker = (st.session_state.ticker or "").strip().upper()

warnings: list[str] = []
load_seconds = 0.0

if ticker:
    t0 = time.perf_counter()
    with st.spinner(f"Pulling {ticker} from Yahoo Finance"):
        try:
            payload, warnings = load(ticker)
        except Exception as exc:
            st.markdown(ui.masthead("no data"), unsafe_allow_html=True)
            st.error(
                f"Could not load **{ticker}**. {type(exc).__name__}: {exc}\n\n"
                "Check the symbol and its suffix — Indian listings need `.NS` "
                "or `.BO`. When the network is unavailable the app falls back "
                "to a saved snapshot if one exists."
            )
            snaps = available_snapshots()
            if snaps:
                st.caption("Snapshots available offline: " + ", ".join(snaps))
            st.stop()
    load_seconds = time.perf_counter() - t0
    c = _co(payload)
else:
    c = sample_company()
    warnings = list(c.warnings)
    payload = json.loads(c.to_json())

cur = c.currency

# --------------------------------------------------------------------------
# Market inputs and the WACC build
# --------------------------------------------------------------------------

with st.sidebar:
    st.markdown(ui.sidebar_head(
        "Market inputs",
        "The two numbers every Indian DCF rests on. Both are inputs because "
        "both move, and neither belongs hard-coded in a model."
    ), unsafe_allow_html=True)
    rf = st.slider("Risk-free rate, 10-year G-sec", 4.00, 10.00, 6.55, 0.05,
                   format="%.2f%%") / 100
    erp = st.slider("Equity risk premium", 4.00, 11.00, 7.00, 0.25,
                    format="%.2f%%") / 100
    beta_override = None
    if st.checkbox("Override beta", value=False):
        beta_override = st.slider("Beta", 0.30, 2.50, float(c.beta or 1.0), 0.01)

w = build_wacc(c, risk_free=rf, erp=erp, beta_override=beta_override)
base, prov = baseline_assumptions(c, w.wacc, risk_free=rf)
prov = {**c.provenance, **prov}

# Rebuild the baseline whenever the company or the market inputs change.
sig = (c.ticker, round(rf, 5), round(erp, 5), round(beta_override or -1.0, 4))
if st.session_state.get("_sig") != sig:
    st.session_state._sig = sig
    for k in ALL_KEYS:
        st.session_state.pop(k, None)

# Seed each slider once, so the widget owns its value afterwards and the
# snap buttons can write to it without Streamlit complaining.
defaults = {
    "g": base.growth_near * 100,
    "m": base.margin_target * 100,
    "wacc": w.wacc * 100,
    "gt": base.growth_terminal * 100,
    "tax": base.tax_rate * 100,
    "roic": base.roic_terminal * 100,
    "s2c": round(base.sales_to_capital, 1),
    "yrs": 10,
}
for k, v in defaults.items():
    st.session_state.setdefault(k, float(v) if k != "yrs" else int(v))

with st.sidebar:
    st.markdown(ui.sidebar_head(
        "Your assumptions",
        "Seeded from this company's own history, never from a model's "
        "opinion. Every starting value explains itself in the Audit tab."
    ), unsafe_allow_html=True)

    g = st.slider("Revenue growth, years 1-3", -10.0, 40.0, step=0.25,
                  format="%.2f%%", key="g",
                  help=prov.get("growth_near", "")) / 100
    m = st.slider("Target EBIT margin, final year", 1.0, 60.0, step=0.25,
                  format="%.2f%%", key="m",
                  help=prov.get("margin_target", "")) / 100
    wacc = st.slider("WACC", 5.0, 25.0, step=0.25, format="%.2f%%", key="wacc",
                     help="Built from CAPM above. Move it to disagree.") / 100
    gt = st.slider("Terminal growth", 0.0, 8.0, step=0.1, format="%.2f%%",
                   key="gt", help=prov.get("growth_terminal", "")) / 100

    with st.expander("Second-order assumptions"):
        tax = st.slider("Tax rate", 5.0, 45.0, step=0.5, format="%.1f%%",
                        key="tax", help=prov.get("tax_rate", "")) / 100
        s2c = st.slider("Sales to capital", 0.5, 8.0, step=0.1, key="s2c",
                        help=prov.get("sales_to_capital", ""))
        roic = st.slider("Terminal ROIC", 4.0, 45.0, step=0.5, format="%.1f%%",
                         key="roic", help=prov.get("roic_terminal", "")) / 100
        yrs = st.select_slider("Forecast years", [5, 7, 10, 12, 15], key="yrs")

a = Assumptions(growth_near=g, margin_target=m, wacc=wacc, growth_terminal=gt,
                tax_rate=tax, sales_to_capital=s2c, roic_terminal=roic,
                years=int(yrs), margin_start=base.margin_start)

p = project(c, a)
implied_g = reverse_dcf(c, a, "growth_near")
ci = consensus_implied(c, a)
mc = cached_mc(payload, a.key(), 6000)
pcts = {int(k): v for k, v in mc["percentiles"].items()}
flags = sanity_flags(c, a, p, w, risk_free=rf)

with st.sidebar:
    st.markdown(ui.sidebar_head("Snap to a case"), unsafe_allow_html=True)
    b1, b2 = st.columns(2)
    if b1.button("Market-implied", use_container_width=True,
                 disabled=implied_g is None,
                 help="Set growth to whatever today's price already assumes."):
        st.session_state.g = round(implied_g * 100, 2)
        st.rerun()
    if b2.button("History", use_container_width=True,
                 help="Reset every assumption to the history-seeded baseline."):
        for k in ALL_KEYS:
            st.session_state.pop(k, None)
        st.rerun()

# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

stamp = {
    "yahoo": f"Yahoo Finance, {c.fetched_at[:16].replace('T', ' ')} UTC",
    "snapshot": f"saved snapshot, {c.fetched_at[:10]}",
    "sample": "illustrative data",
}[c.source]
if load_seconds:
    stamp += f" in {load_seconds:.1f}s"

st.markdown(ui.masthead(stamp), unsafe_allow_html=True)

source_label = {"yahoo": "live from Yahoo Finance",
                "snapshot": "from a saved snapshot",
                "sample": "illustrative figures"}[c.source]
st.markdown(ui.company_line(c.name, c.ticker, c.sector, c.industry, cur,
                            c.price, c.market_cap, source_label),
            unsafe_allow_html=True)

if c.source == "sample":
    st.info("Worked example on invented figures. Enter a ticker in the "
            "sidebar for live financials.")
for ww in warnings:
    st.warning(ww)

st.markdown(ui.gap_bar(
    price=c.price, your_value=p.value_per_share, currency=cur,
    consensus=ci["target"] if ci else None,
    band=(pcts[5], pcts[95]), inner_band=(pcts[25], pcts[75]),
    implied_growth=implied_g, your_growth=a.growth_near,
    consensus_n=ci["n"] if ci else None,
), unsafe_allow_html=True)

st.markdown(ui.verdict(p.value_per_share, c.price, cur,
                       mc["prob_above_price"]), unsafe_allow_html=True)

if implied_g is not None:
    delta = a.growth_near - implied_g
    if abs(delta) < 0.0035:
        msg = ("Your growth assumption and the market's are effectively the "
               "same, so the price looks fair on your own numbers.")
    elif delta > 0:
        msg = (f"You are {delta * 100:.1f} percentage points more optimistic "
               "on growth than the price requires. That gap, rather than the "
               "fair value itself, is the actual claim you are making.")
    else:
        msg = (f"The price needs {abs(delta) * 100:.1f} percentage points more "
               "growth than you are willing to assume. The market is paying "
               "for something you do not see.")
    st.markdown(f'<p class="note">{msg}</p>', unsafe_allow_html=True)

tabs = st.tabs(["Projection", "Sensitivity", "Risk", "Business quality",
                "Audit"])

# ------------------------------- Projection -------------------------------
with tabs[0]:
    st.markdown(ui.section(
        "The forecast your assumptions produce",
        "Revenue compounds at your near-term rate for three years, then "
        "tapers to terminal growth. The shaded cone is what happens once "
        "growth itself is treated as uncertain."
    ), unsafe_allow_html=True)
    st.plotly_chart(
        charts.revenue_fan(c, cached_fan(payload, a.key(), 1200), p),
        use_container_width=True, config=T.CHART_CONFIG)

    left, right = st.columns(2)
    left.plotly_chart(charts.cash_flow_bars(c, p), use_container_width=True,
                      config=T.CHART_CONFIG)
    right.plotly_chart(charts.margin_path(c, p), use_container_width=True,
                       config=T.CHART_CONFIG)

    st.markdown(ui.section("How the value is built"), unsafe_allow_html=True)
    bridge = pd.DataFrame({
        "Step": ["Present value of forecast cash flows",
                 "Present value of terminal value",
                 "Enterprise value", "Less net debt", "Equity value"],
        "Amount": [T.money(v, cur) for v in
                   (p.pv_explicit, p.pv_terminal, p.enterprise_value,
                    -p.net_debt, p.equity_value)],
        "Share of enterprise value": [
            T.pct(p.pv_explicit / p.enterprise_value),
            T.pct(p.pv_terminal / p.enterprise_value),
            "100.0%", "", ""],
    })
    st.dataframe(bridge, hide_index=True, use_container_width=True)
    st.markdown(
        f'<p class="note">Equity value of {T.money(p.equity_value, cur)} '
        f'over {c.shares_out / 1e7:,.1f} crore shares gives '
        f'{T.per_share(p.value_per_share, cur)} a share.</p>',
        unsafe_allow_html=True)

# ------------------------------ Sensitivity -------------------------------
with tabs[1]:
    st.markdown(ui.section(
        "Where the answer is fragile",
        "WACC and terminal growth decide most of a DCF, because both act on "
        "the terminal value. Teal is upside to today's price, rust is "
        "downside. If the sign flips inside this grid, the verdict is a "
        "function of your discount rate rather than of the business."
    ), unsafe_allow_html=True)
    st.plotly_chart(
        charts.sensitivity_heatmap(cached_grid(payload, a.key(), 7),
                                   c.price, cur),
        use_container_width=True, config=T.CHART_CONFIG)

    st.markdown(ui.section("Which assumption carries the most weight"),
                unsafe_allow_html=True)
    tor = tornado(c, a)
    st.plotly_chart(charts.tornado_chart(tor, c.price, cur),
                    use_container_width=True, config=T.CHART_CONFIG)
    if tor:
        top = tor[0]
        st.markdown(
            f'<p class="note">Moving {top["label"].lower()} by '
            f'{charts.delta_label(top)} changes the value by '
            f'{T.per_share(top["swing"], cur)} a share, which is '
            f'{T.pct(top["pct_swing"])} of it. That is where the research '
            f'time belongs; the rest is rounding by comparison.</p>',
            unsafe_allow_html=True)

# --------------------------------- Risk -----------------------------------
with tabs[2]:
    st.markdown(ui.section(
        "The range, not the point",
        f"{mc['n']:,} runs of the same model, drawing growth, margin and WACC "
        "from normal distributions around your assumptions. A single fair "
        "value hides how wide the plausible band really is."
    ), unsafe_allow_html=True)
    st.plotly_chart(
        charts.mc_distribution({**mc, "values": np.array(mc["values"]),
                                "percentiles": pcts},
                               c.price, cur, p.value_per_share),
        use_container_width=True, config=T.CHART_CONFIG)

    stats = [("5th percentile", T.per_share(pcts[5], cur)),
             ("Median", T.per_share(pcts[50], cur)),
             ("95th percentile", T.per_share(pcts[95], cur)),
             ("Chance of beating the price",
              T.pct(mc["prob_above_price"], 0))]
    for col, (label, shown) in zip(st.columns(4), stats):
        col.markdown(
            '<div style="padding:.2rem 0 .9rem 0">'
            f'<div style="font-size:.78rem;color:var(--ink-soft)">{label}</div>'
            '<div style="font-size:1.5rem;font-weight:600;'
            f'letter-spacing:-.02em;color:var(--yours)">{shown}</div></div>',
            unsafe_allow_html=True)

    st.markdown(
        '<p class="note">Growth, margin and WACC are drawn independently '
        'here. In reality a demand shock and a margin shock tend to arrive '
        'together, so the true distribution has fatter tails than this one. '
        'Read the band as a floor on the uncertainty, not a ceiling.</p>',
        unsafe_allow_html=True)

    st.markdown(ui.section("Assumption checks"), unsafe_allow_html=True)
    st.markdown(ui.flag_block(flags), unsafe_allow_html=True)

# --------------------------- Business quality -----------------------------
with tabs[3]:
    st.markdown(ui.section(
        "Does the business earn its cost of capital?",
        "A DCF is only worth running on a business whose returns exceed what "
        "funding it costs. These are the checks that decide whether growth is "
        "worth paying for at all."
    ), unsafe_allow_html=True)
    st.markdown(ui.metric_block(quality_metrics(c, a, p, w), cur),
                unsafe_allow_html=True)

    st.markdown(ui.section("Is the valuation believable?"),
                unsafe_allow_html=True)
    st.markdown(ui.metric_block(valuation_metrics(c, a, p, w), cur),
                unsafe_allow_html=True)

    st.markdown(ui.section("The record"), unsafe_allow_html=True)
    st.plotly_chart(charts.history_bars(c), use_container_width=True,
                    config=T.CHART_CONFIG)

# -------------------------------- Audit -----------------------------------
with tabs[4]:
    st.markdown(ui.section(
        "Where every number came from",
        "Nothing in this model is a guess by a language model. Each baseline "
        "is computed from the company's reported financials by a named rule, "
        "and the rule is printed here."
    ), unsafe_allow_html=True)
    st.markdown(ui.provenance_block(prov), unsafe_allow_html=True)

    st.markdown(ui.section("The WACC build"), unsafe_allow_html=True)
    st.dataframe(pd.DataFrame({
        "Input": ["Risk-free rate, 10-year G-sec", "Equity risk premium",
                  "Beta", "Cost of equity, risk-free + beta x premium",
                  "Cost of debt", "Tax rate", "Weight of equity",
                  "Weight of debt", "WACC"],
        "Value": [T.pct(w.risk_free, 2), T.pct(w.equity_risk_premium, 2),
                  f"{w.beta:.2f}", T.pct(w.cost_of_equity, 2),
                  T.pct(w.cost_of_debt, 2), T.pct(w.tax_rate, 1),
                  T.pct(w.weight_equity, 1), T.pct(w.weight_debt, 1),
                  T.pct(w.wacc, 2)],
    }), hide_index=True, use_container_width=True)
    for n in w.notes:
        st.caption(n)

    st.markdown(ui.section("The full projection"), unsafe_allow_html=True)
    div = 1e7 if cur == "INR" else 1e9
    unit = "crore" if cur == "INR" else "bn"
    st.dataframe(pd.DataFrame({
        "Year": p.years,
        "Growth": [T.pct(v) for v in p.growth],
        "Margin": [T.pct(v) for v in p.margin],
        f"Revenue ({unit})": [round(v / div) for v in p.revenue],
        f"EBIT ({unit})": [round(v / div) for v in p.ebit],
        f"NOPAT ({unit})": [round(v / div) for v in p.nopat],
        f"Reinvestment ({unit})": [round(v / div) for v in p.reinvestment],
        f"FCFF ({unit})": [round(v / div) for v in p.fcff],
        "Discount factor": [round(v, 3) for v in p.discount_factors],
        f"PV of FCFF ({unit})": [round(v / div) for v in p.pv_fcff],
    }), hide_index=True, use_container_width=True)

    st.download_button(
        "Download this projection as CSV",
        pd.DataFrame({
            "year": p.years, "growth": p.growth, "margin": p.margin,
            "revenue": p.revenue, "ebit": p.ebit, "nopat": p.nopat,
            "reinvestment": p.reinvestment, "fcff": p.fcff,
            "discount_factor": p.discount_factors, "pv_fcff": p.pv_fcff,
        }).to_csv(index=False).encode(),
        file_name=f"{c.ticker}_projection.csv", mime="text/csv")

    st.markdown(ui.section("Reported financials, as fetched"),
                unsafe_allow_html=True)
    hist = pd.DataFrame({
        "Fiscal year": c.revenue.years,
        f"Revenue ({unit})": [round(v / div) for v in c.revenue.values],
    })
    for label, series in (("EBIT", c.ebit), ("Net income", c.net_income),
                          ("Free cash flow", c.fcf), ("Capex", c.capex)):
        by_year = dict(zip(series.years, series.values))
        hist[f"{label} ({unit})"] = [
            round(by_year[y] / div) if y in by_year else None
            for y in c.revenue.years]
    st.dataframe(hist, hide_index=True, use_container_width=True)

    st.markdown(ui.section("Method"), unsafe_allow_html=True)
    st.markdown(
        '<p class="note">'
        'Free cash flow to the firm is operating profit after tax less the '
        'reinvestment needed to fund growth, where reinvestment is revenue '
        'added divided by the sales-to-capital ratio. Cash flows are '
        'discounted at WACC. The terminal value grows at the terminal rate in '
        'perpetuity, and that growth is funded: the terminal reinvestment rate '
        'is terminal growth divided by terminal ROIC, so perpetual growth has '
        'to be paid for rather than assumed free. Enterprise value less net '
        'debt gives equity value. The reverse DCF solves by bisection for the '
        'growth rate that makes the model print today\'s market price.'
        '</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="note" style="color:var(--ink-faint)">'
        'Built for a business analytics course. Educational use only, not '
        'investment advice. Financial data comes from Yahoo Finance, which is '
        'unofficial and sometimes wrong, so the Audit tab exists to let you '
        'check it against the filings.</p>', unsafe_allow_html=True)
