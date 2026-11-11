import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { createPresign } from '../presign.js';
import { AUDIENCE, MAX_UPLOAD_BYTES, TicketError } from '../ticket.js';

const SECRET = 's'.repeat(40);
const NOW_MS = 1_800_000_000_000;

function ticket(overrides = {}) {
  const payload = {
    aud: AUDIENCE,
    login: 'owner',
    exp: NOW_MS / 1000 + 60,
    nonce: 'nonce_for_testing_1234',
    max_bytes: MAX_UPLOAD_BYTES,
    ...overrides,
  };
  const payloadB64 = Buffer.from(JSON.stringify(payload)).toString('base64url');
  const signature = createHmac('sha256', SECRET).update(payloadB64, 'ascii').digest('base64url');
  return `${payloadB64}.${signature}`;
}

function fakes() {
  const calls = { claim: [], issue: [], presign: [], order: [] };
  return {
    calls,
    issueSignedToken: async (options) => {
      calls.order.push('issue');
      calls.issue.push(options);
      return { delegationToken: 'd', clientSigningToken: 'c' };
    },
    presignUrl: async (token, options) => {
      calls.order.push('presign');
      calls.presign.push({ token, options });
      return { presignedUrl: `https://store.private.blob.vercel-storage.com/${options.pathname}?sig=x` };
    },
  };
}

test('mints a private, single-file, PDF-only, size-limited PUT URL for a CAS ticket', async () => {
  const f = fakes();
  const result = await createPresign({
    ticket: ticket(),
    secret: SECRET,
    issueSignedToken: f.issueSignedToken,
    presignUrl: f.presignUrl,
    claimTicket: async (nonce) => { f.calls.order.push('claim'); f.calls.claim.push(nonce); },
    now: () => NOW_MS,
    randomId: () => 'abc-123',
  });

  assert.equal(result.pathname, 'tmp/abc-123.pdf');
  assert.match(result.url, /tmp\/abc-123\.pdf/);
  assert.equal(result.max_bytes, MAX_UPLOAD_BYTES);
  assert.deepEqual(f.calls.claim, ['nonce_for_testing_1234']);
  assert.deepEqual(f.calls.order, ['claim', 'issue', 'presign']);

  const [issued] = f.calls.issue;
  assert.deepEqual(issued.operations, ['put']);
  assert.deepEqual(issued.allowedContentTypes, ['application/pdf']);
  assert.equal(issued.maximumSizeInBytes, MAX_UPLOAD_BYTES);
  assert.equal(issued.pathname, 'tmp/abc-123.pdf');
  assert.equal(issued.validUntil, NOW_MS + 5 * 60 * 1000);

  const [{ options }] = f.calls.presign;
  assert.equal(options.access, 'private');
  assert.equal(options.operation, 'put');
  assert.equal(options.allowOverwrite, false);
  assert.equal(options.addRandomSuffix, false);
});

test('mints an XLSX-only upload URL for a Groww ticket', async () => {
  const f = fakes();
  const result = await createPresign({
    ticket: ticket({ upload_type: 'groww_xlsx' }),
    secret: SECRET,
    issueSignedToken: f.issueSignedToken,
    presignUrl: f.presignUrl,
    claimTicket: async () => {},
    now: () => NOW_MS,
    randomId: () => 'groww-123',
  });

  assert.equal(result.pathname, 'tmp/groww-123.xlsx');
  assert.equal(result.content_type, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
  assert.deepEqual(f.calls.issue[0].allowedContentTypes, [result.content_type]);
  assert.equal(f.calls.issue[0].pathname, 'tmp/groww-123.xlsx');
});

test('never calls Blob when the ticket is invalid or expired', async () => {
  for (const bad of ['nope', ticket({ exp: NOW_MS / 1000 - 5 })]) {
    const f = fakes();
    await assert.rejects(
      createPresign({
        ticket: bad,
        secret: SECRET,
        issueSignedToken: f.issueSignedToken,
        presignUrl: f.presignUrl,
        now: () => NOW_MS,
      }),
      TicketError,
    );
    assert.equal(f.calls.issue.length, 0);
    assert.equal(f.calls.presign.length, 0);
  }
});

test('uses a smaller ticket limit but never a larger one', async () => {
  const f = fakes();
  const result = await createPresign({
    ticket: ticket({ max_bytes: 1024 }),
    secret: SECRET,
    issueSignedToken: f.issueSignedToken,
    presignUrl: f.presignUrl,
    claimTicket: async () => {},
    now: () => NOW_MS,
  });
  assert.equal(result.max_bytes, 1024);
});

test('does not mint an upload URL when claiming the ticket fails', async () => {
  const f = fakes();
  await assert.rejects(
    createPresign({
      ticket: ticket(),
      secret: SECRET,
      issueSignedToken: f.issueSignedToken,
      presignUrl: f.presignUrl,
      claimTicket: async () => { throw new TicketError('already used'); },
      now: () => NOW_MS,
    }),
    TicketError,
  );
  assert.equal(f.calls.issue.length, 0);
  assert.equal(f.calls.presign.length, 0);
});
