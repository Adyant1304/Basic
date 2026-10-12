"""Peer discovery and relative valuation. Pure arithmetic, no network."""

import pytest

from mtm import peers as P
from mtm.sample import sample_company, sample_peer_set


@pytest.fixture
def company():
    c = sample_company()
    # Clean, round numbers so the implied values can be checked by hand.
    c.price = 100.0
    c.shares_out = 1000.0
    c.market_cap = 100_000.0
    c.total_debt = 5_000.0
    c.cash = 15_000.0                     # net cash of 10,000
    c.stats = {"pe": 20.0, "fwd_pe": 18.0, "pb": 4.0, "ev_ebitda": 9.0,
               "ev_sales": 2.0, "ebitda": 10_000.0, "revenue_ttm": 45_000.0,
               "target_low": 90.0, "target_high": 150.0, "target_mean": 120.0,
               "low_52w": 80.0, "high_52w": 130.0}
    return c


def _peer(pe, pb=3.0, eveb=10.0, evs=2.0, fpe=None):
    return {"ticker": f"P{pe}", "name": f"Peer {pe}", "market_cap": 1e5,
            "pe": pe, "fwd_pe": fpe or pe * 0.9, "pb": pb,
            "ev_ebitda": eveb, "ev_sales": evs}


# --------------------------------------------------------------------------
# Choosing peers
# --------------------------------------------------------------------------

def test_nearest_by_size_picks_the_closest_in_log_terms():
    cands = [{"symbol": "A", "marketCap": 10}, {"symbol": "B", "marketCap": 95},
             {"symbol": "C", "marketCap": 400}, {"symbol": "D", "marketCap": 1000}]
    got = P.nearest_by_size(cands, "SELF", 100, 2)
    assert [q["symbol"] for q in got] == ["B", "C"]      # 0.95x and 4x


def test_nearest_by_size_excludes_the_company_itself():
    cands = [{"symbol": "self.ns", "marketCap": 100}, {"symbol": "X", "marketCap": 90}]
    assert [q["symbol"] for q in P.nearest_by_size(cands, "SELF.NS", 100, 5)] == ["X"]


def test_nearest_by_size_drops_companies_without_a_market_cap():
    cands = [{"symbol": "A", "marketCap": 0}, {"symbol": "B"}, {"symbol": "C", "marketCap": 5}]
    assert [q["symbol"] for q in P.nearest_by_size(cands, "S", 5, 5)] == ["C"]


def test_duplicate_listings_collapse_to_the_biggest():
    """Sony appeared twice (OTC and NYSE), Xiaomi twice, Panasonic twice."""
    q = [{"symbol": "SNEJF", "shortName": "Sony Group Corporation", "marketCap": 142},
         {"symbol": "SONY", "shortName": "Sony Group Corporation", "marketCap": 141},
         {"symbol": "XIACY", "shortName": "Xiaomi Corp.", "marketCap": 85}]
    got = P._dedupe(q)
    assert len(got) == 2
    assert {x["symbol"] for x in got} == {"SNEJF", "XIACY"}


def test_screener_industry_names_are_normalised():
    """Yahoo's info says 'Banks - Regional'; the screener only accepts
    'Banks—Regional'. Passing the first made HDFC Bank skip its industry."""
    assert P.screener_value("industry", "Banks - Regional") == "Banks—Regional"
    assert P.screener_value("industry", "Information Technology Services") == \
        "Information Technology Services"
    assert P.screener_value("industry", "Not A Real Industry") is None
    assert P.screener_value("sector", "Technology") == "Technology"


# --------------------------------------------------------------------------
# Rows
# --------------------------------------------------------------------------

def test_row_from_info_translates_statement_currency():
    info = {"currentPrice": 1000.0, "marketCap": 4e12, "ebitda": 4e9,
            "totalRevenue": 20e9, "totalDebt": 1e9, "totalCash": 4e9,
            "trailingPE": 14.0, "currency": "INR", "shortName": "Foo"}
    row = P.row_from_info("foo.ns", info, fx=95.0)
    assert row["ticker"] == "FOO.NS"
    assert row["ev_ebitda"] == pytest.approx((4e12 - 3e9 * 95) / (4e9 * 95))
    assert 5 < row["ev_ebitda"] < 15


def test_row_from_info_needs_a_price_and_a_market_cap():
    assert P.row_from_info("X", {"marketCap": 1e9}) is None
    assert P.row_from_info("X", {"currentPrice": 5.0}) is None


# --------------------------------------------------------------------------
# Summary statistics
# --------------------------------------------------------------------------

def test_summary_median_and_quartiles():
    rows = [_peer(pe) for pe in (10, 12, 14, 16, 18)]
    s = P.summarize(rows)["pe"]
    assert s["median"] == 14 and s["n"] == 5
    assert s["q1"] == 12 and s["q3"] == 16


def test_median_resists_an_extreme_peer():
    rows = [_peer(pe) for pe in (10, 12, 14, 16, 250)]
    assert P.summarize(rows)["pe"]["median"] == 14       # mean would be ~60


def test_negative_and_absurd_multiples_are_excluded():
    rows = [_peer(pe) for pe in (10, 12, 14, -8, 5000)]
    s = P.summarize(rows)["pe"]
    assert s["n"] == 3 and s["median"] == 12


def test_too_few_peers_means_no_statistic_rather_than_a_bad_one():
    s = P.summarize([_peer(10), _peer(12)])["pe"]
    assert s["median"] is None and s["n"] == 2


def test_premium_and_discount():
    assert P.premium(15.0, 20.0) == pytest.approx(-0.25)
    assert P.premium(30.0, 20.0) == pytest.approx(0.5)
    assert P.premium(None, 20.0) is None
    assert P.premium(15.0, None) is None


# --------------------------------------------------------------------------
# What the multiples imply
# --------------------------------------------------------------------------

def test_pe_implied_value_scales_the_price():
    """Peers on 30x, company on 20x at a price of 100: earnings are 5 a
    share, so 30x earnings is 150."""
    rows = [_peer(pe) for pe in (24, 27, 30, 33, 36)]
    iv = {r["key"]: r for r in P.implied_values(_co(rows), P.summarize(rows))}
    assert iv["pe"]["mid"] == pytest.approx(150.0)
    assert iv["pe"]["vs_price"] == pytest.approx(0.5)
    assert iv["pe"]["low"] == pytest.approx(135.0)       # q1 27x
    assert iv["pe"]["high"] == pytest.approx(165.0)      # q3 33x


def test_book_value_implied_value():
    rows = [_peer(20, pb=pb) for pb in (3, 4, 5, 6, 7)]
    iv = {r["key"]: r for r in P.implied_values(_co(rows), P.summarize(rows))}
    assert iv["pb"]["mid"] == pytest.approx(100.0 * 5 / 4)


def test_ev_ebitda_bridges_to_equity_with_net_debt():
    """12x on EBITDA of 10,000 is an EV of 120,000. The company holds 10,000
    of net cash, so equity is 130,000 over 1,000 shares: 130 a share."""
    rows = [_peer(20, eveb=m) for m in (10, 11, 12, 13, 14)]
    iv = {r["key"]: r for r in P.implied_values(_co(rows), P.summarize(rows))}
    assert iv["ev_ebitda"]["mid"] == pytest.approx(130.0)


def test_ev_sales_implied_value():
    rows = [_peer(20, evs=m) for m in (1, 1.5, 2, 2.5, 3)]
    iv = {r["key"]: r for r in P.implied_values(_co(rows), P.summarize(rows))}
    assert iv["ev_sales"]["mid"] == pytest.approx((2 * 45_000 + 10_000) / 1000)


def test_a_lender_gets_no_enterprise_value_methods():
    rows = [_peer(20) for _ in range(5)]
    c = _co(rows)
    keys = {r["key"] for r in P.implied_values(c, P.summarize(rows), skip_ev=True)}
    assert keys == {"pe", "fwd_pe", "pb"}


def test_a_negative_implied_value_is_dropped_not_displayed(company):
    """TTML: debt exceeds what any peer multiple supports, so the 'value per
    share' is negative. Printing a negative share price helps nobody."""
    company.total_debt = 500_000.0
    rows = [_peer(20, eveb=m) for m in (10, 11, 12, 13, 14)]
    keys = {r["key"] for r in P.implied_values(company, P.summarize(rows))}
    assert "ev_ebitda" not in keys


def test_a_loss_maker_has_no_pe_implied_value(company):
    company.stats["pe"] = None
    rows = [_peer(pe) for pe in (24, 27, 30, 33, 36)]
    keys = {r["key"] for r in P.implied_values(company, P.summarize(rows))}
    assert "pe" not in keys


def _co(rows):
    c = sample_company()
    c.price, c.shares_out, c.market_cap = 100.0, 1000.0, 100_000.0
    c.total_debt, c.cash = 5_000.0, 15_000.0
    c.stats = {"pe": 20.0, "fwd_pe": 18.0, "pb": 4.0, "ebitda": 10_000.0,
               "revenue_ttm": 45_000.0}
    return c


# --------------------------------------------------------------------------
# Loading with a fallback
# --------------------------------------------------------------------------

def test_falls_back_to_the_saved_peer_set_when_yahoo_fails(tmp_path, monkeypatch, company):
    monkeypatch.setattr(P, "PEER_DIR", tmp_path)
    P.save_peer_snapshot(company.ticker, {"method": "saved", "rows": [_peer(10)],
                                          "fetched_at": "2026-01-01"})

    def boom(*a, **k):
        raise ConnectionError("offline")
    monkeypatch.setattr(P, "find_peers", boom)
    got = P.load_peer_set(company)
    assert got["source"] == "snapshot" and len(got["rows"]) == 1


def test_no_network_and_no_snapshot_returns_empty_not_an_exception(tmp_path, monkeypatch, company):
    monkeypatch.setattr(P, "PEER_DIR", tmp_path)
    monkeypatch.setattr(P, "find_peers", lambda *a, **k: ([], ""))
    got = P.load_peer_set(company)
    assert got["rows"] == [] and got["source"] == "none"


def test_a_custom_list_excludes_the_company_itself(monkeypatch, company):
    seen = {}

    def fake_fetch(symbols, max_workers=4):
        seen["symbols"] = symbols
        return [_peer(10)]
    monkeypatch.setattr(P, "fetch_rows", fake_fetch)
    P.load_peer_set(company, [company.ticker, "tcs.ns", " wipro.ns "])
    assert seen["symbols"] == ["TCS.NS", "WIPRO.NS"]


def test_sample_peers_have_the_same_shape_as_live_ones():
    ps = sample_peer_set()
    assert ps["source"] == "sample" and len(ps["rows"]) >= 5
    s = P.summarize(ps["rows"])
    assert s["pe"]["median"] and s["ev_ebitda"]["median"]
