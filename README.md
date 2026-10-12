# Basic

**What the price has to believe.**

Type a ticker. The app pulls the financials from Yahoo Finance, builds a
discounted cash flow baseline out of the company's own history, and shows
you what growth rate today's share price is already paying for. Then you
drag the assumptions and watch the valuation move.

The claim the tool makes is not "this stock is worth ₹1,025." It is "the
market is paying for 12.0% growth and you only believe 9.1% — that gap is
your thesis."

---

## Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

It opens at `http://localhost:8501` on the home screen, which explains the
idea and takes a ticker. From there, open a company or load the worked
example, which runs on invented figures so the whole tool is visible without
fetching anything. The sidebar has a way back.

Indian listings need the exchange suffix: `INFY.NS` for the NSE, `INFY.BO`
for the BSE. US tickers work bare: `AAPL`, `MSFT`.

### Before a presentation, save snapshots

```bash
python -m mtm.snapshot INFY.NS HCLTECH.NS WIPRO.NS TCS.NS ASIANPAINT.NS TITAN.NS
```

Each snapshot saves the company *and* its peer set, so the Relative value tab
works offline too. The app falls back to these automatically whenever Yahoo is
unreachable, and says on screen that it is doing so. Campus wifi has ended
better demos than yours. Every company you open online is also saved, so
anything you have looked at once is available offline afterwards.

A link such as `http://localhost:8501/?ticker=TCS.NS` opens that company
directly.

### Tests

```bash
python -m pytest tests/ -q      # 186 tests, about 25 seconds, no network
```

Three groups matter most:

- `test_matches_hand_calculation` checks the DCF against a figure worked out
  independently from the formula, line by line. If that passes, the engine is
  doing arithmetic rather than something that merely resembles it.
- `test_beta.py` checks that the regression recovers a beta built into
  synthetic data, and refuses to report one when the data cannot support it.
- `test_app.py` drives the real Streamlit script and clicks its real buttons
  and selectors. Several bugs (a crashing "Market-implied" button, sliders
  seeded outside their range) are Streamlit rules about widgets, so only
  running the page can catch them.

No test touches the network or writes into `data/`.

### Deploying

Push to GitHub, then connect the repo at
[share.streamlit.io](https://share.streamlit.io). It is free, it is one
click, and `requirements.txt` is already here. You get a public URL you can
put on a slide.

---

## What it does

**Overview.** A company snapshot before any modelling: what the business is,
twenty-odd key figures grouped by the question they answer (what the market
says, what it is priced at, how well the business earns, how strong the
balance sheet is), five years of share price, the income statement, balance
sheet and cash flow, and the reported record of revenue and margins. The
valuation ratios are rebuilt after currency translation, because Yahoo's own
versions are wrong whenever a company is quoted in one currency and reports
in another.

**Beta, measured per company.** Yahoo's `beta` is unusable for Indian
listings (on the day this was written it said 0.12 for Infosys, 0.18 for TCS
and -0.06 for ITC). Beta is instead the slope of a regression of the stock's
five years of weekly returns on its local index (Nifty 50 for NSE, Sensex for
BSE, S&P 500 for US listings). The sidebar lets you choose the raw regression,
the Blume-adjusted figure, Yahoo's number, or your own; the Overview draws the
regression itself with its R-squared and confidence interval.

**Segments.** Revenue by business and by geography as donut, ranked bars, a
before-and-after dumbbell of how the mix moved, and a table. Yahoo publishes
no segment data, so this comes from `data/segments.json`, transcribed from
company filings, each entry carrying its source, its period and the total the
filing states (a test checks that every entry adds up). For a company that is
not in the file there is a small table to type its segments into.

**Relative value.** Peers come from Yahoo's screener: same exchange, same
industry, nearest eight by market value (editable). The table shows P/E,
forward P/E, P/B, EV/EBITDA and EV/Sales with the peer median, then what each
median implies for one share, then a football-field chart putting the DCF, the
analyst range and every peer multiple on one price axis. Banks get P/E and P/B
only, because enterprise-value multiples mean nothing for a lender.

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
inputs belong to the market the stock trades in. Indian listings default to a
6.55% risk-free rate (roughly the 10-year G-sec, which Yahoo does not carry,
so update it) and a 7.0% premium; US listings take the live 10-year Treasury
yield from Yahoo and a 4.5% premium. Both are sliders, because both move and
neither belongs hard-coded in a model.

Operating margin uses Yahoo's *Operating Income* line, not *EBIT*. EBIT is
pretax income plus interest, so it carries other income and one-off gains
(TTML's FY26 "EBIT" was 99.6% of revenue); using it would also count
treasury income twice, once in the margin and again when cash is added back.

When Yahoo reports a company's statements in a different currency from its
share price (Infosys and HCLTech: rupee price, dollar financials), every
statement figure is translated at the day's spot rate and the translation is
disclosed on the page and in the Audit tab.

**When a DCF does not apply.** For banks and lenders, deposits are raw
material rather than financing, so enterprise value is meaningless. The app
says so, hides the DCF tabs and keeps Overview, Segments and Relative value;
a sidebar box runs the DCF anyway if you want to see why not.

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
app.py                  the Streamlit page: layout, state, sidebar, tabs
mtm/data.py             Yahoo extraction, aliasing, currency, snapshots
mtm/beta.py             the beta regression (pure arithmetic)
mtm/markets.py          which market a ticker is in; its index and default rates
mtm/engine.py           WACC, the DCF, reverse DCF, sensitivity, tornado, Monte Carlo
mtm/metrics.py          ratios with readings, and the sanity flags
mtm/peers.py            peer discovery, peer multiples, implied values
mtm/segments.py         segment data loading, shares, validation
mtm/views.py            the Overview, Segments and Relative value tabs
mtm/charts.py           Plotly figures on one shared template
mtm/components.py       the gap bar, KPI tiles, tables and HTML pieces
mtm/theme.py            palette, type, number formatting, CSS
mtm/landing.py          the home screen
mtm/sample.py           the invented company used when no ticker is entered
mtm/snapshot.py         save companies and peer sets for offline use
data/segments.json      segment revenue from company filings, with sources
data/snapshots/         saved companies (written automatically)
tests/                  186 tests: engine, beta, data, peers, segments, views, app
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
- **Segment data is not automatic.** It is stored for Infosys, Wipro, Apple
  and Titan (Titan for one quarter only); every other company needs its
  segments typed in from the annual report. Adding a company to
  `data/segments.json` takes one entry, and the tests check that it adds up.
- **Beta has an error bar.** A five-year weekly regression typically explains
  20-45% of a stock's moves, and the 95% range is often 0.4 points wide. The
  app shows R-squared and the range next to the number, and flags a weak fit.
- **Currency translation uses today's rate.** For companies Yahoo reports in
  a foreign currency, growth reflects the foreign-currency accounts and so
  excludes currency drift (Infosys's rupee growth is higher than its dollar
  growth).
- **Peers are matched on industry and size, not on business model.** Edit the
  set when the automatic one is wrong.
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
