# Proposal: Allow Vercel Blob Uploads Through CSP

## Objective

Fix the browser upload failure in the Vercel CAS importer. The Network panel shows that the presign request returns an upload URL on `https://vercel.com/api/blob/`, but the page's Content Security Policy allows only same-origin requests and `*.blob.vercel-storage.com` connections. The browser blocks the returned upload URL, producing `Failed to fetch` before the importer receives the PDF.

## Approved Direction

- Add the exact Vercel Blob API path `https://vercel.com/api/blob/` to the page's `connect-src` directive.
- Preserve the existing same-origin and `*.blob.vercel-storage.com` sources and all other CSP restrictions.
- Add a regression check for the generated CSP and verify the browser upload reaches the import route using the existing synthetic fixture.

## Design Choice

The path-scoped source (`https://vercel.com/api/blob/`) was approved instead of allowing all connections to `https://vercel.com`. This limits browser connections to the observed upload endpoint. CSP ignores a source path after a redirect; the existing `*.blob.vercel-storage.com` source continues to allow the redirected Blob request.
