# Proposal: GitHub Actions Scheduled daily NAV Workflow

## 1. Objective
Migrate the daily scheduled NAV tracking and indicator alert job from local macOS `launchd` to **GitHub Actions scheduled workflows**. This guarantees ultra-reliable daily executions on a free, cloud-hosted runner, independent of whether the user's local Mac is turned on, connected to the internet, or awake.

---

## 2. Background & Need
The current macOS `launchd` daily job (set at 10:30 AM IST) relies on the local Mac being awake and connected to the internet. If the Mac is asleep or experiences any Wi-Fi reconnection latency upon waking, the daily job can hang or fail entirely.

By hosting the schedule on Google's or Microsoft's infrastructure via GitHub Actions, we get:
1. **Perpetual Cloud Execution:** Runs daily at the exact scheduled time without local computer dependencies.
2. **Zero Resource Overhead:** Executing `main.py` takes less than 15 seconds, utilizing less than 0.5% of GitHub's free 2,000-minute monthly tier.
3. **Automated Error Logging:** If a run fails due to AMFI delay, GitHub automatically logs and notifies the user with precise stack traces.

---

## 3. Scope & Exclusions
* **Secure Secret Management:** Securely load and configure sensitive inputs (`credentials.json`, `token.json`, and `alerts.yaml`) utilizing encrypted **GitHub Actions Repository Secrets** rather than committing them to the repository.
* **Scheduling Accuracy:** Run automatically once daily at **10:30 AM IST** (using UTC cron syntax `0 5 * * *`).
* **Environment Setup:** Automatically provision a clean Ubuntu virtual machine, install Python dependencies, inject secret files, execute `main.py`, and tear down securely.
