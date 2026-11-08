# Design: Show the real error when a category file cannot be loaded

| Case | Result |
|---|---|
| Category file missing (no public, no private) | Unchanged: fall back to `funds.yaml` tags, else "not found". |
| Public file only, valid | Unchanged. |
| Private file present, valid | Private file is used (also when the public file is missing). |
| File exists but fails to load | `status: error`, message names the file and the reason. No fallback to `funds.yaml`. |
| Failing file is the public template | Same error plus a hint to create `<name>.private.yaml`. |

Decisions (approved in chat):
- Option 2: fall back to `funds.yaml` only when the category file is missing, never when it is broken.
- The hint is added for any failure of the public file. No string matching on the error text.
- `.private` stems are filtered from the "available categories" list.

Error message shape:

    Could not load category 'large_and_midcap' from large_and_midcap.yaml: No funds configured in ... .
    If this is the public template, copy it to large_and_midcap.private.yaml and add your AMFI scheme codes.
