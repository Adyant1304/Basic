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

from mtm import beta as beta_mod
from mtm import charts, components as ui, landing, peers as P, theme as T, views
from mtm.data import Company, available_snapshots, get_company
from mtm.engine import (Assumptions, baseline_assumptions, build_wacc,
                        dcf_suitability, fan_chart, monte_carlo, project,
                        reverse_dcf, sensitivity_grid, tornado)
from mtm.metrics import (consensus_implied, quality_metrics, sanity_flags,
                         valuation_metrics)
from mtm.sample import sample_company, sample_peer_set

STRETCH = views.STRETCH

# A link like  ?ticker=TCS.NS  opens that company directly. It is read once
# per session so the sidebar and home buttons can still change company.
if "ticker" in st.query_params and not st.session_state.get("_qp_read"):
    st.session_state._qp_read = True
    st.session_state.ticker = str(st.query_params["ticker"]).strip().upper()

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

PRESETS = landing.PRESETS

# Slider keys, in percent units where the underlying value is a rate.
RATE_KEYS = ("g", "m", "wacc", "gt", "tax", "roic")
ALL_KEYS = RATE_KEYS + ("s2c", "yrs")

# Each slider's range. A seeded value outside its slider's range makes
# Streamlit raise, so every default is clamped to these (see `defaults`).
SLIDER_RANGE = {"g": (-10.0, 40.0), "m": (1.0, 60.0), "wacc": (5.0, 25.0),
                "gt": (0.0, 8.0), "tax": (5.0, 45.0), "roic": (4.0, 45.0),
                "s2c": (0.5, 8.0)}


# --------------------------------------------------------------------------
# Cached data access. One network trip per ticker per hour; everything
# downstream is arithmetic, cached on the assumption tuple. The payload is
# passed as an underscore argument so Streamlit does not hash 30 KB of JSON
# on every slider move; the token identifies it instead.
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
def cached_mc(token: str, key: tuple, n: int, _payload: dict) -> dict:
    mc = monte_carlo(_co(_payload), _assumptions(key), n=n)
    return {**mc, "values": mc["values"].tolist()}


@st.cache_data(show_spinner=False)
def cached_grid(token: str, key: tuple, steps: int, _payload: dict) -> dict:
    return sensitivity_grid(_co(_payload), _assumptions(key), steps=steps)


@st.cache_data(show_spinner=False)
def cached_fan(token: str, key: tuple, n: int, _payload: dict) -> dict:
    return fan_chart(_co(_payload), _assumptions(key), n=n)


@st.cache_data(show_spinner=False, ttl=3600)
def cached_peers(token: str, custom: tuple, _payload: dict) -> dict:
    return P.load_peer_set(_co(_payload), list(custom))


# --------------------------------------------------------------------------
# Callbacks. Streamlit refuses a write to a widget's own session_state key
# once that widget has been created in the current run, and every widget
# below is created before the buttons that want to move it. Callbacks run
# *before* the next run's widgets, so the assignment lands safely. Any new
# button that changes a widget's value must use this pattern.
# --------------------------------------------------------------------------

def _pick(symbol: str) -> None:
    st.session_state.ticker = symbol
    st.session_state.show_sample = False


def _snap_to_market(growth: float) -> None:
    lo, hi = SLIDER_RANGE["g"]
    st.session_state.g = float(min(max(round(growth * 100, 2), lo), hi))


def _snap_to_history() -> None:
    for k in ALL_KEYS:
        st.session_state.pop(k, None)


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
        cols[i % 2].button(label, width="stretch", key=f"p_{sym}",
                           on_click=_pick, args=(sym,))
    st.button("Back to the home screen", width="stretch",
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

token = f"{c.ticker}|{c.fetched_at}"
cur = c.currency
mkt = c.market
div, unit = T.unit_for(cur)

# Is a free-cash-flow DCF the right tool for this company at all?
dcf_ok, dcf_reason = dcf_suitability(c)
can_force = bool(c.revenue.latest and c.revenue.latest > 0)
force_dcf = False
if not dcf_ok and can_force:
    with st.sidebar:
        force_dcf = st.checkbox(
            "Run the DCF anyway (not recommended)", key=f"force_{c.ticker}",
            help="The model will run, but its answer is not meaningful for "
                 "this kind of company.")
dcf_on = dcf_ok or force_dcf

# --------------------------------------------------------------------------
# Market inputs and the WACC build
#
# The risk-free rate and equity risk premium belong to the market the stock
# trades in, so each market keeps its own slider state (the widget key
# includes the market). Beta is measured per company; the selector only
# decides which estimate feeds the cost of equity.
# --------------------------------------------------------------------------

rf_default = c.live_risk_free or mkt.risk_free

with st.sidebar:
    st.markdown(ui.sidebar_head(
        "Market inputs",
        f"Discount-rate inputs for {mkt.name}. Both move, so neither is "
        "hard-coded."
    ), unsafe_allow_html=True)
    rf = st.slider(f"Risk-free rate, {mkt.rf_label}", 0.0, 12.0,
                   round(rf_default * 100, 2), 0.05, format="%.2f%%",
                   key=f"rf_{mkt.key}") / 100
    if c.live_risk_free:
        st.caption(f"Default is today's live yield from Yahoo Finance "
                   f"({mkt.live_rf_symbol}).")
    elif mkt.key == "IN":
        st.caption("Yahoo does not carry the Indian 10-year yield, so 6.55% "
                   "is a typed-in default. Update it to the current G-sec.")
    elif not mkt.calibrated:
        st.caption(f"Placeholder default: set the risk-free rate and "
                   f"premium for {mkt.name} yourself.")
    erp = st.slider("Equity risk premium", 2.0, 11.0,
                    round(mkt.erp * 100, 2), 0.25, format="%.2f%%",
                    key=f"erp_{mkt.key}") / 100

    # ---- beta: measured per company, never a fixed range ------------------
    bi = c.beta_info or {}
    opts = beta_mod.options(bi)
    if not opts and c.beta:
        opts = {"stored": float(c.beta)}
    labels = {
        "regression": (f"Regression, {bi.get('years', 5)}-year "
                       f"{bi.get('frequency', 'weekly')} vs "
                       f"{bi.get('benchmark_name', 'index')}"),
        "adjusted": "Blume-adjusted regression",
        "yahoo": "Yahoo Finance reported",
        "stored": "Saved beta",
        "custom": "Custom",
    }
    short = {
        "regression": (f"{bi.get('years', 5)}-year {bi.get('frequency', '')} "
                       f"regression vs {bi.get('benchmark_name', 'index')}"),
        "adjusted": "Blume-adjusted regression beta",
        "yahoo": "Yahoo Finance reported",
        "stored": "saved with the snapshot",
        "custom": "your own input",
    }
    keys = list(opts) + ["custom"]
    default_key = bi.get("default") if bi.get("default") in opts else keys[0]
    beta_key = st.selectbox(
        "Beta", keys, index=keys.index(default_key), key=f"beta_src_{c.ticker}",
        format_func=lambda k: (f"{labels[k]}: {opts[k]:.2f}" if k in opts
                               else labels[k]),
        help="Beta is how much the stock moves when the market moves. It is "
             "measured from this company's own price history, so it differs "
             "for every company.")
    if beta_key == "custom":
        seed = float(min(max(c.beta or 1.0, 0.10), 3.50))
        beta_value = st.slider("Custom beta", 0.10, 3.50, seed, 0.01,
                               key=f"beta_custom_{c.ticker}")
    else:
        beta_value = opts.get(beta_key)
    if beta_key in ("regression", "adjusted") and bi.get("raw") is not None:
        st.caption(f"R-squared {bi['r2']:.2f}, {bi['n']} observations, "
                   f"95% range {bi['ci_low']:.2f} to {bi['ci_high']:.2f}. "
                   f"Yahoo itself reports "
                   f"{'n/a' if bi.get('yahoo') is None else format(bi['yahoo'], '.2f')}.")

w = build_wacc(c, risk_free=rf, erp=erp, beta_override=beta_value,
               beta_label=short[beta_key])
base, prov = baseline_assumptions(c, w.wacc, risk_free=rf)
prov = {**c.provenance, **prov}

# Rebuild the baseline whenever the company or the market inputs change.
sig = (c.ticker, round(rf, 5), round(erp, 5), round(w.beta, 4))
if st.session_state.get("_sig") != sig:
    st.session_state._sig = sig
    for k in ALL_KEYS:
        st.session_state.pop(k, None)

# Seed each slider once, so the widget owns its value afterwards and the
# snap buttons can write to it from a callback. Seeds are clamped to the
# slider's range: a loss-maker's margin or a high-beta WACC can fall outside
# it, and Streamlit raises rather than clamping for you.
raw_defaults = {
    "g": base.growth_near * 100,
    "m": base.margin_target * 100,
    "wacc": w.wacc * 100,
    "gt": base.growth_terminal * 100,
    "tax": base.tax_rate * 100,
    "roic": base.roic_terminal * 100,
    "s2c": round(base.sales_to_capital, 1),
}
PROV_KEY = {"g": "growth_near", "m": "margin_target", "wacc": "wacc",
            "gt": "growth_terminal", "tax": "tax_rate",
            "roic": "roic_terminal", "s2c": "sales_to_capital"}
defaults: dict[str, float | int] = {}
for k, v in raw_defaults.items():
    lo, hi = SLIDER_RANGE[k]
    defaults[k] = float(min(max(v, lo), hi))
    if abs(defaults[k] - v) > 1e-9:
        prov[PROV_KEY[k]] = (
            prov.get(PROV_KEY[k], "")
            + f" The slider only reaches {lo:g} to {hi:g}, so the starting "
            f"value was held at {defaults[k]:g}.").strip()
defaults["yrs"] = 10
for k, v in defaults.items():
    st.session_state.setdefault(k, float(v) if k != "yrs" else int(v))

if dcf_on:
    with st.sidebar:
        st.markdown(ui.sidebar_head(
            "Your assumptions",
            "Seeded from this company's own history, never from a model's "
            "opinion. Every starting value explains itself in the Audit tab."
        ), unsafe_allow_html=True)

        g = st.slider("Revenue growth, years 1-3", *SLIDER_RANGE["g"],
                      step=0.25, format="%.2f%%", key="g",
                      help=prov.get("growth_near", "")) / 100
        m = st.slider("Target operating margin, final year",
                      *SLIDER_RANGE["m"], step=0.25, format="%.2f%%", key="m",
                      help=prov.get("margin_target", "")) / 100
        wacc = st.slider("WACC", *SLIDER_RANGE["wacc"], step=0.25,
                         format="%.2f%%", key="wacc",
                         help="Built from CAPM above. Move it to disagree."
                         ) / 100
        gt = st.slider("Terminal growth", *SLIDER_RANGE["gt"], step=0.1,
                       format="%.2f%%", key="gt",
                       help=prov.get("growth_terminal", "")) / 100

        with st.expander("Second-order assumptions"):
            tax = st.slider("Tax rate", *SLIDER_RANGE["tax"], step=0.5,
                            format="%.1f%%", key="tax",
                            help=prov.get("tax_rate", "")) / 100
            s2c = st.slider("Sales to capital", *SLIDER_RANGE["s2c"],
                            step=0.1, key="s2c",
                            help=prov.get("sales_to_capital", ""))
            roic = st.slider("Terminal ROIC", *SLIDER_RANGE["roic"],
                             step=0.5, format="%.1f%%", key="roic",
                             help=prov.get("roic_terminal", "")) / 100
            yrs = st.select_slider("Forecast years", [5, 7, 10, 12, 15],
                                   key="yrs")

    a = Assumptions(growth_near=g, margin_target=m, wacc=wacc,
                    growth_terminal=gt, tax_rate=tax, sales_to_capital=s2c,
                    roic_terminal=roic, years=int(yrs),
                    margin_start=base.margin_start)

    p = project(c, a)
    implied_g = reverse_dcf(c, a, "growth_near")
    ci = consensus_implied(c, a)
    mc = cached_mc(token, a.key(), 6000, payload)
    pcts = {int(k): v for k, v in mc["percentiles"].items()}
    flags = sanity_flags(c, a, p, w, risk_free=rf)

    g_lo, g_hi = SLIDER_RANGE["g"]
    can_snap = implied_g is not None and g_lo <= implied_g * 100 <= g_hi
    with st.sidebar:
        st.markdown(ui.sidebar_head("Snap to a case"), unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        b1.button("Market-implied", width="stretch", key="snap_market",
                  disabled=not can_snap, on_click=_snap_to_market,
                  args=(implied_g if implied_g is not None else 0.0,),
                  help="Set growth to whatever today's price already "
                       "assumes." if can_snap else
                       "The growth today's price implies is outside this "
                       "slider's range, or no growth rate reaches the price.")
        b2.button("History", width="stretch", key="snap_history",
                  on_click=_snap_to_history,
                  help="Reset every assumption to the history-seeded "
                       "baseline.")
else:
    a = p = implied_g = ci = mc = pcts = flags = None

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
            "sidebar for live financials.", icon="ℹ️")
for ww in warnings:
    # The banner below says the same thing more fully for a company a DCF
    # cannot value, so the data-layer note would only repeat it.
    if not dcf_ok and ww.startswith("No operating income line"):
        continue
    st.warning(ww)

if not dcf_ok:
    st.markdown(ui.banner(
        "A DCF is not the right tool for this company",
        dcf_reason + (" The DCF has been run anyway at your request, so "
                      "treat its output as an exercise, not a valuation."
                      if force_dcf else
                      " The Overview, Segments and Relative value tabs "
                      "still apply; the DCF tabs are hidden. Tick the box in "
                      "the sidebar to run it regardless.")),
        unsafe_allow_html=True)

if dcf_on:
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
            msg = ("Your growth assumption and the market's are effectively "
                   "the same, so the price looks fair on your own numbers.")
        elif delta > 0:
            msg = (f"You are {delta * 100:.1f} percentage points more "
                   "optimistic on growth than the price requires. That gap, "
                   "rather than the fair value itself, is the actual claim "
                   "you are making.")
        else:
            msg = (f"The price needs {abs(delta) * 100:.1f} percentage points "
                   "more growth than you are willing to assume. The market is "
                   "paying for something you do not see.")
        st.markdown(f'<p class="note">{msg}</p>', unsafe_allow_html=True)
    else:
        st.markdown(
            '<p class="note">No growth rate between -25% and 60% makes this '
            'model print today\'s price, so there is no market-implied growth '
            'to show. The price is outside what these margin, WACC and '
            'reinvestment assumptions can reach.</p>',
            unsafe_allow_html=True)

names = (["Overview", "Segments", "Relative value"]
         + (["Projection", "Sensitivity", "Risk", "Business quality"]
            if dcf_on else []) + ["Audit"])
tab = dict(zip(names, st.tabs(names)))

# -------------------------------- Overview ---------------------------------
with tab["Overview"]:
    views.overview_tab(c, w, financial=not dcf_ok)

# -------------------------------- Segments ---------------------------------
with tab["Segments"]:
    views.segments_tab(c)

# ----------------------------- Relative value ------------------------------
with tab["Relative value"]:
    def _peers(_ticker: str, custom: tuple) -> dict:
        if c.source == "sample":
            return sample_peer_set()
        return cached_peers(token, custom, payload)

    dcf_summary = ({"point": p.value_per_share, "p5": pcts[5],
                    "p95": pcts[95]} if dcf_on else None)
    views.relative_tab(c, _peers, dcf_summary, skip_ev=not dcf_ok)

if dcf_on:
    # ------------------------------ Projection ------------------------------
    with tab["Projection"]:
        st.markdown(ui.section(
            "The forecast your assumptions produce",
            "Revenue compounds at your near-term rate for three years, then "
            "tapers to terminal growth. The shaded cone is what happens once "
            "growth itself is treated as uncertain."
        ), unsafe_allow_html=True)
        st.plotly_chart(
            charts.revenue_fan(c, cached_fan(token, a.key(), 1200, payload), p),
            config=T.CHART_CONFIG, **STRETCH)

        left, right = st.columns(2)
        left.plotly_chart(charts.cash_flow_bars(c, p),
                          config=T.CHART_CONFIG, **STRETCH)
        right.plotly_chart(charts.margin_path(c, p),
                           config=T.CHART_CONFIG, **STRETCH)

        st.markdown(ui.section("How the value is built"),
                    unsafe_allow_html=True)
        bridge = pd.DataFrame({
            "Step": ["Present value of forecast cash flows",
                     "Present value of terminal value",
                     "Enterprise value",
                     "Less net debt (or plus net cash)", "Equity value"],
            "Amount": [T.money(v, cur) for v in
                       (p.pv_explicit, p.pv_terminal, p.enterprise_value,
                        -p.net_debt, p.equity_value)],
            "Share of enterprise value": [
                T.pct(p.pv_explicit / p.enterprise_value),
                T.pct(p.pv_terminal / p.enterprise_value),
                "100.0%", "", ""],
        })
        st.dataframe(bridge, hide_index=True, **STRETCH)
        st.markdown(
            f'<p class="note">Equity value of {T.money(p.equity_value, cur)} '
            f'over {c.shares_out / 1e7:,.1f} crore shares gives '
            f'{T.per_share(p.value_per_share, cur)} a share.</p>',
            unsafe_allow_html=True)

    # ------------------------------ Sensitivity -----------------------------
    with tab["Sensitivity"]:
        st.markdown(ui.section(
            "Where the answer is fragile",
            "WACC and terminal growth decide most of a DCF, because both act "
            "on the terminal value. Teal is upside to today's price, rust is "
            "downside. If the sign flips inside this grid, the verdict is a "
            "function of your discount rate rather than of the business."
        ), unsafe_allow_html=True)
        st.plotly_chart(
            charts.sensitivity_heatmap(
                cached_grid(token, a.key(), 7, payload), c.price, cur),
            config=T.CHART_CONFIG, **STRETCH)

        st.markdown(ui.section("Which assumption carries the most weight"),
                    unsafe_allow_html=True)
        tor = tornado(c, a)
        st.plotly_chart(charts.tornado_chart(tor, c.price, cur),
                        config=T.CHART_CONFIG, **STRETCH)
        if tor:
            top = tor[0]
            st.markdown(
                f'<p class="note">Moving {top["label"].lower()} by '
                f'{charts.delta_label(top)} changes the value by '
                f'{T.per_share(top["swing"], cur)} a share, which is '
                f'{T.pct(top["pct_swing"])} of it. That is where the research '
                f'time belongs; the rest is rounding by comparison.</p>',
                unsafe_allow_html=True)

    # --------------------------------- Risk ---------------------------------
    with tab["Risk"]:
        st.markdown(ui.section(
            "The range, not the point",
            f"{mc['n']:,} runs of the same model, drawing growth, margin and "
            "WACC from normal distributions around your assumptions. A single "
            "fair value hides how wide the plausible band really is."
        ), unsafe_allow_html=True)
        st.plotly_chart(
            charts.mc_distribution({**mc, "values": np.array(mc["values"]),
                                    "percentiles": pcts},
                                   c.price, cur, p.value_per_share),
            config=T.CHART_CONFIG, **STRETCH)

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
            'here. In reality a demand shock and a margin shock tend to '
            'arrive together, so the true distribution has fatter tails than '
            'this one. Read the band as a floor on the uncertainty, not a '
            'ceiling.</p>', unsafe_allow_html=True)

        st.markdown(ui.section("Assumption checks"), unsafe_allow_html=True)
        st.markdown(ui.flag_block(flags), unsafe_allow_html=True)

    # ---------------------------- Business quality --------------------------
    with tab["Business quality"]:
        st.markdown(ui.section(
            "Does the business earn its cost of capital?",
            "A DCF is only worth running on a business whose returns exceed "
            "what funding it costs. These are the checks that decide whether "
            "growth is worth paying for at all."
        ), unsafe_allow_html=True)
        st.markdown(ui.metric_block(quality_metrics(c, a, p, w), cur),
                    unsafe_allow_html=True)

        st.markdown(ui.section("Is the valuation believable?"),
                    unsafe_allow_html=True)
        st.markdown(ui.metric_block(valuation_metrics(c, a, p, w), cur),
                    unsafe_allow_html=True)
        st.caption("The reported record of revenue and margins is on the "
                   "Overview tab.")

# --------------------------------- Audit -----------------------------------
with tab["Audit"]:
    st.markdown(ui.section(
        "Where every number came from",
        "Nothing in this model is a guess by a language model. Each baseline "
        "is computed from the company's reported financials by a named rule, "
        "and the rule is printed here."
    ), unsafe_allow_html=True)
    lineage = {
        "financials": "Annual income statement, balance sheet and cash flow "
                      "from Yahoo Finance. Operating margin uses the "
                      "'Operating Income' line.",
        "peers": "Peer set from Yahoo Finance's screener: same exchange, same "
                 "industry, nearest by market value. Editable on the "
                 "Relative value tab.",
        "segments": "Segment revenue is transcribed from company filings "
                    "(Yahoo has none). Each entry names its source and period "
                    "on the Segments tab.",
    }
    st.markdown(ui.provenance_block({**lineage, **prov}),
                unsafe_allow_html=True)

    st.markdown(ui.section("The WACC build"), unsafe_allow_html=True)
    st.dataframe(pd.DataFrame({
        "Input": [f"Risk-free rate, {mkt.rf_label}", "Equity risk premium",
                  "Beta", "Cost of equity, risk-free + beta x premium",
                  "Cost of debt", "Tax rate", "Weight of equity",
                  "Weight of debt", "WACC"],
        "Value": [T.pct(w.risk_free, 2), T.pct(w.equity_risk_premium, 2),
                  f"{w.beta:.2f}  ({w.beta_label})", T.pct(w.cost_of_equity, 2),
                  T.pct(w.cost_of_debt, 2), T.pct(w.tax_rate, 1),
                  T.pct(w.weight_equity, 1), T.pct(w.weight_debt, 1),
                  T.pct(w.wacc, 2)],
    }), hide_index=True, **STRETCH)
    for n in w.notes:
        st.caption(n)

    if dcf_on:
        st.markdown(ui.section("The full projection"), unsafe_allow_html=True)
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
        }), hide_index=True, **STRETCH)

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
    for label, series in (("Operating income", c.ebit),
                          ("Net income", c.net_income),
                          ("Free cash flow", c.fcf), ("Capex", c.capex)):
        by_year = dict(zip(series.years, series.values))
        hist[f"{label} ({unit})"] = [
            round(by_year[y] / div) if y in by_year else None
            for y in c.revenue.years]
    st.dataframe(hist, hide_index=True, **STRETCH)

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
        'growth rate that makes the model print today\'s market price. Beta is '
        'the slope of a regression of the stock\'s weekly returns on its local '
        'index, so it differs for every company.'
        '</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="note" style="color:var(--ink-faint)">'
        'Built for a business analytics course. Educational use only, not '
        'investment advice. Financial data comes from Yahoo Finance, which is '
        'unofficial and sometimes wrong, so the Audit tab exists to let you '
        'check it against the filings.</p>', unsafe_allow_html=True)
