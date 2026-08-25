# Tasks: Tactical "Profit-Taking & Trimming" Assistant

This task checklist tracks the stages of implementing the Tactical Profit-Taking / Trimming Assistant.

---

## 1. Task Breakdown

### Phase 1: Logic & Trimming Core
* [ ] Define the `TrimmingSignal` dataclass inside `mfhelper/alerts.py`.
* [ ] Implement `check_trimming_signal` in `mfhelper/alerts.py` to evaluate the 2+ trigger conditions across Trim Tiers 1, 2, and 3.
* [ ] Integrate the trimming checks inside `main.py`'s daily tracking loop and pass the signals into `dispatch_alerts_email`.

### Phase 2: HTML Email Builder Enhancements
* [ ] Update `dispatch_alerts_email` inside `mfhelper/alerts.py` to accept the `list[TrimmingSignal]`.
* [ ] Design a beautiful, premium, responsive HTML/CSS "Tactical Profit-Taking & Trimming Briefing" block (utilizing soft warning red and orange accents).
* [ ] Inject this block at the very top of the HTML email body (conditionally rendering only if active trimming signals are present, side-by-side or stacked with any active Dip-Buying briefings!).
* [ ] Ensure standard individual alerts table remains unchanged and functional for single-indicator overbought/oversold notifications.

### Phase 3: Verification & Validation
* [ ] Write a test script or execute a mock run where metrics are simulated to trigger Trim Tiers 1, 2, and 3 confluence conditions.
* [ ] Send mock emails to your inbox to verify responsive rendering, colors, readability, and correct Groww link forwarding.
* [ ] Commit and push the final working code to the remote repository.
