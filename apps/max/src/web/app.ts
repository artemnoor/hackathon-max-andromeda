import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { readFile, realpath, stat } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';
import type { IncomingMessage, ServerResponse } from 'node:http';

import type { AppConfig } from '../shared/config.js';
import { AppError, ERROR_CODES, errorToPublicPayload, errorToLogFields } from '../shared/errors.js';
import type { Logger } from '../shared/logger.js';
import { validateMaxInitData } from '../max/auth/init-data.js';
import { miniAppContentSecurityPolicy } from './static-policy.js';
import { catalogPathRequiresLaunch, catalogPublicPath, fetchCatalogPayload } from './catalog-proxy.js';

export const MAX_MINI_APP_RESPONSE_BYTES = 4 * 1024 * 1024;
const MAX_INIT_DATA_HEADER_BYTES = 16 * 1024;
const MAX_PUBLIC_API_BODY_BYTES = 64 * 1024;
const HEADER_NAME = 'x-max-init-data';
const CONTENT_TYPES: Readonly<Record<string, string>> = Object.freeze({
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
});

const loadStaticFiles = (root: string): Readonly<Record<string, string>> => {
  const manifest = JSON.parse(readFileSync(resolve(root, '.vite', 'manifest.json'), 'utf8')) as unknown;
  if (manifest === null || typeof manifest !== 'object' || Array.isArray(manifest)) throw new Error('Invalid Mini App asset manifest');
  const files: Record<string, string> = { '/': 'index.html', '/index.html': 'index.html' };
  for (const entry of Object.values(manifest)) {
    if (entry === null || typeof entry !== 'object' || Array.isArray(entry)) throw new Error('Invalid Mini App asset entry');
    const record = entry as Record<string, unknown>;
    const assets = [record['file'], ...(Array.isArray(record['css']) ? record['css'] : []), ...(Array.isArray(record['assets']) ? record['assets'] : [])];
    for (const asset of assets) {
      if (typeof asset !== 'string' || !/^assets\/[A-Za-z0-9._-]+\.(?:js|css|svg|png|woff2)$/u.test(asset)) {
        throw new Error('Invalid Mini App asset path');
      }
      files[`/${asset}`] = asset;
    }
  }
  return Object.freeze(files);
};

export type MaxMiniAppDependencies = Readonly<{
  config: Pick<AppConfig, 'isProduction' | 'isProtected' | 'maxBotToken' | 'maxInitDataTtlSeconds' | 'miniAppOrigins'> & Partial<Pick<AppConfig, 'andromedaProfileCookieName'>>;
  logger: Logger;
  staticRoot?: string;
  publicApiBaseUrl?: string;
  publicApiTimeoutMs?: number;
  fetcher?: typeof fetch;
  nowSeconds?: () => number;
  requestId?: () => string;
}>;

const header = (request: IncomingMessage, name: string): string | undefined => {
  const value = request.headers[name];
  return typeof value === 'string' ? value : undefined;
};

const readPublicApiBody = async (request: IncomingMessage): Promise<string> => {
  if (header(request, 'content-type')?.split(';', 1)[0]?.trim().toLowerCase() !== 'application/json') {
    throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'content_type' });
  }
  const declaredLength = Number(header(request, 'content-length') ?? 0);
  if (Number.isFinite(declaredLength) && declaredLength > MAX_PUBLIC_API_BODY_BYTES) {
    throw new AppError(ERROR_CODES.VALIDATION_FAILED, 413, undefined, { field: 'body' });
  }
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const value of request) {
    const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
    size += chunk.byteLength;
    if (size > MAX_PUBLIC_API_BODY_BYTES) throw new AppError(ERROR_CODES.VALIDATION_FAILED, 413, undefined, { field: 'body' });
    chunks.push(chunk);
  }
  const body = Buffer.concat(chunks).toString('utf8');
  let payload: unknown;
  try { payload = JSON.parse(body) as unknown; } catch { throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'json' }); }
  if (payload === null || typeof payload !== 'object' || Array.isArray(payload)) throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'json' });
  return body;
};

const routeFor = (pathname: string, staticFiles: Readonly<Record<string, string>>): string => {
  if (pathname === '/api/max/session') return '/api/max/session';
  if (pathname.startsWith('/api/max/catalog/') || pathname.startsWith('/api/max/data/')) return '/api/max/catalog';
  if (pathname === '/health/live') return '/health/live';
  if (pathname === '/health/ready') return '/health/ready';
  return staticFiles[pathname] ? '/static' : '/unknown';
};

export const rejectAuthQuery = (url: URL): void => {
  const forbidden = new Set(['initdata', 'userid', 'role']);
  for (const key of url.searchParams.keys()) {
    if (forbidden.has(key.toLowerCase())) throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'query' });
  }
};

export const buildMiniAppHandler = (dependencies: MaxMiniAppDependencies) => {
  const logger = dependencies.logger.child({ component: 'max.miniapp' });
  const root = resolve(dependencies.staticRoot ?? resolve(process.cwd(), 'miniapp-frontend', 'dist'));
  const staticFiles = loadStaticFiles(root);
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
      route = routeFor(url.pathname, staticFiles);
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

      if (route === '/api/max/catalog') {
        if (request.method !== 'GET' && request.method !== 'POST') {
          sendJson(405, { error: { code: ERROR_CODES.VALIDATION_FAILED, message: 'Method not allowed.', requestId } }, { allow: 'GET, POST' });
          return;
        }
        const contentLength = header(request, 'content-length');
        if (request.method === 'GET' && ((contentLength !== undefined && contentLength !== '0') || header(request, 'transfer-encoding') !== undefined)) {
          throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'body' });
        }
        const requestBody = request.method === 'POST' ? await readPublicApiBody(request) : undefined;
        const publicPath = catalogPublicPath(url, request.method);
        if (!publicPath) throw new AppError(ERROR_CODES.VALIDATION_FAILED, 404);
        if (catalogPathRequiresLaunch(url, request.method)) {
          const initData = header(request, HEADER_NAME);
          if (!initData) throw new AppError(ERROR_CODES.AUTH_REQUIRED, 401);
          if (Buffer.byteLength(initData, 'utf8') > MAX_INIT_DATA_HEADER_BYTES) throw new AppError(ERROR_CODES.AUTH_INVALID, 401);
          validateMaxInitData(initData, {
            botToken: dependencies.config.maxBotToken,
            ttlSeconds: dependencies.config.maxInitDataTtlSeconds,
            ...(dependencies.nowSeconds ? { nowSeconds: dependencies.nowSeconds } : {}),
          });
        }
        if (!dependencies.publicApiBaseUrl) throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503);
        const cookieName = dependencies.config.andromedaProfileCookieName ?? 'andromeda_profile_session';
        const profileToken = header(request, 'cookie')?.split(';').map((item) => item.trim())
          .find((item) => item.startsWith(`${cookieName}=`))?.slice(cookieName.length + 1);
        const profileCookie = profileToken && /^[A-Za-z0-9_-]{32,256}$/u.test(profileToken)
          ? `${cookieName}=${profileToken}`
          : undefined;
        const upstream = await fetchCatalogPayload(
          dependencies.publicApiBaseUrl, publicPath,
          dependencies.publicApiTimeoutMs ?? 10_000,
          dependencies.fetcher,
          profileCookie,
          request.method,
          requestBody,
        );
        sendJson(200, upstream.payload, upstream.setCookie ? { 'set-cookie': upstream.setCookie } : {});
        return;
      }

      if (request.method !== 'GET') {
        sendJson(405, { error: { code: ERROR_CODES.VALIDATION_FAILED, message: 'Method not allowed.', requestId } }, { allow: 'GET, OPTIONS' });
        return;
      }

      const filename = staticFiles[url.pathname];
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
