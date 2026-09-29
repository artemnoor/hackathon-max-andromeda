import createClient from "openapi-fetch";

import type { paths } from "./public-api.generated";

export type AndromedaPublicClientOptions = {
  /** Backend origin or an API gateway base URL; it must not contain a session token. */
  baseUrl: string;
  /** Optional transport adapter, useful for server-side clients and tests. */
  fetch?: (request: Request) => Promise<Response>;
};

export function createAndromedaPublicClient({
  baseUrl,
  fetch: fetchImplementation,
}: AndromedaPublicClientOptions) {
  const normalizedBaseUrl = baseUrl.trim().replace(/\/+$/, "");
  if (!normalizedBaseUrl) throw new Error("Andromeda Public API baseUrl is required");

  return createClient<paths>({
    baseUrl: normalizedBaseUrl,
    credentials: "include",
    ...(fetchImplementation ? { fetch: fetchImplementation } : {}),
  });
}
