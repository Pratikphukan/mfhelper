# Proposal: Per-user Vercel Holdings Import (replaces OCI VM)

## Status

**Decisions answered (see `design.md`). Awaiting sign-off on the follow-up design points. No code or tests yet.**

## Objective

Host the CDSL CAS import page on the user's own Vercel account instead of an OCI Compute VM. Keep the behaviour from `oci_private_holdings`: authenticate the owner, parse the PDF in memory, keep only the minimal normalized snapshot, and never retain the PDF or PAN. No MFHelper-owned shared service or database is introduced.

## Why change

The OCI path works but carries operational cost that Vercel removes:

- No VM to patch, monitor, or firewall.
- No reserved public IP, Nginx, systemd, or Certbot short-lived IP certificate renewal. Vercel provides a stable HTTPS `*.vercel.app` hostname, which also gives GitHub OAuth a stable callback URL.
- Deploys happen from Git instead of by hand on a server.

## New constraints that Vercel introduces

- **Request body limit.** Vercel Functions reject request bodies larger than about 4.5 MB. The current importer accepts up to 25 MB. This is the main design decision.
- **No persistent filesystem.** Functions have a read-only or ephemeral filesystem, so the snapshot needs an external store (OCI Object Storage is no longer available to us).
- **Third-party processing.** The PDF and PAN pass through Vercel's infrastructure. Request metadata may appear in Vercel logs.

## Proposed Direction

- Run the existing FastAPI importer as a Vercel Python Function, reusing `parse_cdsl_cas`, the GitHub OAuth allowlist flow, the CSRF form token, and the stateless signed-cookie session.
- Replace `OCIHoldingsCache` with a storage adapter backed by a Vercel-hosted store (choice in `design.md`).
- Reuse the shared snapshot rules from `holdings_cache.py`: `snapshot_payload`, the older-statement guard, the idempotent re-import check, and atomic replacement.
- Remove the OCI-specific module, deploy templates, and `oci` dependency once the Vercel path is verified.
- Do not connect the snapshot to the daily workflow, dashboard, or recommendations (still deferred).

## Expected Flow

```text
User opens https://<project>.vercel.app
        |
GitHub OAuth sign-in (allowlisted login only)
        |
User selects the CAS PDF and enters its password
        |
Vercel Function decrypts, parses, validates in memory
        |
PDF and password dropped on every path
        |
Function writes the minimal snapshot to the private Vercel store
```

## Deferred

Daily workflow/dashboard integration, multi-user hosting, automatic statement retrieval, transaction history, NAV valuation, budgets, and recommendations.
