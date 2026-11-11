// Mints a presigned PUT URL for exactly one private temporary statement file.
// Dependencies are injected so the logic can be tested without Vercel Blob.
import { randomUUID } from 'node:crypto';
import { MAX_UPLOAD_BYTES, UPLOAD_TYPES, verifyTicket } from './ticket.js';

export const TEMP_PREFIX = 'tmp/';
export const PRESIGN_TTL_MS = 5 * 60 * 1000;
export const ALLOWED_CONTENT_TYPES = Object.values(UPLOAD_TYPES).map((item) => item.contentType);

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
  const fileType = UPLOAD_TYPES[payload.upload_type];
  const allowedContentTypes = [fileType.contentType];
  const pathname = `${TEMP_PREFIX}${randomId()}.${fileType.extension}`;
  const validUntil = now() + PRESIGN_TTL_MS;
  const maximumSizeInBytes = Math.min(payload.max_bytes, MAX_UPLOAD_BYTES);

  const token = await issueSignedToken({
    pathname,
    operations: ['put'],
    allowedContentTypes,
    maximumSizeInBytes,
    validUntil,
  });
  const { presignedUrl } = await presignUrl(token, {
    operation: 'put',
    pathname,
    access: 'private',
    allowedContentTypes,
    maximumSizeInBytes,
    addRandomSuffix: false,
    allowOverwrite: false,
    validUntil,
  });
  return {
    url: presignedUrl,
    pathname,
    max_bytes: maximumSizeInBytes,
    content_type: fileType.contentType,
    upload_type: payload.upload_type,
  };
}
