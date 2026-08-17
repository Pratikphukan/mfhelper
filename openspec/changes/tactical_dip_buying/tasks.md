# Tasks: Tactical "Dip Buying" Assistant in Email Alerts

This task checklist outlines the development and deployment steps for the Dip Buying Assistant.

---

## 1. Task Breakdown

### Phase 1: Logic & Confluence Core
* [ ] Define the `DipBuyingSignal` dataclass in `mfhelper/alerts.py`.
* [ ] Implement `check_confluence_signal` in `mfhelper/alerts.py` to evaluate the 2+ trigger conditions across Tiers 1, 2, and 3.
* [ ] Generate the URL-encoded Groww deep search link for each fund.
* [ ] Integrate the confluence checks inside `main.py`'s daily tracking loop and pass the signals to `dispatch_alerts_email`.

### Phase 2: HTML Email Builder Enhancements
* [ ] Update `dispatch_alerts_email` inside `mfhelper/alerts.py` to accept the `list[DipBuyingSignal]`.
* [ ] Design a beautiful, premium, responsive HTML/CSS "Tactical Dip-Buying Briefing" block.
* [ ] Inject this block at the very top of the HTML email body, conditionally rendering only if active confluence signals are present.
* [ ] Ensure standard individual alerts table remains unchanged and functional for single-indicator notifications.

### Phase 3: Verification & Validation
* [ ] Write a test script or execute a mock run where metrics are simulated to trigger Tier 1, Tier 2, and Tier 3 confluence conditions.
* [ ] Send mock emails to your inbox to verify responsive rendering, colors, readability, and correct Groww link forwarding.
* [ ] Commit and push the final working code to the remote repository.
