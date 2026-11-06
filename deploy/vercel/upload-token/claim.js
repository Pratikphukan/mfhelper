// Claim an upload-ticket nonce once in private Blob before issuing any PUT URL.
// Blob writes reject an existing pathname by default, making the claim shared across service instances.
import { head, put } from '@vercel/blob';
import { TicketError } from './ticket.js';

export const CLAIM_PREFIX = 'tmp/used-tickets/';
const NONCE_RE = /^[A-Za-z0-9_-]{16,64}$/;

export function claimPathForNonce(nonce) {
  if (typeof nonce !== 'string' || !NONCE_RE.test(nonce)) {
    throw new TicketError('The upload ticket is invalid.');
  }
  return `${CLAIM_PREFIX}${nonce}.json`;
}

export async function claimTicketNonce(nonce, { putBlob = put, headBlob = head } = {}) {
  const pathname = claimPathForNonce(nonce);
  try {
    await putBlob(pathname, '{"used":true}', {
      access: 'private',
      contentType: 'application/json',
      addRandomSuffix: false,
      allowOverwrite: false,
      cacheControlMaxAge: 60,
    });
  } catch (writeError) {
    // A successful HEAD means another request already claimed the ticket.
    // If HEAD also fails (for example, Blob is unavailable), fail closed as a server error.
    try {
      await headBlob(pathname);
    } catch {
      throw new Error('The upload ticket could not be claimed.', { cause: writeError });
    }
    throw new TicketError('This upload ticket has already been used. Request a new ticket.');
  }
}
