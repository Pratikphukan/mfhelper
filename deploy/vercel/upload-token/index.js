// Upload-token service: the only job is to turn a valid signed ticket into a
// presigned, private, single-file PUT URL. It holds no session, GitHub secret,
// or parser code. Blob access uses Vercel OIDC (BLOB_STORE_ID), not a static token.
import express from 'express';
import { issueSignedToken, presignUrl } from '@vercel/blob';
import { createPresign } from './presign.js';
import { TicketError } from './ticket.js';

const app = express();
app.disable('x-powered-by');
app.use((_req, res, next) => {
  res.set({
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'",
  });
  next();
});
app.use(express.json({ limit: '4kb' }));

app.post('/upload-token/presign', async (req, res) => {
  try {
    const result = await createPresign({
      ticket: req.body && req.body.ticket,
      secret: process.env.MFHELPER_TICKET_SECRET || '',
      issueSignedToken,
      presignUrl,
    });
    res.status(200).json(result);
  } catch (error) {
    if (error instanceof TicketError) {
      res.status(401).json({ error: error.message });
    } else {
      // Do not log the ticket or URL; they grant upload rights.
      res.status(500).json({ error: 'The private upload could not be prepared.' });
    }
  }
});

// Malformed JSON or oversized bodies.
app.use((_err, _req, res, _next) => {
  res.status(400).json({ error: 'The request was not valid.' });
});

export default app;
