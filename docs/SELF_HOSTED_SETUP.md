# Set up your private MFHelper copy

Each user runs a separate private repository. Your fund list, sheet ID, OAuth files, and email settings stay in your own repository or GitHub Actions secrets; MFHelper does not collect them into a shared database.

## 1. Create a private repository

1. On the MFHelper repository page, click **Use this template** → **Create a new repository**.
2. Choose your account, enter a repository name, and select **Private**.
3. Clone your new repository and open it locally.

Template-created repositories have their own commit history and do not automatically receive upstream updates. GitHub documents this difference in [Creating a repository from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template).

If **Use this template** is not shown on the MFHelper repository page, the repository owner needs to enable **Settings → General → Template repository** after the sanitized setup has been merged.

## 2. Set your private configuration

Before enabling the workflow, edit these files in your private repository:

- `config/funds.yaml`: replace the example scheme code with the AMFI codes you want to track. Add a `name`, `category`, or `weight` when useful.
- `config/settings.yaml`: replace `PASTE_SHEET_ID_HERE` with your Google Sheet ID.
- `config/analytics_funds.yaml`: optionally set the funds for on-demand analytics.
- `config/benchmarks.yaml`: optionally add benchmark mappings for your funds.

The files in the template are examples. Replace the placeholders before turning on the schedule. Keep the repository private if you don't want your fund choices and sheet ID to be visible.

## 3. Prepare Google Sheets access

Follow the main README's OAuth setup to create a Google OAuth desktop client and create your sheet. Save the downloaded client file as `config/credentials.json` in your local clone.

Install the project dependencies in the clone first:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Run the development path once to complete OAuth and create the local token:

```bash
.venv/bin/python main.py --dev
```

This writes to the separate `Daily NAV (Dev)` sheet tab. The token is saved as `data/token.json`.

## 4. Add GitHub Actions secrets

In your private repository, open **Settings → Secrets and variables → Actions → New repository secret** and add:

- `GCP_CREDENTIALS_JSON`: base64-encoded contents of `config/credentials.json`.
- `GCP_TOKEN_JSON`: base64-encoded contents of `data/token.json`.
- `ALERTS_YAML`: base64-encoded contents of your configured `config/alerts.yaml`.
- `EMAIL_PASSWORD`: your email provider's app password, if email alerts are enabled.

On macOS, produce a single-line base64 value with `base64 < path/to/file | tr -d '\n'`. On Linux, use `base64 -w 0 path/to/file`.

`config/alerts.yaml` can be created by copying `config/alerts_example.yaml`; set the sender, receiver, and whether email alerts are enabled before encoding it. Keep the raw credentials and alert config out of commits.

## 5. Enable the daily workflow

After the fund list, sheet settings, and required secrets are ready, add this repository variable in **Settings → Secrets and variables → Actions → Variables**:

- Name: `MFHELPER_SETUP_COMPLETE`
- Value: `true`

This enables the scheduled workflow. Without it, the template copy skips its daily job while you configure it.

The dashboard is not published from template copies by default. If you set `PUBLISH_PUBLIC_DASHBOARD=true`, the workflow publishes the generated dashboard to GitHub Pages. That dashboard includes portfolio data, so only opt in if you're comfortable making it public.

## 6. Updates

Template copies do not track upstream changes automatically. To update, compare the upstream repository's releases with your copy and bring over code and workflow changes while preserving your `config/` files and repository secrets. Do not overwrite your personalized configuration with the example files.

## Existing public upstream configuration

The public MFHelper repository can keep its own personal fund list and sheet settings out of tracked files by using the optional repository secrets `MFHELPER_FUNDS_YAML`, `MFHELPER_SETTINGS_YAML`, and `MFHELPER_BENCHMARKS_YAML`. The daily workflow uses these values when present. Template users should edit the configuration files in their private copy instead.
