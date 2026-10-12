"""Peer set and relative valuation.

A DCF says what a business is worth on one set of assumptions. A peer table
asks the other question: what does the market pay for similar businesses
right now? Putting the two next to each other is the point. If the DCF says a
company is cheap and every peer trades on a lower multiple, the DCF is
probably the outlier.

Peer discovery
--------------
Yahoo exposes no clean "peers" field, so the set is built from its screener:
companies on the *same exchange* in the *same industry*, then the eight
nearest to the target by market value (size is the cheapest proxy for
business model, risk and liquidity). If that returns too few names the
"similar companies" recommendation list is used instead, and the user can
always type their own list.

Everything that turns rows into numbers (`summarize`, `implied_values`,
`premium`) is pure so it can be tested without a network.
"""

from __future__ import annotations

import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from .data import (SNAPSHOT_DIR, Company, _first_num, _fx_rate, _major, _num,
                   _safe, build_stats)

PEER_DIR = SNAPSHOT_DIR / "peers"
DEFAULT_PEERS = 8
MIN_PEERS_FOR_STATS = 3

# key, short label, long label
MULTIPLES = [
    ("pe", "P/E", "Price to earnings, trailing twelve months"),
    ("fwd_pe", "Fwd P/E", "Price to earnings, next twelve months (analyst)"),
    ("pb", "P/B", "Price to book value"),
    ("ev_ebitda", "EV/EBITDA", "Enterprise value to EBITDA"),
    ("ev_sales", "EV/Sales", "Enterprise value to revenue"),
]
EV_KEYS = ("ev_ebitda", "ev_sales")
MULTIPLE_CAPS = {"pe": 300, "fwd_pe": 300, "pb": 100, "ev_ebitda": 150,
                 "ev_sales": 100}


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

def row_from_info(symbol: str, info: dict, fx: float = 1.0) -> dict | None:
    """One peer's comparison row from a Yahoo `info` dict."""
    price = _first_num(info, ["currentPrice", "regularMarketPrice",
                              "previousClose"])
    mcap = _first_num(info, ["marketCap"])
    if not price or not mcap:
        return None
    s = build_stats(info, price, mcap, fx, None, {})
    return {
        "ticker": symbol.upper(),
        "name": info.get("shortName") or info.get("longName") or symbol,
        "industry": info.get("industry") or "",
        "currency": info.get("currency") or "",
        "price": price,
        "market_cap": mcap,
        **{k: s.get(k) for k, *_ in MULTIPLES},
        "roe": s.get("roe"),
        "op_margin": s.get("op_margin"),
        "net_margin": s.get("net_margin"),
        "rev_growth": s.get("rev_growth"),
        "dividend_yield": s.get("dividend_yield"),
    }


def self_row(c: Company) -> dict:
    """The target company as a row, so it sits in the same table."""
    s = c.stats or {}
    return {
        "ticker": c.ticker, "name": c.name, "industry": c.industry,
        "currency": c.currency, "price": c.price, "market_cap": c.market_cap,
        **{k: s.get(k) for k, *_ in MULTIPLES},
        "roe": s.get("roe"), "op_margin": s.get("op_margin"),
        "net_margin": s.get("net_margin"), "rev_growth": s.get("rev_growth"),
        "dividend_yield": s.get("dividend_yield"),
    }


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------

def nearest_by_size(candidates: list[dict], self_symbol: str,
                    self_mcap: float, n: int) -> list[dict]:
    """The n candidates closest to the target in log market value."""
    pool = [q for q in candidates
            if q.get("symbol") and q["symbol"].upper() != self_symbol.upper()
            and (q.get("marketCap") or 0) > 0]
    if not pool or not self_mcap:
        return pool[:n]
    pool.sort(key=lambda q: abs(math.log(q["marketCap"] / self_mcap)))
    return pool[:n]


# US names list in many places, and the OTC/pink-sheet copies of foreign
# companies carry unreliable EV and EBITDA (Samsung's OTC line showed EV/EBITDA
# of -893x), so the US search is limited to the real exchanges.
US_MAJOR_EXCHANGES = ("NMS", "NYQ", "NGM", "NCM", "ASE", "PCX")
MIN_CANDIDATES = 4            # fewer than this and we widen the search
MIN_SIZE_RATIO = 0.02         # ignore companies under 2% of the target's value


def _norm_dash(s: str) -> str:
    """Yahoo writes 'Banks - Regional' in `info` but 'Banks—Regional' in the
    screener. Compare them with all dash styles and spacing removed."""
    return re.sub(r"\s*[-–—]\s*", "-", s or "").strip().lower()


def screener_value(field: str, value: str) -> str | None:
    """The screener's own spelling of an industry or sector, or None."""
    from yfinance import const

    valid = const.EQUITY_SCREENER_EQ_MAP.get(field)
    if valid is None:
        return None
    flat = (set().union(*valid.values()) if isinstance(valid, dict)
            else set(valid))
    want = _norm_dash(value)
    return next((v for v in flat if _norm_dash(v) == want), None)


def _dedupe(quotes: list[dict]) -> list[dict]:
    """One line per company: keep the biggest of any duplicate listings."""
    best: dict[str, dict] = {}
    for q in quotes:
        key = re.sub(r"[^a-z0-9]", "", (q.get("shortName") or
                                        q.get("symbol") or "").lower())
        if key not in best or (q.get("marketCap") or 0) > (
                best[key].get("marketCap") or 0):
            best[key] = q
    return list(best.values())


def _screen(filters: list[tuple], size: int = 100) -> list[dict]:
    import yfinance as yf
    from yfinance import EquityQuery

    parts = []
    for op, field, *vals in filters:
        parts.append(EquityQuery(op, [field, *vals]))
    q = EquityQuery("and", parts)
    res = yf.screen(q, size=size, sortField="intradaymarketcap",
                    sortAsc=False)
    return res.get("quotes", []) if isinstance(res, dict) else []


def find_peers(c: Company, n: int = DEFAULT_PEERS) -> tuple[list[str], str]:
    """(tickers, how they were chosen). Empty list if nothing could be found."""
    region = c.market.region
    if region == "us":
        place = ("is-in", "exchange", *US_MAJOR_EXCHANGES)
        where = "in the US"
    elif c.exchange_code:
        place = ("eq", "exchange", c.exchange_code)
        where = {"NSI": "on the NSE", "BSE": "on the BSE"}.get(
            c.exchange_code, "on the same exchange")
    else:
        place = ("eq", "region", region)
        where = "in the same market"

    levels = []
    if c.industry:
        levels.append(("industry", c.industry, f"in {c.industry}"))
    if c.sector and c.sector != "Unclassified":
        levels.append(("sector", c.sector, f"in the {c.sector} sector"))

    best: tuple[list[dict], str] = ([], "")
    for field, value, label in levels:
        resolved = _safe(lambda f=field, v=value: screener_value(f, v))
        if not resolved:
            continue
        quotes = _safe(lambda f=field, r=resolved: _screen(
            [place, ("eq", f, r)]))
        if not quotes:
            continue
        pool = [q for q in _dedupe(quotes)
                if (q.get("marketCap") or 0) >= MIN_SIZE_RATIO * c.market_cap]
        chosen = nearest_by_size(pool, c.ticker, c.market_cap, n)
        if len(chosen) >= MIN_CANDIDATES:
            return ([q["symbol"] for q in chosen],
                    f"Yahoo Finance screener: the {len(chosen)} companies "
                    f"{where} {label} that are closest to {c.name} by market "
                    "value.")
        if len(chosen) > len(best[0]):
            best = (chosen, f"Yahoo Finance screener: the only "
                    f"{len(chosen)} comparable companies {where} {label}.")

    if len(best[0]) >= MIN_PEERS_FOR_STATS:
        return [q["symbol"] for q in best[0]], best[1]

    recs = _safe(lambda: _recommended(c.ticker))
    if recs:
        return (recs[:n], "Yahoo Finance's list of similar companies. The "
                "screener found too few matches in the same industry.")
    return [], ""


def _recommended(ticker: str) -> list[str]:
    import yfinance as yf

    url = ("https://query2.finance.yahoo.com/v6/finance/"
           "recommendationsbysymbol/" + ticker)
    data = yf.Ticker(ticker)._data.get_raw_json(url)
    res = data["finance"]["result"][0]["recommendedSymbols"]
    return [r["symbol"] for r in res if r.get("symbol")]


# --------------------------------------------------------------------------
# Fetching peer rows
# --------------------------------------------------------------------------

def fetch_rows(symbols: list[str], max_workers: int = 4) -> list[dict]:
    """Fetch comparison rows for each symbol, skipping any that fail."""
    import yfinance as yf

    fx_cache: dict[tuple[str, str], float] = {}

    def one(sym: str) -> dict | None:
        info: dict[str, Any] | None = None
        for attempt in range(2):
            try:
                info = yf.Ticker(sym).info or {}
                if info:
                    break
            except Exception:
                time.sleep(0.4)
        if not info:
            return None
        trading = info.get("currency") or ""
        fin = info.get("financialCurrency") or trading
        fx = 1.0
        if trading and fin and (_major(fin) != _major(trading)):
            key = (fin, trading)
            if key not in fx_cache:
                fx_cache[key] = _safe(lambda: _fx_rate(yf, fin, trading)) or 0.0
            fx = fx_cache[key]
            if not fx:
                return None            # cannot translate, so cannot compare
        return row_from_info(sym, info, fx)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        rows = list(pool.map(one, symbols))
    return [r for r in rows if r]


def load_peer_set(c: Company, custom: list[str] | None = None,
                  n: int = DEFAULT_PEERS) -> dict:
    """Peer rows for a company. Network first, then the saved snapshot."""
    custom = [s.strip().upper() for s in (custom or []) if s.strip()]
    try:
        if custom:
            symbols, method = custom, "Your own list."
        else:
            symbols, method = find_peers(c, n)
        symbols = [s for s in dict.fromkeys(symbols)
                   if s.upper() != c.ticker.upper()]
        rows = fetch_rows(symbols) if symbols else []
        if rows:
            out = {"method": method, "rows": rows,
                   "fetched_at": datetime.now(timezone.utc).isoformat(
                       timespec="seconds"),
                   "source": "yahoo", "custom": bool(custom)}
            if not custom:
                _safe(lambda: save_peer_snapshot(c.ticker, out))
            return out
    except Exception:
        pass
    if not custom:
        snap = load_peer_snapshot(c.ticker)
        if snap:
            snap["source"] = "snapshot"
            return snap
    return {"method": "", "rows": [], "fetched_at": "", "source": "none",
            "custom": bool(custom)}


def save_peer_snapshot(ticker: str, payload: dict) -> Path:
    PEER_DIR.mkdir(parents=True, exist_ok=True)
    p = PEER_DIR / f"{ticker.upper()}.json"
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def load_peer_snapshot(ticker: str) -> dict | None:
    p = PEER_DIR / f"{ticker.upper()}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# Statistics and implied values (pure)
# --------------------------------------------------------------------------

def _valid(key: str, v: Any) -> float | None:
    x = _num(v)
    return x if x is not None and 0 < x < MULTIPLE_CAPS.get(key, 1e9) else None


def summarize(rows: list[dict]) -> dict[str, dict]:
    """Median, quartiles and spread of each multiple across the peers."""
    out: dict[str, dict] = {}
    for key, *_ in MULTIPLES:
        vals = [v for v in (_valid(key, r.get(key)) for r in rows)
                if v is not None]
        if len(vals) < MIN_PEERS_FOR_STATS:
            out[key] = {"n": len(vals), "median": None}
            continue
        a = np.array(vals)
        out[key] = {
            "n": len(vals), "median": float(np.median(a)),
            "mean": float(np.mean(a)),
            "q1": float(np.percentile(a, 25)),
            "q3": float(np.percentile(a, 75)),
            "min": float(a.min()), "max": float(a.max()),
        }
    return out


def premium(own: float | None, median: float | None) -> float | None:
    """How far above (+) or below (-) the peer median the company trades."""
    if own is None or not median:
        return None
    return own / median - 1.0


def implied_values(c: Company, summary: dict[str, dict],
                   skip_ev: bool = False) -> list[dict]:
    """What each peer multiple says one share is worth.

    Equity multiples (P/E, P/B) scale the current price by the ratio of the
    peer median to the company's own multiple, which is the same as applying
    the peer multiple to the company's earnings or book value. Enterprise
    multiples are applied to EBITDA or revenue and then bridged to equity by
    subtracting net debt. `low` and `high` use the peers' lower and upper
    quartiles, so the range reflects how much the peers disagree.
    """
    s = c.stats or {}
    net_debt = (c.total_debt or 0.0) - (c.cash or 0.0)
    out: list[dict] = []
    for key, label, _ in MULTIPLES:
        if skip_ev and key in EV_KEYS:
            continue
        sm = summary.get(key) or {}
        med = sm.get("median")
        if med is None:
            continue
        own = s.get(key)

        def at(m: float) -> float | None:
            if key in ("pe", "fwd_pe", "pb"):
                own_m = _valid(key, own)
                return c.price * m / own_m if own_m else None
            if key == "ev_ebitda":
                base = s.get("ebitda")
                if not base or base <= 0:
                    return None
                return (m * base - net_debt) / c.shares_out
            base = s.get("revenue_ttm")
            if not base:
                return None
            return (m * base - net_debt) / c.shares_out

        mid, lo, hi = at(med), at(sm["q1"]), at(sm["q3"])
        # A negative value means the multiple cannot support the company's
        # debt: say nothing rather than print a negative share price.
        if mid is None or lo is None or hi is None or mid <= 0:
            continue
        lo = max(lo, 0.0)
        lo, hi = min(lo, hi), max(lo, hi)
        out.append({
            "key": key, "label": label, "peer_median": med,
            "own": own, "low": lo, "mid": mid, "high": hi,
            "vs_price": mid / c.price - 1.0, "n": sm["n"],
        })
    return out
