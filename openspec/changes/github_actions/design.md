# Design: GitHub Actions Scheduled daily NAV Workflow

## 1. System Topology & Data Flow

```
┌────────────────────────────────────────────────────────┐
│            GitHub Actions Scheduled Trigger            │
│               - Cron: '0 5 * * *' (10:30 AM IST)       │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Ubuntu Runner Spins Up)
┌────────────────────────────────────────────────────────┐
│             Secure Secrets Reconstruction              │
│   Reconstructs ignored configs from repository secrets:│
│   - secrets.GCP_CREDENTIALS_JSON -> config/credentials.json
│   - secrets.GCP_TOKEN_JSON       -> data/token.json    │
│   - secrets.ALERTS_YAML          -> config/alerts.yaml │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ (Install Python & pip deps)
┌────────────────────────────────────────────────────────┐
│                 Run Python Scheduler                   │
│   - Executes: python main.py                           │
│   - Environment loads secrets.EMAIL_PASSWORD           │
└───────────────────────────┬────────────────────────────┘
                            │
                            ├──────────────────────────┐
                            ▼                          ▼
              ┌──────────────────────────┐┌─────────────────────────┐
              │  Updates Google Sheet   ││   Dispatches SMTP Email │
              │      "Daily NAV"         ││     Alert Digest        │
              └──────────────────────────┘└─────────────────────────┘
```

---

## 2. GitHub Actions Secrets Schema

To prevent checking private credentials into Git, we leverage GitHub's encrypted Repository Secrets. 

### Secrets to configure under GitHub Settings -> Secrets -> Actions:

| Secret Name | Data Type | Encoding / Format | Purpose |
| :--- | :--- | :--- | :--- |
| **`GCP_CREDENTIALS_JSON`** | Base64 String | Base64 encoded string of `config/credentials.json` | Authenticates with the Google Sheets API. |
| **`GCP_TOKEN_JSON`** | Base64 String | Base64 encoded string of `data/token.json` | Stores the active OAuth refresh token. |
| **`ALERTS_YAML`** | Raw Text | Raw string content of your local `config/alerts.yaml` | Holds alert rules and SMTP configuration. |
| **`EMAIL_PASSWORD`** | Raw Text | Raw 16-character App password string | Standard SMTP sender password. |

---

## 3. Workflow Specification File (`.github/workflows/daily_nav.yml`)

The YAML file is placed inside the `.github/workflows/` directory:

```yaml
name: Daily NAV & Technical Alerts Scheduler

on:
  schedule:
    # 5:00 AM UTC translates precisely to 10:30 AM IST
    - cron: '0 5 * * *'
  workflow_dispatch: # Allows triggering the run manually from the GitHub UI

jobs:
  run-scheduler:
    runs-on: ubuntu-latest

    steps:
    - name: Check out repository
      uses: actions/checkout@v4

    - name: Set up Python
      uses: actions/setup-python@v5
      with:
        python-version: '3.11'
        cache: 'pip'

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name: Reconstruct Secure Config Files
      run: |
        mkdir -p config data
        echo "${{ secrets.GCP_CREDENTIALS_JSON }}" | base64 -d > config/credentials.json
        echo "${{ secrets.GCP_TOKEN_JSON }}" | base64 -d > data/token.json
        echo "${{ secrets.ALERTS_YAML }}" > config/alerts.yaml

    - name: Run Daily NAV Tracker
      env:
        EMAIL_PASSWORD: ${{ secrets.EMAIL_PASSWORD }}
      run: |
        python main.py
```
