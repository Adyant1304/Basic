# Live test results

Run on **12 October 2026** against live Yahoo Finance data, through the real
Streamlit script (not the engine alone). These are the eight tests listed for
section 7.2 of the report.

Reload time is the whole page: fetch, beta regression, DCF, Monte Carlo, and the
peer set. "Yahoo beta" is what Yahoo's own `beta` field returned; "Beta used" is
the five-year weekly regression against the local index that the app now uses.

| # | Test | Result | Reload | Yahoo beta | Beta used | WACC | DCF vs price |
|---|------|--------|--------|-----------|-----------|------|--------------|
| 1 | `INFY.NS` | Pass. Statements are in USD against an INR price; translated at 95.73 and disclosed. 8 peers. | 5.5 s | 0.12 | 0.86 | 12.4% | ₹836, 17.4% below |
| 2 | `TCS.NS` | Pass. 8 peers. | 3.7 s | 0.18 | 0.90 | 12.8% | ₹1,955, 8.4% below |
| 3 | `ITC.NS` | Pass. Yahoo's beta was negative. 8 peers. | 4.8 s | -0.06 | 0.67 | 11.2% | ₹215, 16.6% below |
| 4 | `AAPL` | Pass. US market: live 10-year Treasury yield (5.24%), 4.5% premium, S&P 500 beta. 8 peers. | 5.2 s | 1.07 | 1.15 | 10.3% | $129, 61.6% below |
| 5 | `HDFCBANK.NS` | Pass. Recognised as a lender: DCF tabs hidden with an explanation, P/E and P/B peers shown, no EV multiples. | 3.7 s | 0.41 | 1.00 | n/a | not applicable |
| 6 | `TTML.BO` | Pass. Debt exceeds enterprise value; the page says so instead of printing "291% below". Beta fit is weak (R-squared 0.08) and flagged. | 4.4 s | 0.44 | 1.35 | 8.1% | negative (debt exceeds value) |
| 7 | `INFY` | Pass, but see note: this is Infosys's NYSE ADR, a valid ticker. | 4.6 s | 0.12 | 0.78 | 8.7% | $15, 38.7% above |
| 8 | `NOTAREALSYMBOL` | Pass. Clear message with the `.NS`/`.BO` hint, no traceback, lists the offline snapshots. | 2.0 s | n/a | n/a | n/a | n/a |
| + | Offline snapshot (network disabled) | Pass. `INFY.NS` loads from the saved copy with a banner saying so, the peer set loads from its saved copy, DCF identical (₹836). | 0.0 s | | | | |

**Note on test 7.** The handoff described `INFY` as a "bad ticker". It is not:
without a suffix Yahoo resolves it to the NYSE-listed ADR. A genuinely invalid
symbol is test 8.

## What the original code did on the same inputs

For the report's before/after comparison:

| Ticker | Original output | Cause |
|--------|-----------------|-------|
| `INFY.NS` | DCF ₹17 against a ₹1,012 price (98% below) | Dollar statements divided by a rupee share count |
| `TCS.NS`, `ITC.NS` | WACC 8.6% for both; DCF 79% and 41% *above* price | Yahoo betas of 0.18 and -0.06 clamped up to 0.3 |
| `HDFCBANK.NS` | Operating margin exactly 100%; DCF ₹3,513 against ₹705 | "Operating Revenue" was an alias for EBIT, and banks have no EBIT row |
| `TTML.BO` | Margin 99.6%; negative value | The "EBIT" row included a one-off gain |
| `AAPL` | WACC 13.9% | Indian 6.55% risk-free rate and 7% premium applied to a US stock |
| Any company, "Market-implied" button | Page crash (`StreamlitWidgetAlreadyInstantiatedError`) | Wrote to a slider's key after the slider existed |

Betas, prices and valuations move every day; the point of the table is that
every case loads, explains itself, and produces a number that is defensible or
a refusal that is.
