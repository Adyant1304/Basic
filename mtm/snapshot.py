"""Save companies to disk so a demo never depends on the network.

    python -m mtm.snapshot INFY.NS HCLTECH.NS WIPRO.NS TCS.NS

Run it once on a working connection. The app then falls back to these files
automatically whenever Yahoo is unreachable, which is what you want five
minutes before a presentation on campus wifi.
"""

from __future__ import annotations

import sys

from .data import SNAPSHOT_DIR, fetch, save_snapshot


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1

    ok, failed = 0, 0
    for ticker in argv:
        try:
            c = fetch(ticker, write_snapshot=False)
            path = save_snapshot(c)
            print(f"  saved  {c.ticker:<14} {c.name[:40]:<42} -> {path.name}")
            if c.warnings:
                for w in c.warnings:
                    print(f"         note: {w}")
            ok += 1
        except Exception as exc:
            print(f"  FAILED {ticker:<14} {type(exc).__name__}: {exc}")
            failed += 1

    print(f"\n{ok} saved, {failed} failed, in {SNAPSHOT_DIR}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
