"""A synthetic company, for tests and for a first run with no network.

These figures are invented. They are shaped like a mid-sized Indian IT
services firm so the UI and the engine can be exercised end to end, but
nothing here is real data about any real company, and the app labels it
clearly whenever it is in use.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .data import Company, Series

_YEARS = [2026, 2025, 2024, 2023, 2022]

# Revenue in rupees, newest first: a business compounding around 9%.
_REVENUE = [412_000_000_000, 379_000_000_000, 348_000_000_000,
            314_000_000_000, 281_000_000_000]
_EBIT = [86_500_000_000, 77_800_000_000, 73_100_000_000,
         68_100_000_000, 63_800_000_000]
_NET = [66_900_000_000, 60_200_000_000, 56_400_000_000,
        52_600_000_000, 49_300_000_000]
_DA = [11_200_000_000, 10_400_000_000, 9_800_000_000,
       9_100_000_000, 8_400_000_000]
_CAPEX = [-14_800_000_000, -13_200_000_000, -12_600_000_000,
          -11_400_000_000, -10_900_000_000]
_CHG_WC = [-6_200_000_000, -5_400_000_000, -7_100_000_000,
           -4_800_000_000, -5_900_000_000]
_OCF = [74_100_000_000, 67_300_000_000, 61_900_000_000,
        58_200_000_000, 54_100_000_000]
_FCF = [59_300_000_000, 54_100_000_000, 49_300_000_000,
        46_800_000_000, 43_200_000_000]


def sample_company() -> Company:
    # Copy every list. Handing out the module-level lists would let one
    # caller's mutation leak into every later call.
    def s(label: str, values: list[float]) -> Series:
        return Series(label, list(_YEARS), list(values))

    c = Company(
        ticker="SAMPLE.NS",
        name="Sample Services Ltd (illustrative data)",
        sector="Technology",
        industry="Information Technology Services",
        currency="INR",
        price=1_148.0,
        shares_out=1_040_000_000,
        market_cap=1_148.0 * 1_040_000_000,
        revenue=s("Total Revenue", _REVENUE),
        ebit=s("EBIT", _EBIT),
        net_income=s("Net Income", _NET),
        da=s("Depreciation And Amortization", _DA),
        capex=s("Capital Expenditure", _CAPEX),
        chg_wc=s("Change In Working Capital", _CHG_WC),
        ocf=s("Operating Cash Flow", _OCF),
        fcf=s("Free Cash Flow", _FCF),
        total_debt=18_400_000_000,
        cash=132_000_000_000,
        equity_book=288_000_000_000,
        invested_capital=241_000_000_000,
        interest_expense=1_480_000_000,
        beta=0.82,
        trailing_pe=17.9,
        forward_pe=16.3,
        analyst_growth=0.082,
        target_mean=1_242.0,
        n_analysts=34,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source="sample",
    )
    c._pretax = s("Pretax Income",
                  [88_300_000_000, 79_400_000_000, 74_600_000_000,
                   69_500_000_000, 65_100_000_000])
    c._tax = s("Tax Provision",
               [21_400_000_000, 19_200_000_000, 18_200_000_000,
                16_900_000_000, 15_800_000_000])
    return c
