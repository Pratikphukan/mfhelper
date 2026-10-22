"""Gold ETF Analytics CLI (one-shot analyzer).

Tracks performance, volatility, Sharpe/Sortino/Calmar ratios, and drawdowns
across top Indian Gold ETFs listed in ``config/gold_etfs.yaml``.

Run on demand:

    .venv/bin/python gold_etf_main.py

Exit codes:
  0  Success
  2  Configuration error
  3  Unhandled exception.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
import yaml

from mfhelper.config import load_settings
from mfhelper.mfapi import fetch_history
from mfhelper.returns_calc import compute_fund_returns

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

GOLD_ETFS_PATH_DEFAULT = CONFIG_DIR / "gold_etfs.yaml"
SETTINGS_PATH = CONFIG_DIR / "settings.yaml"


def _configure_logging() -> None:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "mfhelper_gold_etfs.log"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    root.addHandler(file_handler)
    root.addHandler(stream_handler)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mfhelper-gold-etf",
        description="Compute Gold ETF analytics and performance ratios.",
    )
    p.add_argument(
        "--etfs",
        type=str,
        default=str(GOLD_ETFS_PATH_DEFAULT),
        help="Path to Gold ETFs YAML file (default: config/gold_etfs.yaml).",
    )
    p.add_argument(
        "--rfr",
        type=float,
        default=7.0,
        help="Risk-free rate %% for Sharpe/Sortino ratios (default: 7.0).",
    )
    return p.parse_args(argv)


def _print_gold_etf_summary(payloads: list[dict]) -> None:
    """Print clean, beautiful terminal summary tables for Gold ETFs."""
    if not payloads:
        return
        
    width = 100
    print("\n" + "=" * width)
    print("🏆 INDIAN GOLD ETFS TRAILING PERFORMANCE SUMMARY")
    print("=" * width)
    print(f"{'ETF Name':<32} | {'Ticker':<10} | {'1Y (Abs)':<9} | {'3Y (CAGR)':<10} | {'5Y (CAGR)':<10} | {'Inception':<10}")
    print("-" * width)
    for p in payloads:
        tr = p.get("trailing_returns") or {}
        name = p.get("etf_name", "?")[:30]
        ticker = p.get("ticker", "?")
        
        def f_val(val):
            return f"{val:.2f}%" if isinstance(val, (int, float)) else "n/a"
            
        y1 = f_val(tr.get("1y_absolute_pct"))
        y3 = f_val(tr.get("3y_cagr_pct"))
        y5 = f_val(tr.get("5y_cagr_pct"))
        si = f_val(tr.get("since_inception_cagr_pct"))
        print(f"{name:<32} | {ticker:<10} | {y1:<9} | {y3:<10} | {y5:<10} | {si:<10}")
    print("=" * width)

    print("\n" + "=" * width)
    print("🛡️ GOLD ETFS RISK METRICS & PERFORMANCE RATIOS (3Y Window)")
    print("=" * width)
    print(f"{'ETF Name':<32} | {'Ticker':<10} | {'Ann. SD %':<10} | {'Sharpe':<10} | {'Sortino':<10} | {'Max DD %':<10}")
    print("-" * width)
    for p in payloads:
        risk = p.get("risk") or {}
        ra = p.get("risk_adjusted") or {}
        name = p.get("etf_name", "?")[:30]
        ticker = p.get("ticker", "?")
        
        def f_val(val):
            return f"{val:.2f}%" if isinstance(val, (int, float)) else "n/a"
            
        def f_rat(val):
            return f"{val:.2f}" if isinstance(val, (int, float)) else "n/a"
            
        sd = f_val(risk.get("sd_3y_annualized_pct"))
        sharpe = f_rat(ra.get("sharpe_3y"))
        sortino = f_rat(ra.get("sortino_3y"))
        dd = f_val(risk.get("max_drawdown_pct"))
        print(f"{name:<32} | {ticker:<10} | {sd:<10} | {sharpe:<10} | {sortino:<10} | {dd:<10}")
    print("=" * width)


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    log = logging.getLogger("mfhelper.gold_etf_main")
    log.info("=== MFHelper Gold ETF Analytics run start ===")
    
    args = _parse_args(argv)
    yaml_path = Path(args.etfs)
    if not yaml_path.exists():
        log.error("Gold ETFs config file not found at: %s", yaml_path)
        return 2

    # Load YAML entries
    try:
        with yaml_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        etf_entries = raw.get("etfs") or []
    except Exception as e:
        log.error("Failed to parse YAML file %s: %s", yaml_path, e)
        return 2

    if not etf_entries:
        log.error("No Gold ETF entries configured under 'etfs:' in %s", yaml_path)
        return 2

    successful_payloads = []
    
    for entry in etf_entries:
        code = str(entry.get("code", "")).strip()
        ticker = str(entry.get("ticker", "")).strip()
        name = str(entry.get("name", "")).strip()
        
        if not code:
            continue
            
        log.info("Processing Gold ETF: %s (%s, code: %s)...", name, ticker, code)
        mfapi_result = fetch_history(code)
        
        if mfapi_result is None or not mfapi_result.history:
            log.warning("Could not fetch history for Gold ETF %s (code %s)", name, code)
            continue
            
        sections = compute_fund_returns(mfapi_result.history, risk_free_rate_pct=args.rfr)
        
        payload = {
            "code": code,
            "ticker": ticker,
            "etf_name": name,
            **sections
        }
        successful_payloads.append(payload)

    if not successful_payloads:
        log.error("Failed to compute analytics for any configured Gold ETFs.")
        return 2

    # Print summary tables to terminal
    _print_gold_etf_summary(successful_payloads)
    log.info("Gold ETF Analytics completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
