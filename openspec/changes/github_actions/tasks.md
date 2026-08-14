# Tasks: GitHub Actions Scheduled daily NAV Workflow

This task checklist outlines the setup stages to deploy MFHelper onto GitHub Actions.

---

## 1. Task Breakdown

### Phase 1: Workflow Configuration
* [ ] Create directories `.github/workflows/` at the root of the project.
* [ ] Write the workflow configuration file `.github/workflows/daily_nav.yml`.

### Phase 2: Local Encryption Prep (Base64 Encoding)
* [ ] Instruct the user on how to convert their local binary JSON credentials to standard Base64 text in their terminal:
  - **macOS / Linux:**
    ```bash
    base64 -i config/credentials.json | pbcopy
    base64 -i data/token.json | pbcopy
    ```

### Phase 3: GitHub Settings Configuration
* [ ] Go to your GitHub repository -> **Settings** -> **Secrets and variables** -> **Actions**.
* [ ] Add the following encrypted repository secrets:
  - `GCP_CREDENTIALS_JSON` (Paste the encoded credentials).
  - `GCP_TOKEN_JSON` (Paste the encoded token).
  - `ALERTS_YAML` (Paste the raw content of your local `config/alerts.yaml`).
  - `EMAIL_PASSWORD` (Paste your 16-character App password).

### Phase 4: Push and Trigger Verification
* [ ] Commit and push `.github/workflows/daily_nav.yml` to the remote repository.
* [ ] Navigate to the repository's **Actions** tab on GitHub, select **Daily NAV & Technical Alerts Scheduler**, and click **Run workflow** manually to verify a clean execution in the cloud.
