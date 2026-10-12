"""The Overview, Segments and Relative value tabs.

Everything that produces a number is a plain function (`kpi_groups`,
`statement_table`, `comparison_table`, `valuation_reading`, ...) so it can be
tested without a browser. The `*_tab` functions only lay those results out.
"""

from __future__ import annotations

import html
import statistics

import pandas as pd
import streamlit as st

from . import beta as beta_mod
from . import charts, components as ui, peers as P, segments as S
from . import theme as T
from .data import Company

STRETCH = {"width": "stretch"}


# ==========================================================================
# Overview
# ==========================================================================

def _change_over(history: dict, weeks: int) -> float | None:
    close = (history or {}).get("close") or []
    if len(close) <= weeks or not close[-weeks - 1]:
        return None
    return close[-1] / close[-weeks - 1] - 1


def _latest(row: list | None) -> float | None:
    return next((v for v in (row or []) if v is not None), None)


def kpi_groups(c: Company, w, financial: bool = False
               ) -> list[tuple[str, list[dict]]]:
    """The figures a reader wants first, grouped by the question they answer.

    `financial` marks banks and lenders, where enterprise-value multiples and
    EBITDA mean nothing and are shown as n/m instead of being invented.
    """
    s = c.stats or {}
    cur = c.currency
    income = (c.statements or {}).get("income", {}).get("rows", {})
    ebitda = s.get("ebitda")
    ev = None if financial else s.get("ev")

    hi, lo = s.get("high_52w"), s.get("low_52w")
    pos = ((c.price - lo) / (hi - lo)
           if hi and lo and hi > lo else None)
    one_year = _change_over(c.price_history, 52)

    shares_cr = c.shares_out / 1e7
    shares_txt = (f"{shares_cr:,.0f} crore shares" if cur == "INR"
                  else f"{c.shares_out / 1e6:,.0f} million shares")

    market = [
        {"label": "Share price", "value": T.per_share(c.price, cur),
         "sub": (f"{one_year:+.1%} over one year" if one_year is not None
                 else ""),
         "tone": ("up" if one_year and one_year > 0 else
                  "dn" if one_year and one_year < 0 else "")},
        {"label": "Market value", "value": T.money(c.market_cap, cur),
         "sub": shares_txt},
        {"label": "Enterprise value",
         "value": T.money(ev, cur) if ev else "n/m",
         "sub": "market value plus net debt" if ev else
         "not meaningful for a lender"},
        {"label": "52-week range",
         "value": (f"{T.per_share(lo, cur)} to {T.per_share(hi, cur)}"
                   if hi and lo else "n/a"),
         "sub": (f"{pos:.0%} of the way up the range" if pos is not None
                 else ""), "marker": pos},
        {"label": "Dividend yield", "value": T.pct(s.get("dividend_yield"), 2),
         "sub": (f"{s['payout_ratio']:.0%} of earnings paid out"
                 if s.get("payout_ratio") else "")},
        {"label": "Beta", "value": f"{w.beta:.2f}",
         "sub": w.beta_label or "company beta"},
    ]

    valuation = [
        {"label": "P/E, trailing", "value": T.multiple(s.get("pe")),
         "sub": "price over the last year's earnings"},
        {"label": "P/E, forward", "value": T.multiple(s.get("fwd_pe")),
         "sub": "price over analysts' next-year earnings"},
        {"label": "Price to book", "value": T.multiple(s.get("pb")),
         "sub": "price over book value per share"},
        {"label": "EV / EBITDA",
         "value": T.multiple(None if financial else s.get("ev_ebitda")),
         "sub": "not meaningful for a lender" if financial else
         "enterprise value over operating cash profit"},
        {"label": "EV / Sales",
         "value": T.multiple(None if financial else s.get("ev_sales")),
         "sub": "not meaningful for a lender" if financial else
         "enterprise value over revenue"},
    ]

    rev = c.revenue
    margin = c.latest_margin()
    ni, rv = c.net_income.latest, rev.latest
    net_margin = ni / rv if ni is not None and rv else s.get("net_margin")
    roe = s.get("roe")
    if roe is None and ni is not None and c.equity_book and c.equity_book > 0:
        roe = ni / c.equity_book
    roic = None if financial else c.roic()
    yoy = rev.yoy()
    cagr = rev.cagr()

    quality = [
        {"label": "Operating margin",
         "value": T.pct(margin) if margin is not None else "n/m",
         "sub": (f"fiscal {c.ebit.years[0]}" if margin is not None and
                 c.ebit.years else "no operating income reported")},
        {"label": "Net margin", "value": T.pct(net_margin),
         "sub": f"fiscal {c.net_income.years[0]}" if c.net_income.years else ""},
        {"label": "Return on equity", "value": T.pct(roe),
         "sub": "profit over shareholders' funds"},
        {"label": "Return on invested capital",
         "value": T.pct(roic) if roic is not None else "n/m",
         "sub": (f"against a WACC of {T.pct(w.wacc)}" if roic is not None
                 else "invested capital is not defined for a lender"),
         "tone": ("up" if roic is not None and roic > w.wacc else
                  "dn" if roic is not None else "")},
        {"label": "Revenue growth, latest year",
         "value": T.pct(yoy[0], 1, signed=True) if yoy else "n/a",
         "sub": f"fiscal {rev.years[0]} over {rev.years[1]}"
         if len(rev.years) > 1 else ""},
        {"label": f"Revenue CAGR, {len(rev.values) - 1} years",
         "value": T.pct(cagr, 1, signed=True) if cagr is not None else "n/a",
         "sub": f"fiscal {rev.years[-1]} to {rev.years[0]}"
         if len(rev.years) > 1 else ""},
    ]

    cash, debt = c.cash or 0.0, c.total_debt or 0.0
    nd_ebitda = ((debt - cash) / ebitda
                 if ebitda and ebitda > 0 and not financial else None)
    ca = _latest((c.statements or {}).get("balance", {}).get("rows", {})
                 .get("Current assets"))
    cl = _latest((c.statements or {}).get("balance", {}).get("rows", {})
                 .get("Current liabilities"))
    current = s.get("current_ratio") or (ca / cl if ca and cl else None)
    fcf = s.get("fcf") or c.fcf.latest
    fcf_yield = fcf / c.market_cap if fcf and c.market_cap else None
    conv = c.fcf_conversion()
    de = s.get("debt_to_equity")
    if de is None and c.equity_book and c.equity_book > 0:
        de = debt / c.equity_book

    balance = [
        {"label": "Net debt / EBITDA",
         "value": T.multiple(nd_ebitda) if nd_ebitda is not None else "n/m",
         "sub": ("net cash, more cash than debt" if nd_ebitda is not None
                 and nd_ebitda < 0 else "years of EBITDA to repay net debt")},
        {"label": "Debt to equity",
         "value": f"{de:.2f}" if de is not None else "n/m",
         "sub": "total debt over book equity"},
        {"label": "Current ratio",
         "value": f"{current:.2f}" if current else "n/a",
         "sub": "current assets over current liabilities"},
        {"label": "FCF conversion", "value": T.pct(conv, 0),
         "sub": "free cash flow over net income"},
        {"label": "FCF yield", "value": T.pct(fcf_yield),
         "sub": "free cash flow over market value"},
        {"label": "Net cash per share",
         "value": (T.per_share(c.net_cash_per_share(), cur)
                   if c.net_cash_per_share() is not None else "n/a"),
         "sub": "cash less debt, per share"},
    ]
    return [("The market", market), ("What it is priced at", valuation),
            ("How well the business earns", quality),
            ("Balance sheet and cash", balance)]


def statement_table(c: Company, kind: str
                    ) -> tuple[list[str], list[list[str]], list[str]] | None:
    """(headers, rows, row classes) for one statement, newest year first."""
    st_ = (c.statements or {}).get(kind) or {}
    years, rows = st_.get("years"), st_.get("rows")
    if not years or not rows:
        return None
    cur = c.currency
    headers = ["", *[f"FY{y}" for y in years]]
    out: list[list[str]] = []
    classes: list[str] = []
    for label, vals in rows.items():
        if label in P_PER_SHARE:
            out.append([label, *[
                f"{T.symbol(cur)}{v:,.2f}" if v is not None else "n/a"
                for v in vals]])
        else:
            out.append([label, *[T.amount(v, cur) if v is not None else "n/a"
                                 for v in vals]])
        classes.append("")

    if kind == "income":
        rev = rows.get("Revenue")
        if rev:
            growth = []
            for i, v in enumerate(rev):
                nxt = rev[i + 1] if i + 1 < len(rev) else None
                growth.append(f"{v / nxt - 1:+.1%}" if v and nxt else "")
            out.append(["Revenue growth", *growth])
            classes.append("sub")
            for label, key in (("Operating margin", "Operating income"),
                               ("Net margin", "Net income")):
                num = rows.get(key)
                if num:
                    out.append([label, *[f"{n / r:.1%}" if n is not None
                                         and r else "" for n, r in
                                         zip(num, rev)]])
                    classes.append("sub")
    return headers, out, classes


P_PER_SHARE = {"Diluted EPS"}


def beta_table(c: Company, w) -> tuple[list[str], list[list[str]], list[str]]:
    b = c.beta_info or {}
    rows: list[list[str]] = []
    classes: list[str] = []
    if b.get("raw") is not None:
        rows.append([f"Regression, {b['years']}-year {b['frequency']} vs "
                     f"{b['benchmark_name']}", f"{b['raw']:.2f}",
                     f"R-squared {b['r2']:.2f}, {b['n']} observations"])
        classes.append("")
        rows.append(["95% range of that estimate",
                     f"{b['ci_low']:.2f} to {b['ci_high']:.2f}",
                     f"standard error {b['se']:.2f}"])
        classes.append("sub")
        rows.append(["Blume-adjusted (two-thirds raw, one-third 1.0)",
                     f"{b['adjusted']:.2f}",
                     "pulls extreme readings toward the market average"])
        classes.append("")
    if b.get("yahoo") is not None:
        rows.append(["Yahoo Finance's reported beta", f"{b['yahoo']:.2f}",
                     "shown for comparison; Yahoo's figure is unreliable "
                     "for Indian listings" if c.market.key == "IN"
                     else "shown for comparison"])
        classes.append("")
    rows.append(["Used in the WACC", f"{w.beta:.2f}", w.beta_label or ""])
    classes.append("agg")
    return ["Estimate", "Beta", "Note"], rows, classes


def overview_tab(c: Company, w, financial: bool = False) -> None:
    prof = c.profile or {}

    st.markdown(ui.section("The business"), unsafe_allow_html=True)
    summary = prof.get("summary") or ""
    if summary:
        short = summary if len(summary) < 430 else summary[:430].rsplit(" ", 1)[0] + "..."
        st.markdown(f'<p class="about">{html.escape(short)}</p>',
                    unsafe_allow_html=True)
        if len(summary) >= 430:
            with st.expander("Read the full description"):
                st.markdown(f'<p class="about">{html.escape(summary)}</p>',
                            unsafe_allow_html=True)
    bits = [b for b in (
        c.sector if c.sector != "Unclassified" else "", c.industry,
        f"{prof['employees']:,} employees" if prof.get("employees") else "",
        prof.get("location"), prof.get("exchange")) if b]
    site = prof.get("website")
    facts = " &nbsp;·&nbsp; ".join(html.escape(b) for b in bits)
    if site and site.startswith(("http://", "https://")):
        facts += (' &nbsp;·&nbsp; <a href="' + html.escape(site, quote=True)
                  + '" target="_blank" rel="noopener noreferrer">'
                  + html.escape(site.split("//", 1)[1].rstrip("/")) + "</a>")
    if facts:
        st.markdown(f'<p class="facts">{facts}</p>', unsafe_allow_html=True)

    st.markdown(ui.section(
        "Key figures",
        "Drawn from Yahoo Finance's latest statements and quote. Ratios that "
        "mix a price with a statement are rebuilt here after currency "
        "translation, because Yahoo's own versions go wrong when the two "
        "currencies differ."), unsafe_allow_html=True)
    for title, items in kpi_groups(c, w, financial):
        st.markdown(f'<div class="kgroup">{html.escape(title)}</div>',
                    unsafe_allow_html=True)
        st.markdown(ui.kpi_grid(items), unsafe_allow_html=True)

    st.markdown(ui.section("The share price"), unsafe_allow_html=True)
    fig = charts.price_chart(c)
    if fig is not None:
        st.plotly_chart(fig, config=T.CHART_CONFIG, **STRETCH)
    else:
        st.caption("No price history is stored for this company.")

    st.markdown(ui.section(
        "Financial snapshot",
        f"Annual statements, newest year first, in "
        f"{T.stmt_unit(c.currency)[1]}."
        + (f" Reported in {c.financial_currency} and translated at "
           f"{c.fx_rate:,.2f}." if c.fx_rate != 1.0 else "")),
        unsafe_allow_html=True)
    any_table = False
    for kind, title in (("income", "Income statement"),
                        ("balance", "Balance sheet"),
                        ("cashflow", "Cash flow")):
        t = statement_table(c, kind)
        if t is None:
            continue
        any_table = True
        st.markdown(f'<div class="kgroup">{title}</div>',
                    unsafe_allow_html=True)
        st.markdown(ui.html_table(t[0], t[1], t[2]), unsafe_allow_html=True)
    if not any_table:
        st.caption("This saved copy was written before the financial "
                   "snapshot existed. Reload the company with a connection "
                   "to fill it in.")
    st.plotly_chart(charts.history_bars(c), config=T.CHART_CONFIG, **STRETCH)

    st.markdown(ui.section(
        "Where the beta comes from",
        "Yahoo's own beta is not usable for Indian listings, so beta is "
        "measured here: a regression of the stock's weekly returns on its "
        "local index. The slope of the fitted line below is the beta."),
        unsafe_allow_html=True)
    h, r, k = beta_table(c, w)
    st.markdown(ui.html_table(h, r, k, left_cols=(2,)), unsafe_allow_html=True)
    note = beta_mod.quality_note(c.beta_info)
    if note:
        st.markdown(f'<p class="note">{html.escape(note)}</p>',
                    unsafe_allow_html=True)
    bfig = charts.beta_scatter(c)
    if bfig is not None:
        st.plotly_chart(bfig, config=T.CHART_CONFIG, **STRETCH)


# ==========================================================================
# Segments
# ==========================================================================

def fmt_amount(v: float, unit: str) -> str:
    u = (unit or "").lower()
    if "inr" in u and "crore" in u:
        return f"₹{T.indian_group(v, 0)} cr"
    if "usd" in u and "million" in u:
        return f"${v:,.0f}m"
    return f"{v:,.0f}"


def colour_map(view: dict) -> dict[str, str]:
    """Segment -> colour, fixed by reported order.

    Up to six segments get their own colour. Beyond that the first five do
    and the rest share the neutral grey, because a donut of eight slices
    stops being readable (they are all still listed in the table).
    """
    names = S.colour_order(view)
    n_own = len(names) if len(names) <= len(T.SEGMENT_COLOURS) else \
        len(T.SEGMENT_COLOURS) - 1
    return {n: (T.SEGMENT_COLOURS[i] if i < n_own else T.OTHER_COLOUR)
            for i, n in enumerate(names)}


def donut_groups(values: dict[str, float], view: dict
                 ) -> tuple[dict[str, float], dict[str, str]]:
    """Fold segments without their own colour into one 'Other segments'."""
    cmap = colour_map(view)
    groups: dict[str, float] = {}
    for name in S.colour_order(view):
        if name not in values:
            continue
        key = name if cmap[name] != T.OTHER_COLOUR else "Other segments"
        groups[key] = groups.get(key, 0.0) + values[name]
    colours = {k: cmap.get(k, T.OTHER_COLOUR) for k in groups}
    colours["Other segments"] = T.OTHER_COLOUR
    return groups, colours


def _plain(v: float) -> str:
    """Whole numbers without decimals, otherwise one decimal."""
    return f"{v:,.0f}" if abs(v - round(v)) < 0.05 else f"{v:,.1f}"


def segment_table(view: dict, period: dict, prior: dict | None
                  ) -> tuple[list[str], list[list[str]], list[list[str]]]:
    """(headers, rows, per-cell classes). The last row is the total."""
    kind, unit = view["kind"], view.get("unit", "")
    vals = period["values"]
    sh = S.shares(vals)
    psh = S.shares(prior["values"]) if prior else {}
    headers = ["Segment"]
    if kind == "amount":
        headers.append(f"Revenue ({unit})")
    headers.append(f"Share, {period['label']}")
    if prior:
        headers += [f"Share, {prior['label']}", "Change"]
    rows: list[list[str]] = []
    cells: list[list[str]] = []
    for name in S.colour_order(view):
        if name not in vals:
            continue
        row = [name]
        if kind == "amount":
            row.append(_plain(vals[name]))
        row.append(f"{sh[name]:.1%}")
        c_row = [""] * len(row)
        if prior:
            old = psh.get(name)
            if old is None:
                row += ["n/a", "new"]
                c_row += ["dim", "dim"]
            else:
                d = (sh[name] - old) * 100
                row += [f"{old:.1%}", T.points(d)]
                c_row += ["dim", "pos" if d > 0.05 else
                          "neg" if d < -0.05 else "dim"]
        rows.append(row)
        cells.append(c_row)
    total = ["Total"]
    if kind == "amount":
        total.append(_plain(sum(vals.values())))
    total.append("100.0%")
    if prior:
        total += ["100.0%", ""]
    rows.append(total)
    cells.append([""] * len(total))
    return headers, rows, cells


def segments_tab(c: Company) -> None:
    st.markdown(ui.section(
        "Where the revenue comes from",
        "Segment revenue as the company itself reports it. Yahoo Finance "
        "publishes no segment data, so these figures are transcribed from "
        "filings, each with its source and period."), unsafe_allow_html=True)

    entry = S.get_segments(c.ticker)
    views = list(entry["views"]) if entry else []
    user = st.session_state.get("seg_user", {}).get(c.ticker)
    if user:
        views.append(user)

    if not views:
        st.info("No segment data is stored for " + c.ticker + ". Add it "
                "below from the segment note in the company's annual report "
                "and the charts appear. Stored so far: "
                + ", ".join(S.covered_tickers()) + ".", icon="ℹ️")
    else:
        titles = [v["title"] for v in views]
        view = views[0]
        if len(views) > 1:
            pick = st.radio("Split by", titles, horizontal=True,
                            key=f"seg_view_{c.ticker}")
            view = views[titles.index(pick)]
        periods = view["periods"]
        period = periods[0]
        if len(periods) > 1:
            labels = [p["label"] for p in periods]
            sel = st.radio("Period", labels, horizontal=True,
                           key=f"seg_period_{c.ticker}_{view['title']}")
            period = periods[labels.index(sel)]
        idx = periods.index(period)
        prior = periods[idx + 1] if idx + 1 < len(periods) else None

        problems = S.check_view(view)
        if problems:
            st.warning("These figures do not add up to the stated total: "
                       + "; ".join(problems))

        vals = period["values"]
        sh = S.shares(vals)
        groups, colours = donut_groups(
            sh if view["kind"] == "share" else vals, view)
        centre = (period["label"] if view["kind"] == "share" else
                  fmt_amount(sum(vals.values()), view.get("unit", "")))
        left, right = st.columns([5, 6], gap="large")
        with left:
            st.plotly_chart(charts.segment_donut(groups, colours, centre),
                            config=T.CHART_CONFIG, **STRETCH)
        with right:
            names = S.colour_order(view)
            names = [n for n in names if n in vals]
            bar_vals = [sh[n] * 100 for n in names]
            if view["kind"] == "amount":
                labels = [f"{fmt_amount(vals[n], view['unit'])}  ·  {sh[n]:.0%}"
                          for n in names]
            else:
                labels = [f"{vals[n]:.1f}%" for n in names]
            st.plotly_chart(charts.segment_bars(names, bar_vals, labels),
                            config=T.CHART_CONFIG, **STRETCH)

        if prior and len(periods) > 1:
            rows = S.mix_shift({"periods": [period, prior]} | {
                "title": view["title"]})
            if rows:
                st.markdown(ui.section(
                    f"How the mix moved, {prior['label']} to {period['label']}",
                    "Each segment's share of revenue then and now. Growth in "
                    "a segment that is already large shifts the mix less "
                    "than the same growth in a small one."),
                    unsafe_allow_html=True)
                st.plotly_chart(
                    charts.segment_shift(rows, prior["label"], period["label"]),
                    config=T.CHART_CONFIG, **STRETCH)

        st.markdown(ui.section("The figures"), unsafe_allow_html=True)
        h, rws, cell = segment_table(view, period, prior)
        st.markdown(ui.html_table(h, rws, [""] * (len(rws) - 1) + ["agg"],
                                  cell_classes=cell),
                    unsafe_allow_html=True)
        detail = f" ({period['detail']})" if period.get("detail") else ""
        st.markdown(ui.source_line(
            f"{view['source']}{detail}.", view.get("source_url", "")),
            unsafe_allow_html=True)
        if view.get("note"):
            st.markdown(f'<p class="note">{html.escape(view["note"])}</p>',
                        unsafe_allow_html=True)

    with st.expander("Add or replace segment data from an annual report"):
        st.caption(
            "Type the segments and their revenue from the filing's segment "
            "note. Use one unit throughout. The data lasts for this session.")
        unit = st.text_input("Unit", value="INR crore",
                             key=f"seg_unit_{c.ticker}")
        base = pd.DataFrame({"Segment": ["", "", "", "", "", ""],
                             "Revenue": [None] * 6})
        edited = st.data_editor(base, num_rows="dynamic", hide_index=True,
                                key=f"seg_edit_{c.ticker}", **STRETCH)
        if st.button("Show these segments", key=f"seg_go_{c.ticker}"):
            v = S.view_from_rows(
                "Your entry", list(zip(edited["Segment"], edited["Revenue"])),
                unit)
            if v is None:
                st.error("Enter at least two segments with a positive revenue.")
            else:
                st.session_state.setdefault("seg_user", {})[c.ticker] = v
                st.rerun()


# ==========================================================================
# Relative value
# ==========================================================================

_SUFFIXES = {"LTD", "LTD.", "LIMITED", "LT", "INC", "INC.", "CORP", "CORP.",
             "CO", "CO."}


def nice_name(name: str) -> str:
    """Yahoo's Indian short names arrive in capitals and abbreviated
    ('TATA CONSULTANCY SERV LT'). Make them readable and short enough that
    a table row stays on one line. Mixed-case names are left alone."""
    if not name or not name.isupper():
        return name
    words = name.split()
    while len(words) > 1 and words[-1] in _SUFFIXES:
        words.pop()
    small = {"OF", "AND", "THE", "FOR", "IN", "ON", "&"}
    return " ".join(
        w.lower() if w in small and i else w if len(w) <= 3 else w.capitalize()
        for i, w in enumerate(words))


def comparison_table(c: Company, rows: list[dict], summary: dict,
                     skip_ev: bool) -> tuple[list[str], list[list[str]],
                                             list[str]]:
    """The peer table: the company first, peers by size, then the median."""
    keys = [k for k, *_ in P.MULTIPLES if not (skip_ev and k in P.EV_KEYS)]
    label = {k: l for k, l, _ in P.MULTIPLES}
    headers = (["Company", "Market value"] + [label[k] for k in keys]
               + ["ROE", "Op. margin", "Revenue growth", "Div. yield"])
    cur = c.currency

    def line(r: dict, name: str | None = None) -> list[str]:
        return ([name or nice_name(r["name"]),
                 T.money(r.get("market_cap"), cur)]
                + [T.multiple(P._valid(k, r.get(k))) for k in keys]
                + [T.pct(r.get("roe")), T.pct(r.get("op_margin")),
                   T.pct(r.get("rev_growth"), 1, signed=True),
                   T.pct(r.get("dividend_yield"), 1)])

    me = P.self_row(c)
    out = [line(me, c.name)]
    cls = ["me"]
    for r in sorted(rows, key=lambda r: r.get("market_cap") or 0, reverse=True):
        out.append(line(r))
        cls.append("")

    med = ["Peer median", ""]
    prem = [f"{c.ticker} vs peer median", ""]
    for k in keys:
        m = (summary.get(k) or {}).get("median")
        med.append(T.multiple(m))
        pr = P.premium(P._valid(k, me.get(k)), m)
        prem.append(f"{pr:+.0%}" if pr is not None else "n/m")
    for key in ("roe", "op_margin", "rev_growth", "dividend_yield"):
        vals = [r.get(key) for r in rows if r.get(key) is not None]
        mv = statistics.median(vals) if len(vals) >= P.MIN_PEERS_FOR_STATS else None
        med.append(T.pct(mv, 1, signed=(key == "rev_growth")))
        own = me.get(key)
        prem.append(T.points((own - mv) * 100)
                    if own is not None and mv is not None else "n/m")
    out += [med, prem]
    cls += ["agg", "sub"]
    return headers, out, cls


def implied_table(c: Company, implied: list[dict]
                  ) -> tuple[list[str], list[list[str]], list[list[str]]]:
    cur = c.currency
    headers = ["Method", "Peer median", f"{c.ticker} today",
               "Implied value per share", "Peer quartile range",
               "Against today's price"]
    rows, cells = [], []
    for iv in implied:
        rows.append([
            iv["label"], T.multiple(iv["peer_median"]), T.multiple(iv["own"]),
            T.per_share(iv["mid"], cur),
            f"{T.per_share(iv['low'], cur)} to {T.per_share(iv['high'], cur)}",
            f"{iv['vs_price']:+.0%}"])
        cells.append(["", "", "", "", "",
                      "pos" if iv["vs_price"] > 0 else "neg"])
    return headers, rows, cells


def football_rows(c: Company, implied: list[dict], dcf: dict | None
                  ) -> list[dict]:
    """Every method's low/mid/high for one share, ready for the chart."""
    s = c.stats or {}
    rows: list[dict] = []
    if dcf:
        rows.append({"label": "Your DCF, 5th to 95th percentile",
                     "low": dcf["p5"], "mid": dcf["point"], "high": dcf["p95"],
                     "group": "dcf"})
    lo, hi = s.get("target_low"), s.get("target_high")
    if lo and hi:
        rows.append({"label": "Analyst targets", "low": lo, "high": hi,
                     "mid": s.get("target_mean"), "group": "consensus"})
    for iv in implied:
        rows.append({"label": f"Peer {iv['label']}", "low": iv["low"],
                     "mid": iv["mid"], "high": iv["high"], "group": "relative"})
    if s.get("low_52w") and s.get("high_52w"):
        rows.append({"label": "52-week trading range", "low": s["low_52w"],
                     "high": s["high_52w"], "mid": None, "group": "market"})
    return rows


def valuation_reading(c: Company, implied: list[dict], dcf: dict | None
                      ) -> str:
    """One paragraph putting the peer view next to the DCF and the price."""
    cur = c.currency
    if not implied:
        return ""
    mids = [iv["mid"] for iv in implied]
    rel = statistics.median(mids)
    gap = rel / c.price - 1
    text = (f"Taken together, the peer multiples value {c.name} at about "
            f"{T.per_share(rel, cur)} a share, which is {abs(gap):.0%} "
            f"{'above' if gap >= 0 else 'below'} today's "
            f"{T.per_share(c.price, cur)}. ")
    if dcf:
        d_gap = dcf["point"] / c.price - 1
        agree = (gap >= 0) == (d_gap >= 0)
        text += (f"Your DCF says {T.per_share(dcf['point'], cur)}, "
                 f"{abs(d_gap):.0%} {'above' if d_gap >= 0 else 'below'} the "
                 "price. ")
        text += ("The two methods lean the same way, which is mild "
                 "corroboration, though both can be wrong together."
                 if agree else
                 "The two methods disagree on direction. Either the peers "
                 "are priced richly or cheaply for reasons that do not apply "
                 "here, or the DCF assumptions are stricter or looser than "
                 "the market's. Finding out which is the actual analysis.")
    return text


def relative_tab(c: Company, load_peers, dcf: dict | None,
                 skip_ev: bool) -> None:
    st.markdown(ui.section(
        "What similar companies are priced at",
        "A DCF values the business on your assumptions. Peer multiples ask "
        "what the market pays for comparable businesses today. Where the two "
        "disagree is where the argument is."), unsafe_allow_html=True)
    if skip_ev:
        st.info(
            "This is a financial company, so enterprise-value multiples "
            "(EV/EBITDA, EV/Sales) are left out. Price to earnings and price "
            "to book are the right yardsticks for a lender.", icon="ℹ️")

    typed = st.text_input(
        "Peer set",
        key=f"peer_in_{c.ticker}",
        placeholder="Leave blank for Yahoo's suggested peers, or type symbols "
                    "such as TCS.NS, HCLTECH.NS, WIPRO.NS",
        help="Comma-separated Yahoo Finance symbols. Blank uses the "
             "automatic peer set.")
    custom = tuple(s.strip().upper() for s in typed.split(",") if s.strip())

    with st.spinner("Pulling peer multiples from Yahoo Finance"):
        peers = load_peers(c.ticker, custom)
    rows = peers.get("rows") or []
    if not rows:
        st.warning(
            "No peers could be loaded. Yahoo may be unreachable, or its "
            "screener found no comparable companies. Type a few symbols "
            "above to build the set yourself.")
        return
    if peers.get("source") == "snapshot":
        st.caption("Showing the peer set saved with this company's snapshot.")
    st.markdown(f'<p class="src">{html.escape(peers.get("method", ""))}</p>',
                unsafe_allow_html=True)

    summary = P.summarize(rows)
    h, r, k = comparison_table(c, rows, summary, skip_ev)
    st.markdown(ui.html_table(h, r, k), unsafe_allow_html=True)
    st.markdown(
        '<p class="tbl-cap">Multiples use trailing twelve months where Yahoo '
        'has them. A blank "n/m" means not meaningful: the denominator is '
        'negative or the ratio is beyond any sensible range. The median is '
        'used rather than the mean so one extreme peer cannot drag it.</p>',
        unsafe_allow_html=True)

    implied = P.implied_values(c, summary, skip_ev=skip_ev)
    if implied:
        st.markdown(ui.section(
            "What the peer multiples imply for one share",
            "Apply each peer median to this company's own earnings, book "
            "value, EBITDA or revenue. The range runs from the peers' lower "
            "to upper quartile, so it shows how much the peers disagree."),
            unsafe_allow_html=True)
        h, r, cells = implied_table(c, implied)
        st.markdown(ui.html_table(h, r, cell_classes=cells),
                    unsafe_allow_html=True)

        st.markdown(ui.section(
            "Every method on one price axis",
            "Teal is your DCF, ochre the analysts' target range, grey the "
            "peer multiples and the trading range. The diamond marks each "
            "method's central value."), unsafe_allow_html=True)
        st.plotly_chart(
            charts.football_field(football_rows(c, implied, dcf), c.price,
                                  c.currency),
            config=T.CHART_CONFIG, **STRETCH)
        reading = valuation_reading(c, implied, dcf)
        if reading:
            st.markdown(f'<p class="note">{html.escape(reading)}</p>',
                        unsafe_allow_html=True)
    else:
        st.caption("Too few peers have usable multiples to build an implied "
                   "value. Add more symbols above.")

    pick_opts = [(k, l) for k, l, _ in P.MULTIPLES
                 if not (skip_ev and k in P.EV_KEYS)]
    st.markdown(ui.section("One multiple across the peers"),
                unsafe_allow_html=True)
    choice = st.radio("Multiple", [l for _, l in pick_opts], horizontal=True,
                      key=f"peer_mult_{c.ticker}", label_visibility="collapsed")
    key = next(k for k, l in pick_opts if l == choice)
    st.plotly_chart(
        charts.peer_bars([P.self_row(c)] + rows, key, choice, c.ticker,
                         (summary.get(key) or {}).get("median")),
        config=T.CHART_CONFIG, **STRETCH)
    st.markdown(
        '<p class="note">Peers are matched on industry and size, not on '
        'business model, fiscal year or growth. A premium to the peer median '
        'is only a finding if the company is not simply growing faster or '
        'earning more on its capital, which the ROE, margin and growth '
        'columns above let you check.</p>', unsafe_allow_html=True)
