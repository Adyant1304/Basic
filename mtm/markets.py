"""Which market a ticker trades in, and what that implies for the discount rate.

A DCF is only coherent if the cash flows, the risk-free rate, the equity risk
premium and the beta all describe the same market. The original build applied
an Indian 6.55% risk-free rate and a 7% premium to every ticker, so Apple was
being discounted as if it were an NSE stock. This module keeps those inputs
tied to the listing.

Beta is measured against the *local* benchmark for the same reason: a
company's sensitivity to the Nifty is what an Indian investor is paid for.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Market:
    key: str
    name: str
    benchmark: str          # Yahoo symbol of the local index
    benchmark_name: str
    risk_free: float        # static default, used when no live yield exists
    erp: float
    region: str             # Yahoo screener region code
    live_rf_symbol: str | None = None   # Yahoo symbol of a 10-year yield
    calibrated: bool = True             # False: defaults are placeholders
    rf_label: str = "10-year government bond yield"


INDIA_NSE = Market("IN", "India (NSE)", "^NSEI", "Nifty 50", 0.0655, 0.070,
                   "in", None, True, "10-year G-sec yield")
INDIA_BSE = Market("IN", "India (BSE)", "^BSESN", "S&P BSE Sensex", 0.0655,
                   0.070, "in", None, True, "10-year G-sec yield")
UNITED_STATES = Market("US", "United States", "^GSPC", "S&P 500", 0.0450,
                       0.045, "us", "^TNX", True, "10-year Treasury yield")


def _other(name: str, bench: str, bench_name: str, region: str) -> Market:
    return Market("OTHER:" + name, name, bench, bench_name, 0.0450, 0.055,
                  region, None, False, "10-year government bond yield")


_SUFFIX: dict[str, Market] = {
    ".NS": INDIA_NSE,
    ".BO": INDIA_BSE,
    ".L": _other("United Kingdom", "^FTSE", "FTSE 100", "gb"),
    ".TO": _other("Canada", "^GSPTSE", "S&P/TSX Composite", "ca"),
    ".AX": _other("Australia", "^AXJO", "S&P/ASX 200", "au"),
    ".HK": _other("Hong Kong", "^HSI", "Hang Seng", "hk"),
    ".T": _other("Japan", "^N225", "Nikkei 225", "jp"),
    ".SI": _other("Singapore", "^STI", "Straits Times", "sg"),
    ".DE": _other("Germany", "^GDAXI", "DAX", "de"),
    ".PA": _other("France", "^FCHI", "CAC 40", "fr"),
    ".KS": _other("South Korea", "^KS11", "KOSPI", "kr"),
    ".SS": _other("China (Shanghai)", "000001.SS", "SSE Composite", "cn"),
    ".SZ": _other("China (Shenzhen)", "399001.SZ", "SZSE Component", "cn"),
    ".SW": _other("Switzerland", "^SSMI", "SMI", "ch"),
    ".AS": _other("Netherlands", "^AEX", "AEX", "nl"),
}


def market_for(ticker: str) -> Market:
    """The market a Yahoo symbol belongs to. No suffix means a US listing."""
    t = (ticker or "").strip().upper()
    for suffix, market in _SUFFIX.items():
        if t.endswith(suffix):
            return market
    return UNITED_STATES
