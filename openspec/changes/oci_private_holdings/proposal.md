# Proposal: Per-user OCI Holdings Import

## Objective

Replace the private-repository/Codespaces storage flow for CAS imports with a remote worker and private storage in the user's own Oracle Cloud Infrastructure (OCI) tenancy. No MFHelper-owned shared database or shared holdings service is introduced.

## Proposed Direction

- Host the upload page and CAS importer in the user's OCI account.
- Let the user select a CDSL CAS PDF and enter the password for that import only.
- Process the PDF in the user's OCI environment, retain only the validated holdings snapshot, and delete the uploaded PDF and transient password.
- Save the snapshot as a private object in the user's OCI Object Storage bucket, not in a GitHub repository.
- Run the worker from MFHelper's public source repository; keep user-specific holdings and credentials in the user's OCI tenancy.
- Do not connect this first OCI version to the daily workflow, dashboard, or investment recommendations.

## Expected Flow

```text
User opens their OCI-hosted private import page
        ↓
User selects the CAS PDF and enters its password
        ↓
OCI worker decrypts, parses, and validates it
        ↓
Worker deletes the temporary PDF and password
        ↓
Worker writes the minimal snapshot to the user's private OCI bucket
```

## Approved Decisions

1. **Worker runtime: decided.** Use an OCI Compute VM. The user selected this after reviewing the trade-off: it accepts the existing 25 MB upload directly, with server maintenance as the cost.
2. **Owner authentication: decided.** Use GitHub OAuth restricted to the user's GitHub identity. GitHub is used only for sign-in; a private GitHub repository is not required.
3. **Snapshot retention: decided.** Keep only the latest snapshot at `holdings/current.json`, replacing it after each successful import.
4. **HTTPS address: decided.** Use the VM's stable public IP and automatically renew short-lived Let's Encrypt IP certificates. IP certificates are valid for about six days, so renewal and web-server reload must be automated. Keep the IP reserved so the OAuth callback and certificate identity do not change.

## Deferred

Daily workflow/dashboard integration, multi-user hosted service, automatic statement retrieval, transaction history, current-NAV valuation, investment budgets, and recommendations remain separate work.
