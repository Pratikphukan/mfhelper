# Proposal: Add large-and-midcap fund list

## Goal

Add a category YAML file that MFHelper can use for large-and-midcap fund rankings and analytics, following the existing `config/midcap.yaml` pattern.

## Proposed change

Keep `config/large_and_midcap.yaml` as a public template with commented guidance and an empty fund list. Put the user's six funds (`120357`, `147704`, `118419`, `119721`, `120596`, and `146772`) in the ignored local override `config/large_and_midcap.private.yaml`.

The existing category-ranking and analytics commands prefer a matching `.private.yaml` file when one exists. This does not require code changes or change the user's main tracked-funds list.
