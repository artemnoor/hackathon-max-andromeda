import { timingSafeEqual } from 'node:crypto';
import { type IncomingMessage, type ServerResponse } from 'node:http';

import { AppError, ERROR_CODES, errorToLogFields } from '../../shared/errors.js';
import type { Logger } from '../../shared/logger.js';

export const MAX_WEBHOOK_BODY_BYTES = 1_048_576;

export type GuardedWebhookOptions = Readonly<{
  path: string;
  secret: string;
  logger?: Logger;
  onBody: (body: Buffer, request: IncomingMessage) => Promise<void>;
}>;

const write = (response: ServerResponse, status: number, text: string): void => {
  if (response.headersSent || response.destroyed) return;
  response.writeHead(status, {
    'content-type': 'text/plain; charset=utf-8',
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
  });
  response.end(text);
};

const secretMatches = (expected: string, actual: string | string[] | undefined): boolean => {
  if (typeof actual !== 'string') return false;
  const expectedBytes = Buffer.from(expected, 'utf8');
  const actualBytes = Buffer.from(actual, 'utf8');
  return expectedBytes.length === actualBytes.length && timingSafeEqual(expectedBytes, actualBytes);
};

export const withWebhookGuard = (options: GuardedWebhookOptions) =>
  (request: IncomingMessage, response: ServerResponse): void => {
    if (request.method !== 'POST' || request.url !== options.path) {
      request.resume();
      write(response, 404, 'Not Found');
      return;
    }
    if (!secretMatches(options.secret, request.headers['x-max-bot-api-secret'])) {
      request.resume();
      write(response, 404, 'Not Found');
      return;
    }
    const contentType = request.headers['content-type'];
    if (typeof contentType !== 'string' || !/^application\/json(?:\s*;|\s*$)/iu.test(contentType)) {
      request.resume();
      write(response, 415, 'Unsupported Media Type');
      return;
    }
    const rawLength = request.headers['content-length'];
    if (rawLength !== undefined && (typeof rawLength !== 'string' || !/^\d+$/u.test(rawLength))) {
      request.resume();
      write(response, 400, 'Bad Request');
      return;
    }
    if (rawLength !== undefined && Number(rawLength) > MAX_WEBHOOK_BODY_BYTES) {
      request.resume();
      write(response, 413, 'Payload Too Large');
      return;
    }

    let received = 0;
    let rejected = false;
    let ended = false;
    const chunks: Buffer[] = [];
    request.on('data', (chunk: Buffer | string) => {
      if (rejected) return;
      const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      received += bytes.byteLength;
      if (received > MAX_WEBHOOK_BODY_BYTES) {
        rejected = true;
        chunks.length = 0;
        write(response, 413, 'Payload Too Large');
        request.resume();
        return;
      }
      chunks.push(bytes);
    });
    request.once('error', () => {
      if (rejected) return;
      rejected = true;
      write(response, 400, 'Bad Request');
    });
    request.once('end', () => {
      if (ended || rejected) return;
      ended = true;
      void options.onBody(Buffer.concat(chunks, received), request).then(
        () => write(response, 200, 'OK'),
        (error: unknown) => {
          options.logger?.warn({ event: 'max_webhook_update_failed', error: errorToLogFields(error) });
          const status = error instanceof AppError && error.code === ERROR_CODES.VALIDATION_FAILED ? 400 : 503;
          write(response, status, status === 400 ? 'Bad Request' : 'Service Unavailable');
        },
      );
    });
  };
