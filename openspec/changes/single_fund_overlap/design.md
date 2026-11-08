# Design: Compare one fund with the configured funds

## Proposed behavior

1. Run locally with a command such as `.venv/bin/python fund_overlap_main.py --fund 120492`.
2. Read configured funds from the local `config/funds.yaml` (or a path supplied on the command line).
3. Require a target AMFI scheme code; it may be absent from the funds YAML.
4. Treat the YAML as the comparison list and include only entries whose `active` field is `true`. If the target also appears in the YAML, skip that entry so it is not compared with itself. An explicitly selected target is allowed even when its YAML entry is marked inactive.
5. Resolve the target and comparison funds through AMFI/Tickertape and fetch their current holdings. Reuse the existing local Tickertape mapping cache and helpers.
6. Reuse `calculate_overlap_percentage`, which calculates overlap as the sum of the minimum allocation for each shared stock.
7. Print comparison funds sorted from highest overlap to lowest, with the overlap percentage and up to 10 shared stocks contributing most to that overlap.
8. Report funds whose holdings could not be fetched without silently treating missing data as 0% overlap. If the target code is not a valid AMFI scheme or its holdings cannot be fetched, show a clear error.
9. Do not run as a scheduled or remote service, and do not write to Google Sheets. Keep the existing all-funds report unchanged.
10. Leave remote or scheduled execution for a separate future change.

## Choices for the user

- **Fund selection:** AMFI scheme code only, as requested. The target can be outside the YAML.
- **Inactive funds:** exclude entries marked `active: false` from the comparison list. A selected target may itself be marked inactive.
- **Implementation location:** a separate read-only `fund_overlap_main.py` avoids changing `overlap_main.py`, which currently writes a full report to Google Sheets.
