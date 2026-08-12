# Tasks: Technical Indicator "Buy/Sell Zone" Trigger Alerts

This task list tracks the execution phases for building and integrating the technical alert system.

---

## 1. Task Breakdown

### Phase 1: Configuration Scaffold
* [ ] Create `config/alerts.yaml` with placeholder SMTP and rule parameters.
* [ ] Add `config/alerts.yaml` to `.gitignore` to prevent any password leak (while checking in a `config/alerts.yaml.template` for users).
* [ ] Implement YAML schema loader inside `mfhelper/config.py` to parse alert rules and credentials.

### Phase 2: Core Alert Logic (`mfhelper/alerts.py`)
* [ ] Implement rule checking functions (`check_rsi`, `check_discount`, `check_sma_crossing`).
* [ ] Construct the HTML email body with neat formatting, colors, and specific calls to action.
* [ ] Implement the secure SMTP email sender leveraging environment variable fallbacks for passwords.

### Phase 3: Scheduler Integration (`main.py`)
* [ ] Load alert settings at the start of `main.py` alongside global configurations.
* [ ] Loop over each compiled fund's metrics and trigger rule evaluations.
* [ ] Accumulate any triggered alerts across all funds and dispatch a single grouped email digest.

### Phase 4: Verification & Testing
* [ ] Run local dry-run tests by forcing alert thresholds (e.g. setting RSI limit to 60 to force trigger an alert) and verify log reports.
* [ ] Verify the HTML email is delivered correctly to the receiver address with formatted numbers.
