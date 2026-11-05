# Design: Private Mutual-Fund Holdings Import

## Proposed GitHub-Hosted Flow

```text
User opens a Codespace from their own private MFHelper repository
        ↓
The Codespace starts a private import page
        ↓
User selects their CDSL CAS PDF and enters the PDF password (PAN in uppercase)
        ↓
The app uploads the PDF to that user's Codespace over the private GitHub connection
        ↓
Codespace decrypts and parses the PDF temporarily, then validates the holdings
        ↓
Codespace saves the minimal holdings snapshot in that user's private repository
        ↓
The temporary PDF is deleted; daily workflow can read the snapshot
```

No shared MFHelper service or portfolio database is proposed. The Codespace belongs to the user who created it. The private forwarded port must stay private; it must not be switched to public visibility.

## Input and Decryption

- First supported source: the user's CDSL CAS, identified from their inbox.
- CDSL documents that the PDF password is the first/sole demat account holder's PAN in uppercase.
- Ask for the PAN in the private import page for that import only. Do not store it in repository files, Codespaces secrets, logs, or the snapshot.
- Recognize CDSL statement fields by their labels and fail closed if the date or holdings table is unsupported. The reviewed sample labels a reporting period and a mutual-fund holdings table with `Closing Balance (Units)` and `Valuation` columns. Use the period end as the holdings date; confirm end-to-end extraction in the Codespace before relying on this parser for the sample.
- If a table has both opening and closing unit balances, use the closing balance. Reject malformed non-total holding rows rather than save a partial snapshot.
- Upload the PDF only to the authenticated private Codespaces port. Keep it in temporary workspace storage and delete it on success and every failure path.

## Fields to Retain

- Stable scheme identifier when available (AMFI scheme code/ISIN)
- Display name
- Units held
- Statement value and statement/as-of date when present
- Import timestamp

Do not retain the source PDF, PAN, folio/account numbers, address, bank details, email content, or unused statement fields. Do not infer purchases from market-value changes. This import produces a holdings snapshot, not a transaction ledger.

## Duplicate and Update Behavior

- If the same statement has already been imported, tell the user it is already current and do not duplicate or rewrite holdings.
- If a newer valid statement is imported, replace/update the snapshot atomically.
- Never replace a valid snapshot with partial or invalid extraction.

## Values and Later Analysis

- Retain values explicitly shown in the statement and label them with the statement date.
- First version retains statement values only. Latest-NAV estimates are deferred.
- Portfolio overlap is not part of the statement cache; it can be calculated later from the holdings snapshot and MFHelper's existing fund data.
- Personal holdings and derived portfolio figures must not be published to public Pages or public workflow artifacts/logs.

## Codespaces and Repository Access

- A Codespace is created from the user's own private repository. The Codespaces import page runs on a privately forwarded port available only to that user.
- The PDF is uploaded to temporary Codespace storage and removed after processing; it is never committed to the repository.
- Store the minimal holdings snapshot as a normal data file in the private repository, without separate file encryption. This avoids per-user key setup; repository access controls limit who can read it.
- Before accepting the upload, require a Codespace, use GitHub CLI to verify the repository is private and forwarded port `8765` is private, and then allow multipart parsing. Use the Codespace's GitHub identity to commit and push only `data/private_holdings.json`.
- Check that the current branch is synchronized with its upstream before creating a snapshot commit. A retry after a failed push is allowed only for exactly one unpushed commit that changes the snapshot file alone.
- The Codespace may incur usage beyond the user's included GitHub quota; it should be stopped after import.
