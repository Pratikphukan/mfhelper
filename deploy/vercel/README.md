# Private CAS importer on Vercel

This runs the CDSL CAS importer in **your own Vercel account**. MFHelper's public source is deployed as one Vercel project with two services:

| Service | Folder | Job |
|---|---|---|
| `web` (Python / FastAPI) | `deploy/vercel/web` | GitHub sign-in, upload tickets, PDF parsing, snapshot storage |
| `upload_token` (Node) | `deploy/vercel/upload-token` | Turns a valid ticket into a presigned, private, single-file PDF upload URL |

Vercel Services is a Beta feature. Routing is defined in the repository's `vercel.json`.

## How a statement is imported

```text
Browser (signed in with GitHub)
  1. POST /upload-ticket            -> Python checks the allowlisted login + CSRF token, returns a 2-minute signed ticket
  2. POST /upload-token/presign     -> Node verifies and claims the ticket nonce once, then returns a presigned PUT URL for tmp/<random>.pdf
  3. PUT <presigned URL>            -> the PDF goes straight to your private Blob store (PDF only, max 25 MB, 5 minutes)
  4. POST /import {pathname, pan}   -> Python reads the PDF, parses it in memory, saves the snapshot, DELETES the PDF
```

Vercel Functions reject request bodies over about 4.5 MB, which is why step 3 goes directly to Blob instead of through the function.

## What is stored

- `holdings/current.json` in your **private** Blob store: only the latest validated snapshot (fund identifiers, names, units, statement value, statement date, import time). No PAN, folio numbers, address, bank details, or PDF.
- `tmp/<random>.pdf`: the encrypted CAS PDF, only between upload and parse. It is deleted when the import finishes, whether it succeeds or fails. If a browser abandons the flow after uploading, the leftover file is removed the next time you use the importer once it is older than 15 minutes.
- Your PAN (the PDF password) is sent only to the Python function for that request. It is never written to Blob, logs, or the snapshot.
- The GitHub OAuth token is used once to identify you and is not saved. The browser session is a signed, secure cookie valid for one hour.

The snapshot is not read by the daily GitHub Actions workflow or the public dashboard.

## Setup

Use **separate throwaway resources first** (a second Vercel project, its own Blob store, and its own GitHub OAuth app) and import the synthetic statement described below. Only then create the real project. Never test with your real statement against production data.

1. **Create the Vercel project.** Import your fork/copy of this repository in Vercel (Hobby is enough for personal use). If the dashboard asks for a framework preset, choose **Services**; the repo's `vercel.json` defines the two services.
2. **Create a private Blob store** in the same Vercel account and connect it to the project for Production (and Preview/Development if you will use them). The access mode cannot be changed after creation. With the CLI:

   ```bash
   vercel blob create-store mfhelper-holdings --access private --yes
   ```

   Connecting the store adds `BLOB_STORE_ID` and OIDC credentials automatically. You do **not** need `BLOB_READ_WRITE_TOKEN`; remove it from the project if it was added.
3. **Create a GitHub OAuth App** (Settings > Developer settings > OAuth Apps) for sign-in only. Homepage: `https://<project>.vercel.app`. Callback: `https://<project>.vercel.app/oauth/callback`. The app requests only `read:user` and accepts only your login.
4. **Add environment variables** in the Vercel project (Production):

   | Variable | Value |
   |---|---|
   | `MFHELPER_PUBLIC_URL` | `https://<project>.vercel.app` (no path, HTTPS) |
   | `MFHELPER_SESSION_SECRET` | random, at least 32 characters |
   | `MFHELPER_TICKET_SECRET` | a **different** random value, at least 32 characters; shared by both services |
   | `GITHUB_OAUTH_CLIENT_ID` | from the OAuth app |
   | `GITHUB_OAUTH_CLIENT_SECRET` | from the OAuth app |
   | `GITHUB_ALLOWED_LOGIN` | your GitHub login |

   Generate a secret with `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
5. **Deploy.** The `web` service's build command runs `vendor.py`, which copies the shared `mfhelper` modules next to the entrypoint. The build log should show `vendored 6 mfhelper modules`.
6. **Open** `https://<project>.vercel.app`, sign in with GitHub, choose the CAS PDF, enter the PAN, and import.

### Synthetic end-to-end check

Create a fake encrypted statement (password `ABCDE1234F`) and import it into your throwaway project:

```bash
.venv/bin/python scripts/make_synthetic_cas.py /tmp/synthetic-cas.pdf
```

After the import, confirm in the Vercel Blob browser that `holdings/current.json` exists, that `tmp/` is empty, and that opening a blob URL without credentials is denied.

## Access and security notes

- Only the configured GitHub login can obtain a ticket. The Node service holds no session, GitHub secret, or parser; it verifies the HMAC-signed ticket, claims its nonce once in a private Blob marker, and mints a URL for a server-chosen `tmp/<random>.pdf` path.
- The upload URL is limited to `application/pdf`, 25 MB, one private path, and 5 minutes. A ticket lasts 2 minutes and can be claimed once. The temporary claim marker is removed by the next stale-object cleanup after 15 minutes.
- The page sends a strict Content-Security-Policy (nonce-based inline script, `connect-src` limited to the app, `https://vercel.com/api/blob/`, and `*.blob.vercel-storage.com`) and loads no third-party scripts.
- Vercel is a third party that handles the encrypted PDF and PAN in transit. Do not add request-body logging or log drains for this project.
- The Python Blob SDK has no cache-bypass read; after a replace, the previous snapshot can be served for up to about 60 seconds. This only matters if two imports happen within a minute.
- Rotate `MFHELPER_SESSION_SECRET` / `MFHELPER_TICKET_SECRET` to sign out all sessions and invalidate tickets immediately.

## Deleting your data

In the Vercel dashboard, open the project's Blob store and delete `holdings/current.json` and anything under `tmp/`. Delete the store itself to remove everything.

## Updating

Redeploy from the repository. Importer code is public; your holdings and secrets exist only in your Vercel project and Blob store.

## Local checks

```bash
pytest tests/                                     # Python tests (use a fake Blob store; no Vercel account needed)
cd deploy/vercel/upload-token && npm ci && npm test   # Node ticket/presign tests
```

Local development against a real store needs `vercel link` and `vercel env pull`; use a throwaway store.
