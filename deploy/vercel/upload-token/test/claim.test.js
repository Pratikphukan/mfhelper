import test from 'node:test';
import assert from 'node:assert/strict';
import { claimPathForNonce, claimTicketNonce } from '../claim.js';
import { TicketError } from '../ticket.js';

const NONCE = 'nonce_for_testing_1234';

test('claims the signed nonce at a private fixed path without overwrite', async () => {
  const writes = [];
  await claimTicketNonce(NONCE, {
    putBlob: async (path, body, options) => writes.push({ path, body, options }),
    headBlob: async () => { throw new Error('not found'); },
  });

  assert.equal(writes.length, 1);
  assert.equal(writes[0].path, `tmp/used-tickets/${NONCE}.json`);
  assert.equal(writes[0].body, 'used');
  assert.equal(writes[0].options.access, 'private');
  assert.equal(writes[0].options.addRandomSuffix, false);
  assert.equal(writes[0].options.allowOverwrite, false);
});

test('rejects an already claimed ticket and does not overwrite its marker', async () => {
  const objects = new Set();
  const putBlob = async (path) => {
    if (objects.has(path)) throw new Error('pathname already exists');
    objects.add(path);
  };
  const headBlob = async (path) => {
    if (!objects.has(path)) throw new Error('not found');
    return { pathname: path };
  };

  await claimTicketNonce(NONCE, { putBlob, headBlob });
  await assert.rejects(claimTicketNonce(NONCE, { putBlob, headBlob }), TicketError);
  assert.equal(objects.size, 1);
});

test('concurrent use of one ticket has only one successful claim', async () => {
  const objects = new Set();
  const putBlob = async (path) => {
    await Promise.resolve();
    if (objects.has(path)) throw new Error('pathname already exists');
    objects.add(path);
  };
  const headBlob = async (path) => {
    if (!objects.has(path)) throw new Error('not found');
    return { pathname: path };
  };

  const results = await Promise.allSettled([
    claimTicketNonce(NONCE, { putBlob, headBlob }),
    claimTicketNonce(NONCE, { putBlob, headBlob }),
  ]);
  assert.equal(results.filter((result) => result.status === 'fulfilled').length, 1);
  const rejected = results.find((result) => result.status === 'rejected');
  assert.ok(rejected.reason instanceof TicketError);
});

test('fails closed when Blob cannot create or check the claim', async () => {
  await assert.rejects(
    claimTicketNonce(NONCE, {
      putBlob: async () => { throw new Error('Blob unavailable'); },
      headBlob: async () => { throw new Error('Blob unavailable'); },
    }),
    /could not be claimed/,
  );
});

test('rejects path-unsafe nonce values', () => {
  for (const nonce of ['../file', '', 42, 'short']) {
    assert.throws(() => claimPathForNonce(nonce), TicketError);
  }
});
