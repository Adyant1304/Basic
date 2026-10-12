"""Save companies to disk so a demo never depends on the network.

    python -m mtm.snapshot INFY.NS HCLTECH.NS WIPRO.NS TCS.NS

Run it once on a working connection. The app then falls back to these files
automatically whenever Yahoo is unreachable, which is what you want five
minutes before a presentation on campus wifi. Each run saves the company and
its peer set, so the Relative value tab works offline too.
"""

from __future__ import annotations

import sys

from .data import SNAPSHOT_DIR, fetch, save_snapshot
from .peers import load_peer_set


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1

    ok, failed = 0, 0
    for ticker in argv:
        try:
            c = fetch(ticker, write_snapshot=False)
            path = save_snapshot(c)
            peers = load_peer_set(c)        # writes its own snapshot
            print(f"  saved  {c.ticker:<14} {c.name[:34]:<36} -> {path.name}"
                  f"  ({len(peers['rows'])} peers)")
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
