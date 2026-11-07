import test from 'node:test';
import assert from 'node:assert/strict';

process.env.MFHELPER_TICKET_SECRET = 's'.repeat(40);
const { default: app } = await import('../index.js');

async function withServer(fn) {
  const server = app.listen(0, '127.0.0.1');
  await new Promise((resolve) => server.once('listening', resolve));
  try {
    await fn(`http://127.0.0.1:${server.address().port}`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

test('rejects a bad ticket with 401 and no-store headers', async () => {
  await withServer(async (base) => {
    const response = await fetch(`${base}/upload-token/presign`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ ticket: 'not-a-ticket' }),
    });
    assert.equal(response.status, 401);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.equal(response.headers.get('x-powered-by'), null);
    assert.match((await response.json()).error, /invalid/);
  });
});

test('rejects malformed JSON without leaking details', async () => {
  await withServer(async (base) => {
    const response = await fetch(`${base}/upload-token/presign`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: '{not json',
    });
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { error: 'The request was not valid.' });
  });
});

test('does not expose other methods or paths', async () => {
  await withServer(async (base) => {
    assert.equal((await fetch(`${base}/upload-token/presign`)).status, 404);
    assert.equal((await fetch(`${base}/other`, { method: 'POST' })).status, 404);
  });
});
