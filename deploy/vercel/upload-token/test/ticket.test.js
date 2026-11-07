import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { AUDIENCE, MAX_UPLOAD_BYTES, TicketError, verifyTicket } from '../ticket.js';

const SECRET = 's'.repeat(40);
const NOW_MS = 1_800_000_000_000;

function sign(payload, secret = SECRET) {
  const payloadB64 = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const signature = createHmac('sha256', secret).update(payloadB64, 'ascii').digest('base64url');
  return `${payloadB64}.${signature}`;
}

function payload(overrides = {}) {
  return {
    aud: AUDIENCE,
    login: 'owner',
    exp: NOW_MS / 1000 + 60,
    nonce: 'nonce_for_testing_1234',
    max_bytes: MAX_UPLOAD_BYTES,
    ...overrides,
  };
}

test('accepts a valid ticket', () => {
  const result = verifyTicket(SECRET, sign(payload()), NOW_MS);
  assert.equal(result.login, 'owner');
});

test('rejects a ticket signed with another secret', () => {
  assert.throws(() => verifyTicket(SECRET, sign(payload(), 'x'.repeat(40)), NOW_MS), TicketError);
});

test('rejects a tampered payload', () => {
  const [, signature] = sign(payload()).split('.');
  const forged = Buffer.from(JSON.stringify(payload({ max_bytes: 1 }))).toString('base64url');
  assert.throws(() => verifyTicket(SECRET, `${forged}.${signature}`, NOW_MS), TicketError);
});

test('rejects an expired ticket', () => {
  assert.throws(() => verifyTicket(SECRET, sign(payload({ exp: NOW_MS / 1000 - 1 })), NOW_MS), /expired/);
});

test('rejects the wrong audience and oversized limits', () => {
  assert.throws(() => verifyTicket(SECRET, sign(payload({ aud: 'other' })), NOW_MS), TicketError);
  assert.throws(
    () => verifyTicket(SECRET, sign(payload({ max_bytes: MAX_UPLOAD_BYTES + 1 })), NOW_MS),
    TicketError,
  );
});

test('rejects malformed input and short secrets', () => {
  for (const bad of [undefined, null, 42, '', 'abc', 'a.b.c', 'x'.repeat(3000)]) {
    assert.throws(() => verifyTicket(SECRET, bad, NOW_MS), TicketError);
  }
  assert.throws(() => verifyTicket('short', sign(payload()), NOW_MS), TicketError);
});

test('verifies a ticket passed on the command line (cross-language check)', { skip: !process.env.MFHELPER_TEST_TICKET }, () => {
  const result = verifyTicket(process.env.MFHELPER_TEST_SECRET, process.env.MFHELPER_TEST_TICKET);
  assert.equal(result.aud, AUDIENCE);
  assert.equal(result.login, 'mfhelper-owner');
});

test('rejects missing or path-unsafe nonces', () => {
  for (const nonce of [undefined, '', '../file', 'short', 'x'.repeat(65)]) {
    assert.throws(() => verifyTicket(SECRET, sign(payload({ nonce })), NOW_MS), TicketError);
  }
});
