"""Show the current market regime and valuation context.

Read-only: it fetches NIFTY 500 / India VIX / Nifty 50 P/E and prints what the daily
run would use. It never touches Google Sheets, sends email, or changes state files
(other than refreshing the market-data cache in data/market_context/).

    python regime_main.py             # today's context
    python regime_main.py --history 15   # also the last 15 sessions
"""

from __future__ import annotations

import argparse
from datetime import date
import logging
from pathlib import Path
import sys

from mfhelper.config import load_alert_settings
from mfhelper.market_regime import (
    REGIME_STANCE,
    banner_text,
    build_market_context,
    load_series,
    regime_history,
)

PROJECT_ROOT = Path(__file__).resolve().parent
ALERTS_PATH = PROJECT_ROOT / "config" / "alerts.yaml"
CACHE_DIR = PROJECT_ROOT / "data" / "market_context"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--history", type=int, default=0, metavar="N", help="also show the last N sessions")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    settings = load_alert_settings(ALERTS_PATH)
    cfg = settings.regime
    print(
        f"Switches in alerts.yaml: regime.enable (advice on alerts) = {cfg.enable}, "
        f"regime.record_to_sheet (daily row in the '{cfg.sheet_name}' tab) = {cfg.record_to_sheet}\n"
    )

    context = build_market_context(cfg, cache_dir=CACHE_DIR)
    print(banner_text(context))
    if context.available:
        print(f"\nRegime : {context.regime.value} - {REGIME_STANCE[context.regime]}")
        print(f"As of  : {context.as_of}")
        print(f"Index  : {context.index_close:,.2f}  (50D SMA {context.sma_short:,.2f}, 200D SMA {context.sma_long:,.2f})")
        vix = f"{context.vix_avg:.2f}" if context.vix_avg is not None else "n/a"
        print(f"VIX avg: {vix}  (UPTREND < {cfg.vix_low:g}, CORRECTION >= {cfg.vix_high:g})")

    if args.history > 0 and context.available:
        today = date.today()
        index = load_series(cfg.index_ticker, cache_dir=CACHE_DIR, today=today)
        vix = load_series(cfg.vix_ticker, cache_dir=CACHE_DIR, today=today)
        print(f"\n{'Date':<12}{'Index':>12}{'VIX avg':>9}  Regime")
        for row in regime_history(index, vix, cfg, args.history):
            vix_text = f"{row.vix_avg:.2f}" if row.vix_avg is not None else "n/a"
            print(f"{row.day.isoformat():<12}{row.index_close:>12,.2f}{vix_text:>9}  {row.regime.value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
