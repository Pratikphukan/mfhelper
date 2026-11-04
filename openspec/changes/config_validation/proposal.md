# Proposal: Validate fund configuration values

## Problem

`load_funds()` currently converts `active` with Python's `bool()`. A quoted YAML value such as `active: "false"` is a non-empty string and therefore becomes `True`, silently enabling a fund the user meant to disable. Numeric configuration values are converted to floats but are not checked for NaN, infinity, or plausible ranges.

## Proposed change

Make fund configuration validation explicit and fail early with an error that identifies the fund and field. Require `active` to be a YAML boolean, and validate optional numeric fund fields before constructing `FundConfig`.

## Scope

This covers `active`, `weight`, and `expense_ratio` in `mfhelper/config.py`. It does not alter fund tracking behavior, analytics formulas, or configuration file values.
