# Proposal: CLI Segregated Runs for Local Testing

## 1. Objective
Introduce a dedicated CLI command-line flag `--dev` to `main.py` that separates local test executions from your live scheduled production database inside your Google Sheet. 

---

## 2. Background & Need
Currently, both your manual local runs on your Mac and the scheduled automatic runs on GitHub Actions write directly to the same **`Daily NAV`** worksheet tab in your Google Sheet. This results in duplicate rows and cluttered testing data in your live production logs.

By introducing the `--dev` CLI flag:
1. **Database Isolation:** When running with the `--dev` flag, the script will automatically redirect its output to an isolated tab named **`Daily NAV (Dev)`**.
2. **Email Safety:** The script will prefix any sent alert emails with **`[DEV]`** in the subject line, ensuring they are never confused with real daily production briefings.
3. **Implicit Safety:** The production scheduled GitHub Actions runner will continue running without the flag, ensuring only real scheduled data updates the live production sheet.

---

## 3. Scope & Exclusions
* **Argument Parser:** Integrate `argparse` in `main.py` to accept the `--dev` boolean flag.
* **Dynamic Worksheet Selection:** Redirect the target tab from `Daily NAV` to `Daily NAV (Dev)` dynamically when `--dev` is active.
* **Subject Line Prefixing:** Modify `dispatch_alerts_email` in `mfhelper/alerts.py` to optionally accept an `is_dev` parameter and prefix emails accordingly.
