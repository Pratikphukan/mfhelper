# Tasks: AMFI Quarterly Scheme AUM

## Phase 1: Confirm Design

- [x] Confirm which analytics tabs receive the new column and AMFI AUM source (all sheets written by `analytics_main.py`).
- [x] Confirm whether AUM is whole-scheme or exact-plan/option AAUM (exact Direct Growth plan only).
- [x] Confirm the displayed quarter-label format (Calendar format, e.g. `Jul-Sep 2026`).

## Phase 2: Implementation

- [x] Retrieve the latest available AMFI scheme-wise quarterly AAUM report.
- [x] Match scheme rows and compute AUM using the approved plan/option rule.
- [x] Add `AUM Quarter` adjacent to `AUM (Cr.)` in the approved analytics tabs.
- [x] Keep `Last Updated (IST)` as the analytics row write time.
- [x] Handle unavailable reports and unmatched schemes without silently
  presenting stale values as current.

## Phase 3: Verification

- [x] Verify report-quarter selection and AUM matching with offline/sample data.
- [x] Verify output columns and quarter labels without writing to production
  Google Sheets or live state.
- [x] Run `pytest tests/` and confirm all tests pass.
