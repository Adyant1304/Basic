"""Visual system: one palette, two typefaces, one chart template.

Colour carries information here rather than decorating. Three cases run
through every surface in the app — the chart, the hero, the tables — and
each keeps its own colour everywhere:

    market      slate     where the price is now, a fact
    yours       teal      the case you authored
    consensus   ochre     what the analyst crowd expects

Everything else is paper, ink and rules.
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------
PAPER = "#0F1415"
PAPER_2 = "#161D1F"
PAPER_3 = "#1E2729"
INK = "#E8ECE9"
INK_SOFT = "#A3ADB0"
INK_FAINT = "#6F7B80"
RULE = "#2C3739"

MARKET = "#9AA5A9"
YOURS = "#3FB8A8"
CONSENSUS = "#D9A441"
DOWN = "#E0674A"
GOOD = "#4CC38A"
WATCH = "#D9A441"
POOR = "#E0674A"
STATUS = {"good": GOOD, "watch": WATCH, "poor": POOR, "neutral": INK_SOFT}

FONT_SANS = "'Archivo', 'Helvetica Neue', Arial, sans-serif"
FONT_SERIF = "'Source Serif 4', Georgia, serif"


# --------------------------------------------------------------------------
# Number formatting, Indian conventions
# --------------------------------------------------------------------------

def symbol(currency: str) -> str:
    return {"INR": "₹", "USD": "$", "EUR": "€",
            "GBP": "£", "JPY": "¥"}.get(currency, currency + " ")


def indian_group(n: float, decimals: int = 0) -> str:
    """Group digits 2,2,3 the way Indian financial writing does."""
    neg = n < 0
    s = f"{abs(n):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    out = whole + (f".{frac}" if frac else "")
    return ("-" if neg else "") + out


def money(value: float | None, currency: str = "INR",
          compact: bool = True) -> str:
    """Large sums in crore for rupees, billions otherwise."""
    if value is None:
        return "n/a"
    sym = symbol(currency)
    if not compact:
        return f"{sym}{indian_group(value, 0)}"
    if currency == "INR":
        cr = value / 1e7
        if abs(cr) >= 1e5:
            return f"{sym}{indian_group(cr / 1e5, 2)} lakh cr"
        return f"{sym}{indian_group(cr, 0)} cr"
    for div, suffix in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if abs(value) >= div:
            return f"{sym}{value / div:,.1f}{suffix}"
    return f"{sym}{value:,.0f}"


def per_share(value: float | None, currency: str = "INR") -> str:
    if value is None:
        return "n/a"
    return f"{symbol(currency)}{indian_group(value, 0)}"


def pct(value: float | None, decimals: int = 1, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    s = f"{value * 100:+.{decimals}f}%" if signed else f"{value * 100:.{decimals}f}%"
    return s


# --------------------------------------------------------------------------
# CSS
# --------------------------------------------------------------------------

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400&display=swap');

:root {{
  --paper: {PAPER};
  --paper-2: {PAPER_2};
  --paper-3: {PAPER_3};
  --ink: {INK};
  --ink-soft: {INK_SOFT};
  --ink-faint: {INK_FAINT};
  --rule: {RULE};
  --market: {MARKET};
  --yours: {YOURS};
  --consensus: {CONSENSUS};
  --down: {DOWN};
}}

html, body, .stApp, .stMarkdown, .stMarkdown p, label, button, input, textarea {{
  font-family: {FONT_SANS};
}}
.stApp {{
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1, "cv05" 1;
}}

/* Icons keep Streamlit's own icon font. */
[data-testid="stIconMaterial"],
[data-testid="stExpanderIcon"],
span[class*="material" i] {{
  font-family: "Material Symbols Rounded" !important;
  font-feature-settings: "liga" !important;
  font-variant-numeric: normal !important;
  letter-spacing: normal !important;
}}
.stApp {{ background: var(--paper); color: var(--ink); }}

/* Strip Streamlit's own chrome so the page reads as one designed surface. */
[data-testid="stHeader"] {{ background: transparent; height: 0; }}
[data-testid="stToolbar"] {{ display: none; }}
#MainMenu, footer {{ visibility: hidden; }}
[data-testid="stAppViewBlockContainer"] {{
  padding: 1.25rem 2.25rem 4rem 2.25rem;
  max-width: 1320px;
}}
[data-testid="stSidebar"] {{
  background: var(--paper-2);
  border-right: 1px solid var(--rule);
}}
[data-testid="stSidebarUserContent"] {{ padding-top: 1.5rem; }}

/* ---------------- masthead ---------------- */
.mast {{
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 1rem; border-bottom: 2px solid var(--ink);
  padding-bottom: .55rem; margin-bottom: 1.5rem;
}}
.mast h1 {{
  font-size: 1.32rem; font-weight: 700; letter-spacing: -.021em;
  margin: 0; color: var(--ink);
}}
.mast .tag {{
  font-family: {FONT_SERIF}; font-style: italic;
  font-size: .95rem; color: var(--ink-soft);
}}
.mast .stamp {{
  font-size: .76rem; color: var(--ink-faint); white-space: nowrap;
}}

/* ---------------- company line ---------------- */
.co {{ margin: 0 0 .25rem 0; }}
.co .nm {{
  font-size: 2.05rem; font-weight: 600; letter-spacing: -.028em;
  line-height: 1.1; margin: 0; color: var(--ink);
}}
.co .meta {{
  font-size: .86rem; color: var(--ink-soft); margin-top: .3rem;
}}
.co .meta b {{ font-weight: 500; color: var(--ink); }}

/* ---------------- verdict ---------------- */
.verdict {{
  font-family: {FONT_SERIF}; font-size: 1.07rem; line-height: 1.55;
  color: var(--ink); max-width: 68ch; margin: 1.1rem 0 .2rem 0;
}}
.verdict .big {{
  font-family: {FONT_SANS}; font-weight: 700;
  font-size: 1.16rem; letter-spacing: -.012em;
}}
.up {{ color: var(--yours); }}
.dn {{ color: var(--down); }}

/* ---------------- section headings ---------------- */
.sec {{
  font-size: .97rem; font-weight: 600; letter-spacing: -.006em;
  color: var(--ink); margin: 1.9rem 0 .2rem 0;
  padding-bottom: .34rem; border-bottom: 1px solid var(--rule);
}}
.sec:first-child {{ margin-top: .4rem; }}
.note {{
  font-family: {FONT_SERIF}; font-size: .94rem; line-height: 1.55;
  color: var(--ink-soft); max-width: 70ch; margin: .55rem 0 0 0;
}}

/* ---------------- metric rows ----------------
   Rows with a status-keyed left edge, not a deck of identical cards:
   the edge is the only decoration and it encodes the reading. */
.mrow {{
  display: grid; grid-template-columns: 15.5rem 1fr;
  gap: 1.1rem; align-items: start;
  padding: .82rem 0 .82rem 1rem;
  border-bottom: 1px solid var(--rule);
  border-left: 3px solid var(--edge, var(--rule));
}}
.mrow:last-child {{ border-bottom: none; }}
.mrow .lab {{
  font-size: .8rem; color: var(--ink-soft); margin-bottom: .1rem;
}}
.mrow .val {{
  font-size: 1.62rem; font-weight: 600; letter-spacing: -.022em;
  line-height: 1.05; color: var(--edge, var(--ink));
}}
.mrow .band {{
  font-size: .73rem; color: var(--ink-faint); margin-top: .25rem;
  max-width: 15rem; line-height: 1.35;
}}
.mrow .read {{
  font-family: {FONT_SERIF}; font-size: .97rem; line-height: 1.58;
  color: var(--ink); max-width: 62ch; padding-top: .18rem;
}}
.mrow .dir {{
  font-size: .73rem; color: var(--ink-faint); margin-top: .4rem;
}}

/* ---------------- flags ---------------- */
.flag {{
  border-left: 3px solid var(--fc); background: var(--paper-2);
  padding: .7rem .9rem; margin: .5rem 0; border-radius: 2px;
}}
.flag .ft {{ font-size: .88rem; font-weight: 600; color: var(--fc); }}
.flag .fd {{
  font-family: {FONT_SERIF}; font-size: .94rem; line-height: 1.55;
  color: var(--ink); margin-top: .22rem; max-width: 72ch;
}}

/* ---------------- provenance list ---------------- */
.prov {{ border-top: 1px solid var(--rule); }}
.prov .pr {{
  display: grid; grid-template-columns: 14rem 1fr; gap: 1rem;
  padding: .52rem 0; border-bottom: 1px solid var(--rule);
  font-size: .88rem;
}}
.prov .pr .k {{ color: var(--ink-soft); }}
.prov .pr .v {{ font-family: {FONT_SERIF}; color: var(--ink); line-height: 1.5; }}

/* ---------------- sidebar ---------------- */
.sb-h {{
  font-size: .82rem; font-weight: 600; color: var(--ink);
  margin: 1.4rem 0 .1rem 0; padding-bottom: .3rem;
  border-bottom: 1px solid var(--rule);
}}
.sb-h:first-child {{ margin-top: 0; }}
.sb-n {{
  font-family: {FONT_SERIF}; font-size: .83rem; line-height: 1.45;
  color: var(--ink-soft); margin: .4rem 0 .6rem 0;
}}

/* ---------------- widgets ---------------- */
[data-testid="stSidebar"] label p, [data-testid="stSidebar"] label {{
  font-size: .84rem !important; font-weight: 500 !important;
  color: var(--ink) !important;
}}
[data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] {{
  font-size: .68rem !important; color: var(--ink-faint) !important;
}}
.stTabs [data-baseweb="tab-list"] {{
  gap: .3rem; border-bottom: 1px solid var(--rule);
}}
.stTabs [data-baseweb="tab"] {{
  font-size: .9rem; font-weight: 500; color: var(--ink-soft);
  padding: .55rem .95rem; background: transparent;
}}
.stTabs [aria-selected="true"] {{
  color: var(--ink) !important; font-weight: 600;
  border-bottom: 2px solid var(--yours);
}}
.stTabs [data-baseweb="tab-highlight"] {{ display: none; }}
button[kind="secondary"], button[kind="primary"] {{
  border-radius: 2px !important; font-size: .83rem !important;
  font-weight: 500 !important;
}}
[data-testid="stDataFrame"] {{ border: 1px solid var(--rule); }}

/* Streamlit's alerts in the page palette rather than their own. */
[data-testid="stAlert"] {{
  background: var(--paper-2) !important;
  border: 1px solid var(--rule) !important;
  border-left: 3px solid var(--consensus) !important;
  border-radius: 2px !important;
  padding: .7rem .9rem !important;
}}
[data-testid="stAlert"] p {{
  font-family: {FONT_SERIF}; font-size: .95rem !important;
  line-height: 1.55 !important; color: var(--ink) !important;
}}
[data-testid="stAlert"] > div,
[data-testid="stAlertContainer"],
[data-testid="stAlertContentInfo"],
[data-testid="stAlertContentWarning"] {{
  background: transparent !important;
  color: var(--ink) !important;
}}

[data-testid="stSidebar"] {{ min-width: 332px; }}


/* ================= home screen =================
   Wider measure and more air than the app: this page is read, the app is
   used. The one bold element is the annotated gap bar. */
.lp-hero {{ margin: 2.4rem 0 2.2rem 0; }}
.lp-h1 {{
  font-size: clamp(2.3rem, 5.1vw, 3.75rem); font-weight: 700;
  letter-spacing: -.042em; line-height: 1.02; margin: 0;
  color: var(--ink);
}}
.lp-lede {{
  font-family: {FONT_SERIF}; font-size: 1.19rem; line-height: 1.6;
  color: var(--ink-soft); max-width: 60ch; margin: 1.15rem 0 0 0;
}}
.lp-ask {{
  font-size: .97rem; font-weight: 600; color: var(--ink);
  padding-bottom: .34rem; border-bottom: 1px solid var(--rule);
  margin-bottom: .75rem;
}}
.lp-hint {{
  font-family: {FONT_SERIF}; font-size: .9rem; line-height: 1.52;
  color: var(--ink-soft); max-width: 52ch; margin: .5rem 0 0 0;
}}
.lp-or {{
  font-size: .83rem; color: var(--ink-faint); margin: 1.5rem 0 .55rem 0;
}}
.lp-diagram {{
  background: var(--paper-2); border: 1px solid var(--rule);
  border-radius: 2px; padding: 1.5rem 1.2rem .9rem 1.2rem;
  margin: 3rem 0 0 0;
}}
.lp-cap {{
  font-family: {FONT_SERIF}; font-size: 1.01rem; line-height: 1.6;
  color: var(--ink); max-width: 72ch; margin: 1.05rem 0 0 0;
}}
.lp-sec {{
  font-size: 1.02rem; font-weight: 600; color: var(--ink);
  margin: 3.2rem 0 1.15rem 0; padding-bottom: .36rem;
  border-bottom: 1px solid var(--rule);
}}
.lp-note {{
  font-family: {FONT_SERIF}; font-style: italic; font-size: .98rem;
  color: var(--ink-soft); margin: -.5rem 0 1rem 0; max-width: 60ch;
}}
.lp-step {{ border-top: 2px solid var(--yours); padding-top: .72rem; }}
.lp-num {{
  font-size: .78rem; font-weight: 600; color: var(--yours);
  margin-bottom: .2rem;
}}
.lp-st {{
  font-size: 1.12rem; font-weight: 600; letter-spacing: -.016em;
  color: var(--ink); margin-bottom: .32rem;
}}
.lp-sb {{
  font-family: {FONT_SERIF}; font-size: .96rem; line-height: 1.58;
  color: var(--ink-soft); margin: 0; max-width: 42ch;
}}
.lp-list {{ border-top: 1px solid var(--rule); }}
.lp-row {{
  display: grid; grid-template-columns: 15rem 1fr; gap: 1.4rem;
  padding: .82rem 0; border-bottom: 1px solid var(--rule);
}}
.lp-rk {{
  font-size: .98rem; font-weight: 600; color: var(--ink);
  letter-spacing: -.012em;
}}
.lp-rv {{
  font-family: {FONT_SERIF}; font-size: .98rem; line-height: 1.58;
  color: var(--ink-soft); max-width: 66ch;
}}
.lp-rule {{
  border-top: 1px solid var(--rule); margin: 1.75rem 0 .2rem 0;
}}
.lp-foot {{
  margin: 3rem 0 1rem 0; padding-top: 1.1rem;
  border-top: 1px solid var(--rule);
}}
.lp-foot p {{
  font-family: {FONT_SERIF}; font-size: .89rem; line-height: 1.6;
  color: var(--ink-soft); max-width: 74ch; margin: 0;
}}
@media (max-width: 760px) {{
  .lp-row {{ grid-template-columns: 1fr; gap: .22rem; }}
  .lp-diagram {{ padding: .9rem .6rem; }}
  .lp-sec {{ margin-top: 2.2rem; }}
}}

/* Respect a reduced-motion preference. */
@media (prefers-reduced-motion: reduce) {{
  * {{ animation: none !important; transition: none !important; }}
}}

/* Keyboard focus must stay visible. */
:focus-visible {{ outline: 2px solid var(--yours); outline-offset: 2px; }}

@media (max-width: 760px) {{
  [data-testid="stAppViewBlockContainer"] {{ padding: 1rem 1rem 3rem 1rem; }}
  .mast {{ flex-wrap: wrap; gap: .35rem; }}
  .mast .tag {{ display: none; }}
  .co .nm {{ font-size: 1.5rem; }}
  .mrow {{ grid-template-columns: 1fr; gap: .35rem; }}
  .prov .pr {{ grid-template-columns: 1fr; gap: .1rem; }}
}}
</style>
"""


# --------------------------------------------------------------------------
# Plotly template
# --------------------------------------------------------------------------

def plotly_template() -> dict:
    axis = {
        "showgrid": True,
        "gridcolor": "rgba(232,236,233,0.08)",
        "gridwidth": 1,
        "zeroline": False,
        "showline": True,
        "linecolor": RULE,
        "linewidth": 1,
        "ticks": "outside",
        "ticklen": 4,
        "tickcolor": RULE,
        "tickfont": {"size": 11, "color": INK_SOFT},
        "title": {"font": {"size": 12, "color": INK_SOFT}},
        "automargin": True,
    }
    return {
        "layout": {
            "paper_bgcolor": "rgba(0,0,0,0)",
            "plot_bgcolor": "rgba(0,0,0,0)",
            "font": {"family": "Archivo, Helvetica Neue, Arial, sans-serif",
                     "size": 12, "color": INK},
            "colorway": [YOURS, CONSENSUS, MARKET, DOWN],
            "xaxis": axis,
            "yaxis": {**axis, "ticks": ""},
            "margin": {"l": 8, "r": 8, "t": 28, "b": 8},
            "hoverlabel": {
                "bgcolor": INK, "bordercolor": INK,
                "font": {"family": "Archivo", "size": 12, "color": PAPER},
            },
            "legend": {
                "orientation": "h", "yanchor": "bottom", "y": 1.02,
                "xanchor": "left", "x": 0,
                "font": {"size": 11, "color": INK_SOFT},
                "bgcolor": "rgba(0,0,0,0)",
            },
            "title": {"font": {"size": 13, "color": INK}, "x": 0, "xanchor": "left"},
        }
    }


CHART_CONFIG = {
    "displayModeBar": False,
    "scrollZoom": False,
    "responsive": True,
}
