"""Segment revenue: how a company's sales split across its own businesses.

Where the data comes from
-------------------------
Yahoo Finance does not publish segment revenue, so this cannot be fetched.
Segment figures live in a company's annual report and results filings, and
those are what `data/segments.json` holds: each entry carries its source,
its period and the total the filing states, so every number can be traced.

For a company that is not in the file, the Segments tab offers a small table
the user fills in from the filing's segment note. That path produces exactly
the same shape as the stored entries, so the charts do not care which one
they were given.

A *view* is one way of cutting revenue (by business, by geography). It has
one or more *periods*, newest first, each mapping segment name to a value.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "segments.json"
MAX_SLICES = 6          # a donut past six slices stops being readable


def _load_all() -> dict:
    try:
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def get_segments(ticker: str) -> dict | None:
    """The stored entry for a ticker (or one of its aliases), else None."""
    key = (ticker or "").strip().upper()
    data = _load_all()
    for name, entry in data.items():
        if name.startswith("_"):
            continue
        names = [name.upper()] + [a.upper() for a in entry.get("aliases", [])]
        if key in names:
            return entry
    return None


def covered_tickers() -> list[str]:
    """Real companies with stored segment data (not the invented sample)."""
    return [k for k, v in _load_all().items()
            if not k.startswith("_") and not v.get("illustrative")]


def shares(values: dict[str, float]) -> dict[str, float]:
    """Each segment as a fraction of the sum of the listed segments."""
    total = sum(v for v in values.values() if v and v > 0)
    if total <= 0:
        return {k: 0.0 for k in values}
    return {k: (v / total if v and v > 0 else 0.0) for k, v in values.items()}


def check_view(view: dict, tolerance: float = 0.0015) -> list[str]:
    """Problems with a view's arithmetic. Empty means it adds up.

    A filing's segments should sum to the total it states. A typo in a
    transcribed number shows up here before it reaches a chart.
    """
    problems: list[str] = []
    for p in view.get("periods", []):
        vals = p.get("values", {})
        if not vals:
            problems.append(f"{p.get('label', '?')}: no segments")
            continue
        total = p.get("total")
        got = sum(vals.values())
        if total and abs(got - total) > max(abs(total) * tolerance, 0.06):
            problems.append(
                f"{p.get('label', '?')}: segments sum to {got:,.1f} but the "
                f"stated total is {total:,.1f}")
        if any(v < 0 for v in vals.values()):
            problems.append(f"{p.get('label', '?')}: a segment is negative")
    return problems


def colour_order(view: dict) -> list[str]:
    """Segment names in the order they were first reported.

    Colour follows the entity, so a segment keeps its colour in every period
    and every chart. Ordering by size instead would repaint segments whenever
    their rank changed.
    """
    seen: list[str] = []
    for p in view.get("periods", []):
        for name in p.get("values", {}):
            if name not in seen:
                seen.append(name)
    return seen


def fold_tail(values: dict[str, float], max_n: int = MAX_SLICES
              ) -> dict[str, float]:
    """Keep the largest max_n-1 segments and fold the rest into 'Other'."""
    items = sorted(values.items(), key=lambda kv: kv[1], reverse=True)
    if len(items) <= max_n:
        return dict(items)
    head, tail = items[: max_n - 1], items[max_n - 1:]
    out = dict(head)
    out["Other segments"] = sum(v for _, v in tail)
    return out


def mix_shift(view: dict) -> list[dict]:
    """Change in share between the newest and the oldest period, in points.

    Sorted by the size of the move, because the story in a segment table is
    usually what changed rather than what is biggest.
    """
    periods = view.get("periods", [])
    if len(periods) < 2:
        return []
    new = shares(periods[0]["values"])
    old = shares(periods[-1]["values"])
    rows = []
    for name in colour_order(view):
        if name in new and name in old:
            rows.append({"segment": name, "new": new[name], "old": old[name],
                         "shift": (new[name] - old[name]) * 100})
    return sorted(rows, key=lambda r: abs(r["shift"]), reverse=True)


def view_from_rows(title: str, rows: list[tuple[str, float]],
                   unit: str = "") -> dict | None:
    """Build a view from user-typed (name, amount) rows. None if unusable."""
    clean: dict[str, float] = {}
    for name, amount in rows:
        name = (name or "").strip()
        try:
            v = float(amount)
        except (TypeError, ValueError):
            continue
        if name and math.isfinite(v) and v > 0:
            clean[name] = clean.get(name, 0.0) + v
    if len(clean) < 2:
        return None
    return {
        "title": title, "kind": "amount", "unit": unit or "your units",
        "source": "entered by you", "source_url": "", "note": "",
        "periods": [{"label": "Your entry", "detail": "", "values": clean,
                     "total": sum(clean.values())}],
    }
