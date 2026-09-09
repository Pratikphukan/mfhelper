# Proposal: "Mute" Inactive Funds via Configuration

## 1. Objective
Introduce an optional **"Mute" Flag (`active: false`)** inside your fund configurations in `config/funds.yaml`. If a fund is flagged as inactive, the daily scheduled NAV job will completely ignore it—skipping its NAV downloads, metric calculations, and alerting. It preserves the historical columns inside the Google Sheet (leaving new rows blank) to maintain clean accounting audits without any active noise.

---

## 2. Background & Need
When you completely redeem your holdings in a mutual fund, you no longer want to track its daily NAV movements, calculate its technical indicators, or receive buy/sell alerts and briefing emails for it.

However, physically deleting the fund from `funds.yaml` causes an alignment error with your Google Sheet because the column headers in the sheet will still exist. Deleting columns manually is brittle and can lead to data loss.

By introducing the `active: false` flag:
1. **Zero Maintenance Silence:** You can "silence" any fund in 1 second.
2. **Preserves History:** The historical columns and past data cells remain untouched in your sheet, ensuring your historical net worth audits and rolling graphs remain fully functional.
3. **No Active Clutter:** The active daily tracker loop skips the fund entirely, eliminating any unwanted alert noise from your morning emails.

---

## 3. Scope & Exclusions
* **Extended Schema:** Update `FundConfig` and `load_funds` inside `mfhelper/config.py` to support an optional boolean `active:` field (defaulting to `True` if omitted so all existing files are fully backwards-compatible!).
* **Ignored Active Processing:** Update `main.py`'s daily tracking loop to verify if `fund.active` is `True` before downloading or processing NAVs/alerts.
* **Blank Writing in Sheets:** Ensure that if a fund is inactive, its columns are safely preserved but receive blank values in the newly appended daily row.
