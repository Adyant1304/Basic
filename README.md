# Basic

**What the price has to believe.**

Type a ticker. The app pulls the financials from Yahoo Finance, builds a
discounted cash flow baseline out of the company's own history, and shows
you what growth rate today's share price is already paying for. Then you
drag the assumptions and watch the valuation move.

The claim the tool makes is not "this stock is worth ₹1,025." It is "the
market is paying for 12.0% growth and you only believe 9.1% — that gap is
your thesis."

## What it does

**Reverse DCF.** Solves by bisection for the growth rate that makes the
model print today's market price. This is the feature the tool exists for:
it turns "is this cheap" into "what would have to be true", which is the
question an analyst actually asks.

**Sensitivity grid.** Value per share across WACC and terminal growth, the
two assumptions that between them decide most of any DCF. If the sign of
the upside flips inside that grid, the verdict is a function of your
discount rate rather than of the business, and you can see it immediately.

**Tornado.** Which assumption moves the answer most, ranked. Tells you where
to spend research time.

**Monte Carlo.** 6,000 runs drawing growth, margin and WACC from normal
distributions around your assumptions, reported as a distribution and as the
share of outcomes that beat the current price. The point estimate is never
shown alone.

**Business-quality panel.** ROIC against WACC, margin level and volatility,
cash conversion, net cash. Every metric states which direction is better, a
reference band, and a sentence reading that specific value for that specific
company.

**Assumption checks.** Flags growth above anything in the record, margin
above the historical peak, terminal growth above the risk-free rate, a
WACC-to-terminal-growth spread too thin to be meaningful, and a terminal
value that has swallowed the valuation.

**Audit tab.** Every baseline prints the rule that produced it. The WACC
build is itemised. The full projection is a table you can download as CSV.

---

## The model

```
Revenue_t   = Revenue_(t-1) x (1 + g_t)
g_t           held at g_near for 3 years, then tapered to g_terminal
Margin_t      tapered from the current margin to the target
EBIT_t      = Revenue_t x Margin_t
NOPAT_t     = EBIT_t x (1 - tax)
Reinvest_t  = (Revenue_t - Revenue_(t-1)) / sales_to_capital
FCFF_t      = NOPAT_t - Reinvest_t

TV          = FCFF_(N+1) / (WACC - g_terminal)
FCFF_(N+1)  = NOPAT_N x (1 + g_term) x (1 - g_term / ROIC_term)

EV          = sum FCFF_t / (1+WACC)^t  +  TV / (1+WACC)^N
Equity      = EV - total debt + cash
Per share   = Equity / shares outstanding
```

Two choices worth defending out loud, because a professor will ask:

**Terminal growth is funded.** The terminal reinvestment rate is
`g_terminal / ROIC_terminal`, so perpetual growth has to be paid for out of
cash flow instead of appearing free. Letting terminal growth rise without
charging for it is the single most common way a student DCF inflates itself.

**Terminal growth is capped below the risk-free rate.** A company growing
faster than the economy forever eventually becomes the economy. The app
raises a hard flag if you push past it.

WACC is CAPM: `risk-free + beta x equity risk premium` for the cost of
equity, blended with the after-tax cost of debt at market weights. The
risk-free rate defaults to 6.55%, roughly the Indian 10-year G-sec, and the
equity risk premium to 7.0%. Both are sliders, because both move and neither
belongs hard-coded in a model.

---

## Why this is not just asking a chatbot

A language model asked to project revenue is predicting plausible-looking
text. Ask twice, get two numbers. This engine is a pure function: same
inputs, same output, every time, and the test suite pins it to a hand
calculation.

Nothing in the valuation path touches a model. Yahoo supplies the
financials, documented rules derive the baselines, and the Audit tab prints
every rule. When a baseline cannot be computed the app says what it fell
back to instead of quietly inventing a number.

And the interaction only works because the maths is local. Dragging a slider
recomputes in under a millisecond. Round-tripping each drag through an API
would make exploring a scenario space impossible — you could only ask one
question at a time.

---

## Layout

```
app.py                  the Streamlit page: layout, state, tabs
mtm/data.py             Yahoo extraction, aliasing, snapshots
mtm/engine.py           the DCF, reverse DCF, sensitivity, tornado, Monte Carlo
mtm/metrics.py          ratios with readings, and the sanity flags
mtm/charts.py           Plotly figures on one shared template
mtm/components.py       the gap bar and the HTML pieces
mtm/theme.py            palette, type, number formatting, CSS
mtm/sample.py           the invented company used when no ticker is entered
mtm/snapshot.py         save companies for offline use
tests/test_engine.py    29 tests
```

`data.py` never trusts a single Yahoo label: every line item is looked up
through a list of aliases, because Yahoo renames them between companies and
filings. Anything missing degrades to a documented default that gets
recorded and shown, rather than crashing or silently guessing.

---

## Known limits

State these before anyone else does; it is what makes the work credible.

- **Yahoo Finance is unofficial.** Figures are occasionally wrong or stale,
  and coverage of Indian mid and small caps is patchy. The Audit tab exists
  so you can check what was fetched against the filings.
- **The Monte Carlo draws independently.** In reality a demand shock and a
  margin shock arrive together, so the real distribution has fatter tails.
  Read the band as a floor on the uncertainty, not a ceiling.
- **A DCF suits stable, cash-generative businesses.** It is a poor fit for
  loss-makers, financials, and anything cyclical enough that the last five
  years say little about the next ten.
- **Guidance is not parsed from transcripts.** The baseline comes from
  reported history plus Yahoo's growth figure. Reading management guidance
  out of concall transcripts is the natural next version.
- **Five years of history is thin** for estimating a through-cycle margin.
  The app flags it when Yahoo returns fewer than three.

---

Educational project. Not investment advice.
