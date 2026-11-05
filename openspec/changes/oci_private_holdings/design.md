# Design: Per-user OCI Holdings Import

## Scope

Move the remote CAS upload, parsing, and persistent holdings snapshot out of GitHub Codespaces and the private GitHub repository. Each user owns and operates their own OCI tenancy and storage. MFHelper does not receive a shared copy of user holdings.

## Proposed Components

- **Import web app:** existing FastAPI form with a PDF picker and transient password field.
- **Worker:** the CAS parser runs in the same user's OCI tenancy after an explicit upload.
- **Object Storage:** a private bucket holds only the normalized holdings JSON snapshot.
- **Source code:** deploy from the public MFHelper repository. Do not place user holdings, credentials, or PDFs in the source checkout or its Git history.

## Data Handling

- Accept import requests only after authenticating the user and confirming the target bucket is private.
- The browser sends the PDF directly to the VM over HTTPS; the current parser's 25 MB limit remains in force.
- Keep the PDF and password in temporary process memory/storage only; do not log the password or statement contents.
- Delete the PDF and password on every success and error path.
- Store only the existing minimal snapshot fields: stable fund identifier when available, display name, units, statement value/date, and import timestamp.
- Do not store the PAN, folio/account numbers, address, bank details, or original PDF.
- Write the new snapshot atomically so a failed parse cannot replace a valid one.
- Do not make the snapshot public or expose it through Pages, logs, build artifacts, or unauthenticated endpoints.

### Public HTTPS Address

- **Decided:** use the VM's stable public IP as the HTTPS hostname; no custom domain is available.
- Assign a reserved public IPv4 address and use it as the GitHub OAuth callback host. A changing IP would break the callback and certificate.
- Use Certbot 5.4+ with the Let's Encrypt `shortlived` profile and IP-address validation. Let's Encrypt IP certificates last about 160 hours, so automatic renewal and a web-server reload hook are required.
- Do not expose the application directly on HTTP. Allow public inbound traffic only for ports 80 (ACME HTTP challenge and redirect) and 443 (HTTPS); keep the app server bound to loopback.

## Approved Choices and Trade-offs

### Worker Runtime

- **Decided: OCI Compute VM.** It supports the existing long-running FastAPI upload app and its 25 MB PDF limit. Requires HTTPS, OS updates, firewall/IAM setup, and monitoring. Always Free shapes are limited to the tenancy's home region and may be temporarily unavailable.

### Authentication

- **Decided: GitHub OAuth allowlist.** Reuse an identity the user already has and restrict access to their GitHub account; this does not require a private repo. Requires registering and protecting an OAuth app secret.

### Snapshot Retention

- **Decided: single current object.** Overwrite `holdings/current.json` after a successful import; this retains only the latest snapshot, but has no object-level rollback.

## Future Workflow Integration

This change only imports and stores the holdings snapshot. Existing GitHub Actions and dashboard code will not automatically read OCI Object Storage. Any later integration must use per-user OCI authorization and keep holdings out of public artifacts and logs.
