"""Beta is the number the professor objected to, so it is tested properly.

The regression has to recover a known beta from data built to have one, and
it has to refuse to produce a number when the data cannot support it.
"""

import numpy as np
import pytest

from mtm import beta as B


def _market(n=300, seed=1):
    return np.random.default_rng(seed).normal(0.002, 0.025, n)


def test_recovers_a_known_beta_from_noisy_data():
    m = _market(600)
    rng = np.random.default_rng(2)
    s = 0.001 + 1.35 * m + rng.normal(0, 0.012, m.size)
    est = B.regress(s, m)
    assert est is not None
    assert est.beta == pytest.approx(1.35, abs=0.08)
    assert est.n == 600
    lo, hi = est.ci95
    assert lo < 1.35 < hi                    # the interval should cover the truth


def test_noise_free_data_gives_the_exact_beta():
    m = _market()
    est = B.regress(0.8 * m, m)
    assert est.beta == pytest.approx(0.8)
    assert est.r2 == pytest.approx(1.0)
    assert est.se == pytest.approx(0.0, abs=1e-9)


def test_negative_beta_is_reported_as_negative():
    """A genuinely countercyclical stock must not be forced positive."""
    m = _market()
    est = B.regress(-0.4 * m, m)
    assert est.beta == pytest.approx(-0.4)


def test_beta_is_the_covariance_over_the_variance():
    m = _market()
    rng = np.random.default_rng(5)
    s = 0.6 * m + rng.normal(0, 0.02, m.size)
    est = B.regress(s, m)
    expected = np.cov(s, m, ddof=1)[0, 1] / np.var(m, ddof=1)
    assert est.beta == pytest.approx(expected)


def test_refuses_a_short_history():
    m = _market(B.MIN_OBS - 1)
    assert B.regress(m * 1.2, m) is None


def test_refuses_a_flat_market():
    assert B.regress(_market(100), np.zeros(100)) is None


def test_ignores_missing_observations():
    m = _market(200)
    s = 1.1 * m
    s[10] = np.nan
    m2 = m.copy()
    m2[50] = np.nan
    est = B.regress(s, m2)
    assert est.n == 198
    assert est.beta == pytest.approx(1.1)


def test_estimate_from_price_levels():
    """Prices in, returns out: the same answer as regressing on returns."""
    m = _market(260)
    s = 0.9 * m + np.random.default_rng(3).normal(0, 0.01, m.size)
    px_s = 100 * np.concatenate([[1.0], np.cumprod(1 + s)])
    px_m = 20000 * np.concatenate([[1.0], np.cumprod(1 + m)])
    est = B.estimate_from_prices(px_s, px_m)
    assert est.beta == pytest.approx(B.regress(s, m).beta)


def test_blume_adjustment():
    assert B.blume(1.0) == pytest.approx(1.0)
    assert B.blume(0.0) == pytest.approx(1 / 3)
    assert B.blume(2.0) == pytest.approx(5 / 3)
    assert abs(B.blume(0.6) - 1) < abs(0.6 - 1)       # always toward 1.0


def test_bundle_and_options_round_trip():
    m = _market(300)
    est = B.regress(1.2 * m + np.random.default_rng(9).normal(0, 0.01, m.size), m)
    b = B.bundle(est, "^NSEI", "Nifty 50", "weekly", 5, 0.116, "2026-10-05")
    assert b["raw"] == pytest.approx(est.beta)
    assert b["adjusted"] == pytest.approx(B.blume(est.beta))
    assert b["yahoo"] == pytest.approx(0.116)
    opts = B.options(b)
    assert set(opts) == {"regression", "adjusted", "yahoo"}


def test_options_when_regression_failed_offers_only_yahoo():
    b = B.bundle(None, "^NSEI", "Nifty 50", "weekly", 5, 0.4)
    assert B.options(b) == {"yahoo": 0.4}
    assert B.options({}) == {}


def test_quality_note_flags_a_weak_fit_and_stays_quiet_on_a_good_one():
    weak = {"raw": 1.4, "n": 260, "r2": 0.05, "se": 0.3}
    good = {"raw": 0.9, "n": 260, "r2": 0.45, "se": 0.08}
    short = {"raw": 0.9, "n": 60, "r2": 0.45, "se": 0.08}
    assert "explains just 5%" in B.quality_note(weak)
    assert B.quality_note(good) is None
    assert "60 weekly observations" in B.quality_note(short)
    assert B.quality_note({}) is None
