# Tasks: "Mute" Inactive Funds via Configuration

This task checklist tracks the implementation of the "Mute" flag feature.

---

## 1. Task Breakdown

### Phase 1: Config Schema Extension
* [ ] Update `FundConfig` and `load_funds` inside `mfhelper/config.py` to support the optional boolean `active` field (defaulting to `True`).

### Phase 2: Active Evaluation Integration
* [ ] Update `main.py`'s daily tracking loop:
  * For each fund, check `if not fund.active`.
  * If inactive, skip AMFI index and `mfapi.in` fetches.
  * Populate `values_by_code[fund.code]` with an empty `NavValue(nav=None, day_change_pct=None, dist_52w_pct=None, dist_200d_sma_pct=None, rsi=None)`.
  * Ensure the fund is completely skipped from `check_fund_alerts` and `check_confluence_signal` (so it never triggers emails or logs).
  * Skip saving its NAV state in `new_state`.

### Phase 3: Final Verification & Push
* [ ] Flag one of your funds (e.g. `140196` Edelweiss Liquid) as `active: false` inside `config/funds.yaml`.
* [ ] Run `python main.py --dev` locally and verify that:
  * The script prints an alert suppression log.
  * It skips all downloads/alerts for Edelweiss Liquid.
  * It appends a clean new row to your `Daily NAV (Dev)` Google Sheet tab where Edelweiss Liquid's columns are left perfectly blank!
* [ ] Stage, commit, and push all final changes to the remote repository.
