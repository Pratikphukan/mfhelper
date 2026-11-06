// Mints a presigned PUT URL for exactly one private temporary PDF.
// Dependencies are injected so the logic can be tested without Vercel Blob.
import { randomUUID } from 'node:crypto';
import { MAX_UPLOAD_BYTES, verifyTicket } from './ticket.js';

export const TEMP_PREFIX = 'tmp/';
export const PRESIGN_TTL_MS = 5 * 60 * 1000;
export const ALLOWED_CONTENT_TYPES = ['application/pdf'];

export async function createPresign({
  ticket,
  secret,
  issueSignedToken,
  presignUrl,
  claimTicket,
  now = Date.now,
  randomId = randomUUID,
}) {
  const payload = verifyTicket(secret, ticket, now());
  if (typeof claimTicket !== 'function') throw new Error('Upload ticket claim is not configured.');
  await claimTicket(payload.nonce);

  // The pathname is always chosen here; nothing from the browser selects it.
  const pathname = `${TEMP_PREFIX}${randomId()}.pdf`;
  const validUntil = now() + PRESIGN_TTL_MS;
  const maximumSizeInBytes = Math.min(payload.max_bytes, MAX_UPLOAD_BYTES);

  const token = await issueSignedToken({
    pathname,
    operations: ['put'],
    allowedContentTypes: ALLOWED_CONTENT_TYPES,
    maximumSizeInBytes,
    validUntil,
  });
  const { presignedUrl } = await presignUrl(token, {
    operation: 'put',
    pathname,
    access: 'private',
    allowedContentTypes: ALLOWED_CONTENT_TYPES,
    maximumSizeInBytes,
    addRandomSuffix: false,
    allowOverwrite: false,
    validUntil,
  });
  return { url: presignedUrl, pathname, max_bytes: maximumSizeInBytes };
}
