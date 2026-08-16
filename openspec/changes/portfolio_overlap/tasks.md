# Tasks: Standalone Mutual Fund Portfolio Overlap Analyzer

This task checklist tracks the stages of implementing the portfolio overlap analysis feature.

---

## 1. Task Breakdown

### Phase 1: Core Engine Implementation
* [x] Create `mfhelper/overlap.py` to hold the modular extraction and calculation logic.
* [x] Parse AMFI to map AMFI scheme codes to ISINs and names.
* [x] Download Tickertape sitemap XML and extract all mutual fund URL slugs.
* [x] Write name fuzzy matching and candidate scoring logic with `difflib.SequenceMatcher`.
* [x] Query Tickertape `/mutualfunds/{mfId}/summary` API to validate the candidates' ISIN codes.
* [x] Cache resolved mappings inside `data/tickertape_mappings.json` to enable instant subsequent runs.
* [x] Retrieve live stock allocations from `api.tickertape.in/mutualfunds/{mfId}/holdings`.
* [x] Implement pairwise minimum-weight intersection calculations.

### Phase 2: Command Line Interface & Reporting
* [x] Create `overlap_main.py` entry point.
* [x] Implement arguments parsing (`--funds` parameter for custom yaml configs).
* [x] Formulate a nicely-aligned ASCII pairwise overlap matrix printing routine.
* [x] Implement a detailed stock-level analysis that displays the top 8 overlapping stock holdings for fund pairs with over 10.0% overlap.

### Phase 3: Final Verification
* [x] Run `overlap_main.py` locally and verify that all 11 funds resolve and map perfectly.
* [x] Confirm that subsequent executions run instantly (<1s) by loading from the local mapping cache.
* [x] Stage, commit, and push all implementation and OpenSpec files to the remote `main` branch.
