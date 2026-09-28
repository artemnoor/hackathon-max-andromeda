import { randomUUID } from 'node:crypto';
import { readFile, realpath, stat } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';
import type { IncomingMessage, ServerResponse } from 'node:http';

import type { AppConfig } from '../shared/config.js';
import { AppError, ERROR_CODES, errorToPublicPayload, errorToLogFields } from '../shared/errors.js';
import type { Logger } from '../shared/logger.js';
import { validateMaxInitData } from '../max/auth/init-data.js';
import { miniAppContentSecurityPolicy } from './static-policy.js';

export const MAX_MINI_APP_RESPONSE_BYTES = 4 * 1024 * 1024;
const MAX_INIT_DATA_HEADER_BYTES = 16 * 1024;
const HEADER_NAME = 'x-max-init-data';
const STATIC_FILES: Readonly<Record<string, string>> = Object.freeze({
  '/': 'index.html',
  '/index.html': 'index.html',
  '/styles.css': 'styles.css',
  '/app.js': 'app.js',
  '/bridge.js': 'bridge.js',
});
const CONTENT_TYPES: Readonly<Record<string, string>> = Object.freeze({
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
});

export type MaxMiniAppDependencies = Readonly<{
  config: Pick<AppConfig, 'isProduction' | 'isProtected' | 'maxBotToken' | 'maxInitDataTtlSeconds' | 'miniAppOrigins'>;
  logger: Logger;
  staticRoot?: string;
  nowSeconds?: () => number;
  requestId?: () => string;
}>;

const header = (request: IncomingMessage, name: string): string | undefined => {
  const value = request.headers[name];
  return typeof value === 'string' ? value : undefined;
};

const routeFor = (pathname: string): string => {
  if (pathname === '/api/max/session') return '/api/max/session';
  if (pathname === '/health/live') return '/health/live';
  if (pathname === '/health/ready') return '/health/ready';
  return STATIC_FILES[pathname] ? '/static' : '/unknown';
};

export const rejectAuthQuery = (url: URL): void => {
  const forbidden = new Set(['initdata', 'userid', 'role']);
  for (const key of url.searchParams.keys()) {
    if (forbidden.has(key.toLowerCase())) throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'query' });
  }
};

export const buildMiniAppHandler = (dependencies: MaxMiniAppDependencies) => {
  const logger = dependencies.logger.child({ component: 'max.miniapp' });
  const root = resolve(dependencies.staticRoot ?? resolve(process.cwd(), 'miniapp'));
  const makeRequestId = dependencies.requestId ?? randomUUID;

  return async (request: IncomingMessage, response: ServerResponse): Promise<void> => {
    const requestId = makeRequestId();
    const startedAt = Date.now();
    let route = '/unknown';
    let origin: string | undefined;
    let isStatic = false;

    const headers = (): void => {
      response.setHeader('x-request-id', requestId);
      response.setHeader('x-content-type-options', 'nosniff');
      response.setHeader('referrer-policy', 'no-referrer');
      response.setHeader('permissions-policy', 'camera=(), microphone=(), geolocation=()');
      response.setHeader('cache-control', 'no-store');
      response.setHeader('content-security-policy', miniAppContentSecurityPolicy());
      response.setHeader('vary', 'Origin');
      if (!isStatic) response.setHeader('x-frame-options', 'DENY');
      if (dependencies.config.isProtected) response.setHeader('strict-transport-security', 'max-age=31536000; includeSubDomains');
      if (origin) response.setHeader('access-control-allow-origin', origin);
    };

    const sendJson = (status: number, payload: unknown, extra: Readonly<Record<string, string>> = {}): void => {
      if (response.headersSent || response.destroyed) return;
      const body = Buffer.from(JSON.stringify(payload), 'utf8');
      if (body.byteLength > MAX_MINI_APP_RESPONSE_BYTES) throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
      headers();
      response.setHeader('content-type', 'application/json; charset=utf-8');
      for (const [name, value] of Object.entries(extra)) response.setHeader(name, value);
      response.writeHead(status);
      response.end(body);
    };

    try {
      const url = new URL(request.url ?? '/', 'http://miniapp.invalid');
      route = routeFor(url.pathname);
      rejectAuthQuery(url);
      origin = header(request, 'origin');
      if (origin && !dependencies.config.miniAppOrigins.includes(origin)) {
        throw new AppError(ERROR_CODES.FORBIDDEN, 403);
      }

      if (request.method === 'OPTIONS') {
        const requestedMethod = header(request, 'access-control-request-method');
        const requestedHeaders = (header(request, 'access-control-request-headers') ?? '')
          .split(',').map((item) => item.trim().toLowerCase()).filter(Boolean);
        if (requestedMethod !== 'GET' || requestedHeaders.some((item) => !['x-max-init-data', 'content-type'].includes(item))) {
          throw new AppError(ERROR_CODES.FORBIDDEN, 403);
        }
        headers();
        response.setHeader('access-control-allow-methods', 'GET, OPTIONS');
        response.setHeader('access-control-allow-headers', 'X-Max-Init-Data, Content-Type');
        response.setHeader('access-control-max-age', '300');
        response.writeHead(204);
        response.end();
        return;
      }

      if (url.pathname === '/health/live' || url.pathname === '/health/ready') {
        if (request.method !== 'GET') {
          sendJson(405, { error: { code: ERROR_CODES.VALIDATION_FAILED, message: 'Method not allowed.', requestId } }, { allow: 'GET' });
          return;
        }
        sendJson(200, { status: url.pathname === '/health/live' ? 'ok' : 'ready' });
        return;
      }

      if (url.pathname === '/api/max/session') {
        if (request.method !== 'GET') {
          sendJson(405, { error: { code: ERROR_CODES.VALIDATION_FAILED, message: 'Method not allowed.', requestId } }, { allow: 'GET' });
          return;
        }
        const contentLength = header(request, 'content-length');
        if ((contentLength !== undefined && contentLength !== '0') || header(request, 'transfer-encoding') !== undefined) {
          throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'body' });
        }
        const initData = header(request, HEADER_NAME);
        if (!initData) throw new AppError(ERROR_CODES.AUTH_REQUIRED, 401);
        if (Buffer.byteLength(initData, 'utf8') > MAX_INIT_DATA_HEADER_BYTES) throw new AppError(ERROR_CODES.AUTH_INVALID, 401);
        validateMaxInitData(initData, {
          botToken: dependencies.config.maxBotToken,
          ttlSeconds: dependencies.config.maxInitDataTtlSeconds,
          ...(dependencies.nowSeconds ? { nowSeconds: dependencies.nowSeconds } : {}),
        });
        sendJson(200, { authenticated: true });
        return;
      }

      if (request.method !== 'GET') {
        sendJson(405, { error: { code: ERROR_CODES.VALIDATION_FAILED, message: 'Method not allowed.', requestId } }, { allow: 'GET, OPTIONS' });
        return;
      }

      const filename = STATIC_FILES[url.pathname];
      if (!filename || url.pathname.includes('\\') || url.pathname.split('/').some((part) => part.startsWith('.')) || url.pathname.endsWith('.map')) {
        throw new AppError(ERROR_CODES.VALIDATION_FAILED, 404);
      }
      const rootRealPath = await realpath(root);
      const filePath = resolve(root, filename);
      const fileRealPath = await realpath(filePath);
      if (!fileRealPath.startsWith(`${rootRealPath}${sep}`)) throw new AppError(ERROR_CODES.FORBIDDEN, 403);
      const fileInfo = await stat(fileRealPath);
      if (!fileInfo.isFile() || fileInfo.size > MAX_MINI_APP_RESPONSE_BYTES) throw new AppError(ERROR_CODES.FORBIDDEN, 403);
      const body = await readFile(fileRealPath);
      if (body.byteLength > MAX_MINI_APP_RESPONSE_BYTES) throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
      isStatic = true;
      headers();
      response.setHeader('content-type', CONTENT_TYPES[extname(filename)] ?? 'application/octet-stream');
      response.writeHead(200);
      response.end(body);
    } catch (error) {
      const status = error instanceof AppError ? error.status : 500;
      logger.warn({ requestId, method: request.method, route, status, durationMs: Date.now() - startedAt, error: errorToLogFields(error) });
      const payload = errorToPublicPayload(error, requestId);
      try {
        sendJson(status, payload);
      } catch {
        if (!response.headersSent && !response.destroyed) response.writeHead(500).end();
      }
    }
  };
};
