# Design: Add large-and-midcap fund list

## Proposed behavior

1. Keep `config/large_and_midcap.yaml` as a tracked template with instructions and `funds: []`.
2. Store the six user-selected AMFI codes and names in `config/large_and_midcap.private.yaml`; `.gitignore` already excludes `config/*.private.yaml`.
3. The loader resolves the private override automatically for both category rankings and analytics.
4. Do not add these funds to `config/funds.yaml` or change daily tracking.

## Open choice

The approved public template uses commented guidance and an empty list, so users must add their own funds in a private override before running this category.
