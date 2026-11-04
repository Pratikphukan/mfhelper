# Design: Fund configuration validation

## Boolean handling

Recommended: accept only actual YAML booleans (`true` / `false`, unquoted) for `active`; reject quoted strings such as `"false"` with a clear message. This prevents silent coercion. Alternative: accept case-insensitive strings `"true"` and `"false"` for convenience, at the cost of a more permissive schema.

## Numeric handling

Both `weight` and `expense_ratio` should reject non-numeric and non-finite values. Candidate range policies:

- Minimal: require finite, non-negative values; do not impose upper bounds or relationships between funds.
- Strict: additionally limit each `weight` to 100 percent and enforce a portfolio-level total rule. This catches more mistakes but may reject intentionally partial or overlapping fund lists.

For `expense_ratio`, a finite non-negative percentage is a low-assumption constraint. A tighter upper bound is possible but needs a chosen threshold.

## Errors

Raise `ValueError` naming the config path, fund entry number, and invalid field/value. Keep the existing behavior that omitted optional fields remain `None`, and omitted `active` defaults to `True`.
