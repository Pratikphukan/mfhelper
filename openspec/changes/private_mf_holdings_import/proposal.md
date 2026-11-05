# Proposal: Private Mutual-Fund Holdings Import

## Objective

Let one MFHelper user import their own CDSL mutual-fund CAS and create a holdings snapshot for later portfolio analysis. This is a standalone first step; it does not make investment recommendations or automatically retrieve statements.

## First-Phase Direction

- The user opens a Codespace from their own private MFHelper repository and uses a private import page with a file picker.
- The user selects a CDSL CAS PDF and enters its password. CDSL uses the first/sole account holder's PAN in uppercase; ask for it for that import only and never save or log it.
- Process the PDF remotely inside that user's Codespace. Extract fund identity/name, units, statement value when present, and statement/as-of date; validate before replacing the previous snapshot.
- Keep the persistent holdings cache as a normal data file in that user's private GitHub repository. Do not retain the source PDF.
- Keep all funds shown as holdings, including funds that no longer receive contributions.
- Make repeat imports idempotent: identify the same statement and report that it is already imported instead of duplicating or rewriting the data.
- The remote daily workflow may use the holdings cache, but personal holdings and derived values must not be published to a public dashboard.

## Deferred

Gmail access, automatic statement retrieval, other CAS formats, transaction-ledger reconstruction, SIP state, investment budgets, recommendations, and trade execution are separate changes.

## Implementation Decisions

1. Use a file-picker UI in the Codespace import page. (Decided.)
2. Keep the PDF password transient and do not persist it. (Decided.)
3. Retain statement values only in the first version; defer latest-NAV estimates. (Decided.)
4. Store the holdings snapshot as a normal private-repository file; do not add separate file encryption. (Decided.)
5. Require `CODESPACES=true`, verify the repository visibility with GitHub CLI before accepting the upload, and use the Codespace's GitHub identity to push the snapshot.

## Data-Handling Boundary

There is no shared MFHelper upload server or portfolio database. The PDF and PAN are sent from the user's browser to that user's GitHub-hosted Codespace for processing. The PDF is temporary and must be deleted after processing, including on errors. Only the normalized holdings snapshot is committed as a normal data file to that user's private repository, whose access controls protect it.
