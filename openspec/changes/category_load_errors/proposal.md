# Proposal: Show the real error when a category file cannot be loaded

## Problem

`fetch_category_rankings` hides every category-file load error. An empty list, a YAML typo or a fund
with no `code` all end as "Category 'x' not found" (the real reason goes only to the log). The same
message also lists the category as "available".

## Change

- If a category file exists (the public file or its `.private.yaml` override) and fails to load,
  return that file's real error. Do not fall back to `funds.yaml`.
- If no category file exists at all, keep today's fallback to `funds.yaml` category tags.
- When the failing file is the public template, add a hint: copy it to `<name>.private.yaml` and add
  your AMFI scheme codes.
- A category that has only a `.private.yaml` file (no public file) is now found.
- `*.private` files are no longer listed as separate categories in the "available categories" text.

## Out of scope

Analytics commands, the empty template file itself, and any change to which funds are ranked.
