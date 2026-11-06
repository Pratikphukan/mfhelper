// Verifies the short-lived upload ticket minted by mfhelper/upload_ticket.py.
// Format: base64url(payload_json) + "." + base64url(HMAC_SHA256(secret, payload_b64)).
import { createHmac, timingSafeEqual } from 'node:crypto';

export const AUDIENCE = 'mfhelper-upload';
export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
export const MIN_SECRET_LENGTH = 32;

export class TicketError extends Error {}

function invalid() {
  return new TicketError('The upload ticket is invalid.');
}

export function verifyTicket(secret, ticket, nowMs = Date.now()) {
  if (typeof secret !== 'string' || secret.length < MIN_SECRET_LENGTH) {
    throw new TicketError('The upload ticket secret is not configured.');
  }
  if (typeof ticket !== 'string' || ticket.length > 2048) throw invalid();
  const parts = ticket.split('.');
  if (parts.length !== 2) throw invalid();
  const [payloadB64, supplied] = parts;

  const expected = createHmac('sha256', secret).update(payloadB64, 'ascii').digest('base64url');
  const a = Buffer.from(expected, 'utf8');
  const b = Buffer.from(supplied, 'utf8');
  if (a.length !== b.length || !timingSafeEqual(a, b)) throw invalid();

  let payload;
  try {
    payload = JSON.parse(Buffer.from(payloadB64, 'base64url').toString('utf8'));
  } catch {
    throw invalid();
  }
  if (payload === null || typeof payload !== 'object' || payload.aud !== AUDIENCE) throw invalid();
  if (!Number.isInteger(payload.exp) || nowMs / 1000 >= payload.exp) {
    throw new TicketError('The upload ticket has expired. Reload the page and try again.');
  }
  if (!Number.isInteger(payload.max_bytes) || payload.max_bytes <= 0 || payload.max_bytes > MAX_UPLOAD_BYTES) {
    throw invalid();
  }
  return payload;
}
