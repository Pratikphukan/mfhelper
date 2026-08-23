# Tasks: CLI Segregated Runs for Local Testing

This task checklist tracks the stages of implementing CLI-driven environment segregation.

---

## 1. Task Breakdown

### Phase 1: Main Parser & Logic
* [ ] Integrate an `argparse` parser inside `main.py` to accept the `--dev` CLI flag.
* [ ] Update `run()` inside `main.py` to accept the parsed arguments namespace.
* [ ] Dynamically construct `worksheet_name` depending on the `--dev` state and supply it to `SheetAppender`.
* [ ] Pass the `is_dev=args.dev` parameter into the `dispatch_alerts_email` function call.

### Phase 2: Email Helper Enhancement
* [ ] Update `dispatch_alerts_email` in `mfhelper/alerts.py` to accept the `is_dev` parameter.
* [ ] Implement conditional subject prefix styling (`🚨 [DEV]` vs `🚨`) inside `dispatch_alerts_email`.

### Phase 3: Deployment & Verification
* [ ] Run `python main.py --dev` locally on your Mac to verify that it successfully creates and populates the separate **`Daily NAV (Dev)`** worksheet tab.
* [ ] Confirm that your email alerts are successfully dispatched with the `[DEV]` tag in the subject line.
* [ ] Commit and push the final working files to the remote repository.
