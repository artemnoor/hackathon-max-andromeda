import { createHmac, timingSafeEqual } from "node:crypto";

const MAX_SIGNATURE_AGE_SECONDS = 120;

export type OgRequestContext = {
  request: Request;
  query: string;
  cookie: string | null;
};

export function authorizeOgRequest(request: Request): OgRequestContext {
  const url = new URL(request.url);
  const query = normalizeQuery(url.searchParams);
  const timestamp = request.headers.get("x-andromeda-render-timestamp");
  const signature = request.headers.get("x-andromeda-render-signature");
  const secret = process.env.ANDROMEDA_RENDER_HMAC_SECRET;
  if (!secret || !timestamp || !signature || !/^\d+$/.test(timestamp)) {
    throw new OgHttpError(401, "invalid render signature");
  }
  const age = Math.abs(Math.floor(Date.now() / 1000) - Number(timestamp));
  if (age > MAX_SIGNATURE_AGE_SECONDS) throw new OgHttpError(401, "expired render signature");
  const expected = createHmac("sha256", secret)
    .update(`${request.method}\n${url.pathname}\n${query}\n${timestamp}`)
    .digest("hex");
  const actualBuffer = Buffer.from(signature, "utf8");
  const expectedBuffer = Buffer.from(expected, "utf8");
  if (actualBuffer.length !== expectedBuffer.length || !timingSafeEqual(actualBuffer, expectedBuffer)) {
    throw new OgHttpError(401, "invalid render signature");
  }
  return { request, query, cookie: request.headers.get("cookie") };
}

export async function fetchInternal<T>(context: OgRequestContext, path: string, init: RequestInit = {}): Promise<T> {
  const baseUrl = (process.env.ANDROMEDA_INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://backend:8020").replace(/\/$/, "");
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (context.cookie) headers.set("cookie", context.cookie);
  const publicPath = path.startsWith("/api/v1/") ? path : `/api/v1${path}`;
  const response = await fetch(`${baseUrl}${publicPath}`, { ...init, headers, cache: "no-store" });
  if (!response.ok) throw new OgHttpError(response.status, "internal API request failed");
  return (await response.json()) as T;
}

export function normalizeQuery(params: URLSearchParams): string {
  return [...params.entries()]
    .filter(([, value]) => value !== "")
    .sort(([leftKey, leftValue], [rightKey, rightValue]) => leftKey.localeCompare(rightKey) || leftValue.localeCompare(rightValue))
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    .join("&");
}

export function parseIds(value: string | null, min = 1, max = 3): string[] {
  const ids = (value ?? "").split(",").map((item) => item.trim()).filter(Boolean);
  if (ids.length < min || ids.length > max || new Set(ids).size !== ids.length || ids.some((id) => !/^program:[A-Za-z0-9._:-]+$/.test(id))) {
    throw new OgHttpError(400, "invalid program ids");
  }
  return ids;
}

export class OgHttpError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

export function errorResponse(error: unknown): Response {
  if (error instanceof OgHttpError) return Response.json({ error: error.message }, { status: error.status });
  return Response.json({ error: "render failed" }, { status: 502 });
}
