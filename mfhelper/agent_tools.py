"""Agent tools providing clean financial analytics interfaces for MCP and CLI chat."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mfhelper.config import AlertRulesConfig, load_alert_settings, load_funds, resolve_config_path
from mfhelper.metrics import distance_from_200d_sma, distance_from_52w_high, rsi as compute_rsi
from mfhelper.mfapi import fetch_history
from mfhelper.returns_calc import risk_adjusted, risk_metrics, trailing_returns

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"


def _default_alert_rules() -> AlertRulesConfig:
    """Fallback default alert rules when alerts.yaml is unavailable."""
    return AlertRulesConfig(
        rsi_mild_pullback=55.0,
        rsi_moderate_dip=45.0,
        rsi_deep_oversold=35.0,
        rsi_overbought=70.0,
        sma_trend_support_pct=2.0,
        sma_moderate_discount_pct=-2.0,
        sma_deep_capitulation_pct=-10.0,
        discount_mild_pct=-5.0,
        discount_moderate_pct=-10.0,
        discount_deep_pct=-20.0,
        enable_sma_crossing=True,
    )


def fetch_fund_metrics_summary(scheme_code: str) -> dict[str, Any]:
    """Fetch NAV, key technical indicators, and trailing returns for an AMFI scheme."""
    code = str(scheme_code).strip()
    result = fetch_history(code)
    if result is None:
        return {
            "status": "error",
            "message": f"No NAV history found from mfapi.in for scheme code '{code}'.",
        }

    history = result.history
    if not history:
        return {
            "status": "error",
            "message": f"History data is empty for scheme code '{code}'.",
        }

    latest = history[0]
    current_nav = latest.nav
    current_date = latest.nav_date

    dist_52w = distance_from_52w_high(history, current_nav, current_date)
    dist_200d = distance_from_200d_sma(history, current_nav, current_date)
    rsi_val = compute_rsi(history, current_nav, current_date)
    raw_trailing = trailing_returns(history, current_date)

    # Normalize trailing returns dictionary so both period labels ('1M', '1Y', '3Y')
    # and engine keys ('1m_pct', '1y_absolute_pct', '3y_cagr_pct') are accessible.
    trailing = dict(raw_trailing)
    trailing.update({
        "1M": raw_trailing.get("1m_pct"),
        "3M": raw_trailing.get("3m_pct"),
        "6M": raw_trailing.get("6m_pct"),
        "1Y": raw_trailing.get("1y_absolute_pct"),
        "3Y": raw_trailing.get("3y_cagr_pct"),
        "5Y": raw_trailing.get("5y_cagr_pct"),
        "Inception": raw_trailing.get("since_inception_cagr_pct"),
    })

    return {
        "status": "success",
        "scheme_code": code,
        "scheme_name": result.scheme_name,
        "latest_nav": current_nav,
        "latest_date": current_date.isoformat(),
        "dist_52w_high_pct": dist_52w,
        "dist_200d_sma_pct": dist_200d,
        "rsi_14": rsi_val,
        "trailing_returns": trailing,
    }


def format_metrics_markdown(data: dict[str, Any]) -> str:
    """Format the fund metrics dictionary into clean readable markdown."""
    if data.get("status") != "success":
        return f"❌ {data.get('message', 'Failed to retrieve fund metrics.')}"

    dist_52w = data.get("dist_52w_high_pct")
    dist_200d = data.get("dist_200d_sma_pct")
    rsi_val = data.get("rsi_14")
    trailing = data.get("trailing_returns", {})

    dist_52w_str = f"{dist_52w:.2f}%" if dist_52w is not None else "N/A"
    dist_200d_str = f"{dist_200d:.2f}%" if dist_200d is not None else "N/A (<200 days)"
    rsi_str = f"{rsi_val:.2f}" if rsi_val is not None else "N/A (<15 days)"

    # Technical context notes
    tech_notes = []
    if rsi_val is not None:
        if rsi_val <= 35:
            tech_notes.append("🟢 Oversold RSI")
        elif rsi_val >= 70:
            tech_notes.append("🔴 Overbought RSI")
    if dist_200d is not None:
        if dist_200d > 0:
            tech_notes.append("📈 Above 200D SMA (Uptrend)")
        else:
            tech_notes.append("📉 Below 200D SMA (Downtrend/Discount)")

    notes_line = f" ({', '.join(tech_notes)})" if tech_notes else ""

    lines = [
        f"### 📊 Fund Analytics: {data.get('scheme_name')} (`{data.get('scheme_code')}`)",
        f"- **Latest NAV:** ₹{data.get('latest_nav', 0.0):.4f} *(as of {data.get('latest_date')})*",
        f"- **Distance from 52-Week High:** `{dist_52w_str}`",
        f"- **Distance from 200-Day SMA:** `{dist_200d_str}`",
        f"- **RSI (14-Day Wilder):** `{rsi_str}`{notes_line}",
        "",
        "#### 📈 Trailing Returns",
        "| Period | Return |",
        "| :--- | :--- |",
    ]

    period_labels = [
        (["1M", "1m_pct"], "1 Month (Absolute)"),
        (["3M", "3m_pct"], "3 Month (Absolute)"),
        (["6M", "6m_pct"], "6 Month (Absolute)"),
        (["1Y", "1y_absolute_pct"], "1 Year (Absolute)"),
        (["3Y", "3y_cagr_pct"], "3 Year (CAGR)"),
        (["5Y", "5y_cagr_pct"], "5 Year (CAGR)"),
        (["Inception", "since_inception_cagr_pct"], "Since Inception (CAGR)"),
    ]

    for keys, label in period_labels:
        val = None
        for k in keys:
            if trailing.get(k) is not None:
                val = trailing.get(k)
                break
        if val is not None:
            sign = "+" if val > 0 else ""
            lines.append(f"| {label} | **{sign}{val:.2f}%** |")
        else:
            lines.append(f"| {label} | - |")

    return "\n".join(lines)


def fetch_fund_overlap_summary(code_a: str, code_b: str) -> dict[str, Any]:
    """Calculate pairwise portfolio overlap % and top common stock holdings."""
    from mfhelper.overlap import (
        calculate_overlap_percentage,
        fetch_fund_holdings,
        fetch_isin_from_amfi,
        fetch_tickertape_sitemap_urls,
        get_tickertape_mappings_path,
        load_cached_mappings,
        resolve_mfid_by_isin,
        save_cached_mappings,
    )

    clean_a = str(code_a).strip()
    clean_b = str(code_b).strip()

    if clean_a == clean_b:
        return {
            "status": "error",
            "message": "Both fund scheme codes are identical. Please specify two different funds.",
        }

    try:
        code_to_isin, code_to_name = fetch_isin_from_amfi([clean_a, clean_b])
    except Exception as e:
        return {
            "status": "error",
            "message": f"Failed to retrieve ISIN mappings from AMFI directory: {e}",
        }

    isin_a = code_to_isin.get(clean_a)
    isin_b = code_to_isin.get(clean_b)

    if not isin_a or not isin_b:
        missing = []
        if not isin_a:
            missing.append(clean_a)
        if not isin_b:
            missing.append(clean_b)
        return {
            "status": "error",
            "message": f"Could not find ISIN in AMFI master for scheme code(s): {', '.join(missing)}",
        }

    name_a = code_to_name.get(clean_a, clean_a)
    name_b = code_to_name.get(clean_b, clean_b)

    mappings_path = get_tickertape_mappings_path()
    cached_mappings = load_cached_mappings(mappings_path)
    sitemap_urls: list[str] | None = None

    mfid_a = cached_mappings.get(isin_a)
    if not mfid_a:
        sitemap_urls = fetch_tickertape_sitemap_urls()
        mfid_a = resolve_mfid_by_isin(isin_a, name_a, sitemap_urls)
        if mfid_a:
            cached_mappings[isin_a] = mfid_a
            save_cached_mappings(mappings_path, cached_mappings)

    mfid_b = cached_mappings.get(isin_b)
    if not mfid_b:
        if sitemap_urls is None:
            sitemap_urls = fetch_tickertape_sitemap_urls()
        mfid_b = resolve_mfid_by_isin(isin_b, name_b, sitemap_urls)
        if mfid_b:
            cached_mappings[isin_b] = mfid_b
            save_cached_mappings(mappings_path, cached_mappings)

    if not mfid_a or not mfid_b:
        unresolved = []
        if not mfid_a:
            unresolved.append(f"{name_a} ({clean_a})")
        if not mfid_b:
            unresolved.append(f"{name_b} ({clean_b})")
        return {
            "status": "error",
            "message": f"Could not map fund to Tickertape holdings database: {', '.join(unresolved)}",
        }

    holdings_a = fetch_fund_holdings(mfid_a)
    holdings_b = fetch_fund_holdings(mfid_b)

    if not holdings_a or not holdings_b:
        return {
            "status": "error",
            "message": "Holdings data could not be fetched for one or both funds.",
        }

    overlap_pct, common_stocks = calculate_overlap_percentage(holdings_a, holdings_b)

    # Normalize holdings dictionaries so that both engine fields ('company_name', 'alloc_a',
    # 'alloc_b', 'intersection') and formatter fields ('name', 'weight_a', 'weight_b', 'min_weight')
    # are present.
    normalized_common = []
    for s in common_stocks:
        comp_name = s.get("company_name") or s.get("name", "Unknown")
        alloc_a = s.get("alloc_a") if s.get("alloc_a") is not None else s.get("weight_a", 0.0)
        alloc_b = s.get("alloc_b") if s.get("alloc_b") is not None else s.get("weight_b", 0.0)
        intersection = s.get("intersection") if s.get("intersection") is not None else s.get("min_weight", 0.0)
        ticker = s.get("ticker", "")
        normalized_common.append({
            "company_name": comp_name,
            "name": comp_name,
            "ticker": ticker,
            "alloc_a": alloc_a,
            "weight_a": alloc_a,
            "alloc_b": alloc_b,
            "weight_b": alloc_b,
            "intersection": intersection,
            "min_weight": intersection,
        })

    return {
        "status": "success",
        "fund_a": {"code": clean_a, "name": name_a, "total_holdings": len(holdings_a)},
        "fund_b": {"code": clean_b, "name": name_b, "total_holdings": len(holdings_b)},
        "overlap_pct": overlap_pct,
        "common_count": len(normalized_common),
        "common_stocks": normalized_common,
    }


def format_overlap_markdown(data: dict[str, Any]) -> str:
    """Format the overlap dictionary into clean readable markdown."""
    if data.get("status") != "success":
        return f"❌ {data.get('message', 'Failed to calculate overlap.')}"

    fa = data["fund_a"]
    fb = data["fund_b"]
    overlap_pct = data["overlap_pct"]
    common = data.get("common_stocks", [])

    lines = [
        f"### 🗺️ Portfolio Overlap Analysis",
        f"- **Fund A:** {fa['name']} (`{fa['code']}`) - {fa['total_holdings']} total holdings",
        f"- **Fund B:** {fb['name']} (`{fb['code']}`) - {fb['total_holdings']} total holdings",
        f"- **Pairwise Overlap:** **`{overlap_pct:.2f}%`**",
        f"- **Shared Stock Count:** {data['common_count']} stocks",
        "",
    ]

    if overlap_pct >= 50.0:
        lines.append("> ⚠️ **High Overlap Alert:** Over 50% of the portfolios hold identical stocks. Holding both funds may result in excessive concentration and minimal diversification.")
    elif overlap_pct >= 30.0:
        lines.append("> ℹ️ **Moderate Overlap:** Meaningful shared exposure. Review top overlapping stocks below.")
    else:
        lines.append("> ✅ **Low Overlap:** Good diversification across both portfolios.")

    lines.append("")
    lines.append("#### 🤝 Top Shared Holdings")
    lines.append(f"| Stock Name | Min Overlap Weight | {fa['name'][:20]}... % | {fb['name'][:20]}... % |")
    lines.append("| :--- | :---: | :---: | :---: |")

    top_stocks = common[:15]
    for s in top_stocks:
        name = s.get("name") or s.get("company_name", "Unknown")
        min_wt = s.get("min_weight") if s.get("min_weight") is not None else s.get("intersection", 0.0)
        wt_a = s.get("weight_a") if s.get("weight_a") is not None else s.get("alloc_a", 0.0)
        wt_b = s.get("weight_b") if s.get("weight_b") is not None else s.get("alloc_b", 0.0)
        lines.append(f"| {name} | **{min_wt:.2f}%** | {wt_a:.2f}% | {wt_b:.2f}% |")

    if len(common) > 15:
        remaining_sum = sum(
            (s.get("min_weight") if s.get("min_weight") is not None else s.get("intersection", 0.0))
            for s in common[15:]
        )
        lines.append(f"| *... and {len(common) - 15} more smaller common holdings* | *{remaining_sum:.2f}%* | - | - |")

    return "\n".join(lines)


def fetch_category_rankings(category: str) -> dict[str, Any]:
    """Rank funds in a specific category (e.g. flexicap, midcap, smallcap, multicap, gold_etfs)."""
    cat_lower = category.strip().lower().replace(" ", "_")
    cat_file = CONFIG_DIR / f"{cat_lower}.yaml"

    funds_to_analyze = []

    # A private override counts even when the public file is missing.
    resolved_file = resolve_config_path(cat_file)
    if resolved_file.exists():
        try:
            funds_to_analyze = load_funds(cat_file)
        except Exception as e:
            # The file exists but is broken. Say so, instead of pretending the category is missing
            # or quietly ranking other funds.
            log.warning("Could not load category file %s: %s", resolved_file, e)
            message = f"Could not load category '{category}' from {resolved_file.name}: {e}"
            if resolved_file == cat_file:
                message += (
                    f" If this is the public template, copy it to {cat_file.stem}.private{cat_file.suffix} "
                    "and add your AMFI scheme codes."
                )
            return {"status": "error", "message": message}

    if not funds_to_analyze:
        # Fallback: search main funds.yaml for matching category tag
        main_funds_file = CONFIG_DIR / "funds.yaml"
        if main_funds_file.exists():
            all_funds = load_funds(main_funds_file)
            funds_to_analyze = [
                f for f in all_funds if (f.category or "").strip().lower() == cat_lower
            ]

    if not funds_to_analyze:
        # Check what category files are actually available
        available_files = [
            p.stem for p in CONFIG_DIR.glob("*.yaml")
            if p.stem not in ("funds", "settings", "alerts", "alerts_example", "benchmarks", "analytics_funds")
            and not p.stem.endswith(".private")
        ]
        return {
            "status": "error",
            "message": f"Category '{category}' not found. Available categories with configs: {', '.join(available_files)}",
        }

    fund_stats = []
    for f in funds_to_analyze:
        res = fetch_history(f.code)
        if not res or not res.history:
            continue
        history = res.history
        latest = history[0]

        trailing = trailing_returns(history, latest.nav_date)
        risk = risk_metrics(history, as_of=latest.nav_date)
        adjusted = risk_adjusted(history, as_of=latest.nav_date)

        fund_stats.append({
            "code": f.code,
            "name": f.name or res.scheme_name,
            "nav": latest.nav,
            "nav_date": latest.nav_date.isoformat(),
            "cagr_1y": trailing.get("1y_absolute_pct") if trailing.get("1y_absolute_pct") is not None else trailing.get("1Y"),
            "cagr_3y": trailing.get("3y_cagr_pct") if trailing.get("3y_cagr_pct") is not None else trailing.get("3Y"),
            "cagr_5y": trailing.get("5y_cagr_pct") if trailing.get("5y_cagr_pct") is not None else trailing.get("5Y"),
            "sd_3y": risk.get("sd_3y_annualized_pct"),
            "sharpe_3y": adjusted.get("sharpe_3y"),
            "sortino_3y": adjusted.get("sortino_3y"),
            "calmar_3y": adjusted.get("calmar_3y"),
        })

    if not fund_stats:
        return {
            "status": "error",
            "message": f"Could not fetch historical data for funds in category '{category}'.",
        }

    # Rank primarily by Sharpe 3Y (or 3Y CAGR if Sharpe is None)
    def rank_key(item: dict[str, Any]) -> float:
        if item.get("sharpe_3y") is not None:
            return float(item["sharpe_3y"])
        if item.get("cagr_3y") is not None:
            return float(item["cagr_3y"])
        return -999.0

    fund_stats.sort(key=rank_key, reverse=True)

    return {
        "status": "success",
        "category": category,
        "count": len(fund_stats),
        "rankings": fund_stats,
    }


def format_rankings_markdown(data: dict[str, Any]) -> str:
    """Format category rankings into a clean markdown table."""
    if data.get("status") != "success":
        return f"❌ {data.get('message', 'Failed to retrieve category rankings.')}"

    category = data.get("category", "")
    rankings = data.get("rankings", [])

    lines = [
        f"### 🏆 Category Rankings: {category.upper()}",
        f"Ranked by Risk-Adjusted Efficiency (3-Year Sharpe & Return):",
        "",
        "| Rank | Fund Name | 1Y CAGR | 3Y CAGR | 5Y CAGR | Sharpe 3Y | Volatility (SD) |",
        "| :---: | :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    for idx, f in enumerate(rankings, 1):
        c1 = f"{f['cagr_1y']:.2f}%" if f.get("cagr_1y") is not None else "-"
        c3 = f"{f['cagr_3y']:.2f}%" if f.get("cagr_3y") is not None else "-"
        c5 = f"{f['cagr_5y']:.2f}%" if f.get("cagr_5y") is not None else "-"
        sh = f"{f['sharpe_3y']:.2f}" if f.get("sharpe_3y") is not None else "-"
        sd = f"{f['sd_3y']:.2f}%" if f.get("sd_3y") is not None else "-"
        badge = "🥇" if idx == 1 else ("🥈" if idx == 2 else ("🥉" if idx == 3 else f"#{idx}"))
        lines.append(f"| {badge} | **{f['name']}** (`{f['code']}`) | {c1} | {c3} | {c5} | **{sh}** | {sd} |")

    return "\n".join(lines)


def screen_dip_and_trim_opportunities(
    funds_path: Path | None = None,
    alerts_path: Path | None = None,
) -> dict[str, Any]:
    """Scan configured funds for active confluence dip-buying and trimming signals."""
    from mfhelper.alerts import check_confluence_signal, check_trimming_signal

    f_path = funds_path or (CONFIG_DIR / "funds.yaml")
    a_path = resolve_config_path(alerts_path or (CONFIG_DIR / "alerts.yaml"))

    if not f_path.exists():
        return {
            "status": "error",
            "message": f"Funds configuration not found at: {f_path}",
        }

    try:
        funds = load_funds(f_path)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error loading funds file: {e}",
        }

    rules = _default_alert_rules()
    if a_path.exists():
        try:
            alerts_cfg = load_alert_settings(a_path)
            rules = alerts_cfg.rules
        except Exception as e:
            log.warning("Could not load alerts config %s: %s; using defaults.", a_path, e)

    dip_signals = []
    trim_signals = []
    scanned_count = 0
    active_evaluated_count = 0
    failed_funds = []
    skipped_funds = []

    for f in funds:
        scanned_count += 1
        if not f.active:
            skipped_funds.append({"code": f.code, "name": f.name, "reason": "Inactive"})
            continue
        # Skip debt funds for equity confluence signals
        if (f.category or "").strip().lower() in ("debt", "liquid", "arbitrage"):
            skipped_funds.append({"code": f.code, "name": f.name, "reason": f"Non-equity category: {f.category}"})
            continue

        res = fetch_history(f.code)
        if not res or not res.history:
            failed_funds.append({
                "code": f.code,
                "name": f.name or f"Scheme {f.code}",
                "reason": "NAV history could not be retrieved from mfapi.in",
            })
            continue

        active_evaluated_count += 1
        history = res.history
        latest = history[0]
        current_nav = latest.nav
        current_date = latest.nav_date

        dist_52w = distance_from_52w_high(history, current_nav, current_date)
        dist_200d = distance_from_200d_sma(history, current_nav, current_date)
        rsi_val = compute_rsi(history, current_nav, current_date)

        dip_sig = check_confluence_signal(
            scheme_code=f.code,
            fund_name=f.name or res.scheme_name,
            current_rsi=rsi_val,
            current_dist_52w=dist_52w,
            current_dist_200d_sma=dist_200d,
            rules=rules,
        )
        if dip_sig:
            dip_signals.append({
                "scheme_code": dip_sig.scheme_code,
                "fund_name": dip_sig.fund_name,
                "tier": dip_sig.tier,
                "reasons": dip_sig.reasons,
                "suggestion": dip_sig.suggestion,
                "groww_link": dip_sig.groww_link,
            })

        trim_sig = check_trimming_signal(
            scheme_code=f.code,
            fund_name=f.name or res.scheme_name,
            current_rsi=rsi_val,
            current_dist_52w=dist_52w,
            rules=rules,
        )
        if trim_sig:
            trim_signals.append({
                "scheme_code": trim_sig.scheme_code,
                "fund_name": trim_sig.fund_name,
                "tier": trim_sig.tier,
                "reasons": trim_sig.reasons,
                "suggestion": trim_sig.suggestion,
                "groww_link": trim_sig.groww_link,
            })

    # Sort dip signals by Tier descending (Tier 3 highest priority)
    dip_signals.sort(key=lambda s: s["tier"], reverse=True)
    trim_signals.sort(key=lambda s: s["tier"], reverse=True)

    if active_evaluated_count == 0:
        return {
            "status": "error",
            "message": f"Could not retrieve NAV history for any active fund ({len(failed_funds)} failed).",
            "scanned_count": scanned_count,
            "active_evaluated_count": 0,
            "failed_funds": failed_funds,
            "skipped_funds": skipped_funds,
            "dip_signals": [],
            "trim_signals": [],
        }

    return {
        "status": "success",
        "scanned_count": scanned_count,
        "active_evaluated_count": active_evaluated_count,
        "failed_funds": failed_funds,
        "skipped_funds": skipped_funds,
        "dip_signals": dip_signals,
        "trim_signals": trim_signals,
    }


def format_screen_markdown(data: dict[str, Any]) -> str:
    """Format dip and trim opportunity scanner results into clean markdown."""
    if data.get("status") != "success":
        failed = data.get("failed_funds", [])
        failed_str = ""
        if failed:
            failed_list = ", ".join([f"{f.get('name') or f.get('code')} (`{f.get('code')}`)" for f in failed])
            failed_str = f"\n\nFailed funds: {failed_list}"
        return f"❌ {data.get('message', 'Failed to scan opportunities.')}{failed_str}"

    dips = data.get("dip_signals", [])
    trims = data.get("trim_signals", [])
    active_count = data.get("active_evaluated_count", 0)
    failed_funds = data.get("failed_funds", [])

    lines = [
        f"### 🎯 Tactical Market Confluence Scanner",
        f"Evaluated **{active_count} active funds** against multi-indicator confluence thresholds.",
        "",
    ]

    if failed_funds:
        failed_names = ", ".join([f"{f.get('name') or f.get('code')} (`{f.get('code')}`)" for f in failed_funds])
        lines.append(f"> ⚠️ **Warning:** Could not retrieve data for {len(failed_funds)} fund(s): {failed_names}. These were skipped.")
        lines.append("")

    if not dips and not trims:
        lines.append("✅ **No extreme dip or trim confluences detected today.**")
        lines.append("All tracked funds are trading in normal equilibrium ranges. Standard SIP schedules should continue uninterrupted.")
        return "\n".join(lines)

    dips = data.get("dip_signals", [])
    trims = data.get("trim_signals", [])
    active_count = data.get("active_evaluated_count", 0)

    lines = [
        f"### 🎯 Tactical Market Confluence Scanner",
        f"Evaluated **{active_count} active funds** against multi-indicator confluence thresholds.",
        "",
    ]

    if not dips and not trims:
        lines.append("✅ **No extreme dip or trim confluences detected today.**")
        lines.append("All tracked funds are trading in normal equilibrium ranges. Standard SIP schedules should continue uninterrupted.")
        return "\n".join(lines)

    if dips:
        lines.append("#### 🟢 Active Dip-Buying Confluences (Opportunity Alerts)")
        for d in dips:
            tier_badge = "🔥 Tier-3 Generational Dip" if d["tier"] == 3 else ("⚡ Tier-2 Moderate Buy" if d["tier"] == 2 else "🌱 Tier-1 Mild Pullback")
            lines.append(f"##### {tier_badge}: **{d['fund_name']}** (`{d['scheme_code']}`)")
            lines.append(f"- **Triggers:** {', '.join(d['reasons'])}")
            lines.append(f"- **Recommendation:** {d['suggestion']}")
            lines.append(f"- [Direct Buy on Groww]({d['groww_link']})")
            lines.append("")

    if trims:
        lines.append("#### 🔴 Active Overbought Trimming Warnings (Risk Reduction)")
        for t in trims:
            tier_badge = "🚨 Tier-3 Urgent Climax Peak" if t["tier"] == 3 else ("⚠️ Tier-2 Overbought Warning" if t["tier"] == 2 else "🔔 Tier-1 Mild Momentum")
            lines.append(f"##### {tier_badge}: **{t['fund_name']}** (`{t['scheme_code']}`)")
            lines.append(f"- **Triggers:** {', '.join(t['reasons'])}")
            lines.append(f"- **Recommendation:** {t['suggestion']}")
            lines.append(f"- [View Fund on Groww]({t['groww_link']})")
            lines.append("")

    return "\n".join(lines)
