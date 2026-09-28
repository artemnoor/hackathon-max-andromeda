import { describe, expect, it, vi } from "vitest";

import { createAndromedaPublicClient } from "./public-api-client";
import type { paths } from "./public-api.generated";

describe("generated Public API v1 client", () => {
  it("uses the public path and includes browser-managed cookie credentials", async () => {
    const fetchMock = vi.fn(async (_request: Request) =>
      new Response(JSON.stringify({ status: "live" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const client = createAndromedaPublicClient({
      baseUrl: "https://andromeda.example.test/",
      fetch: fetchMock,
    });

    const result = await client.GET("/api/v1/health/live");

    expect(result.data).toEqual({ status: "live" });
    expect(fetchMock).toHaveBeenCalledOnce();
    const request = fetchMock.mock.calls[0]?.[0];
    expect(request?.url).toBe("https://andromeda.example.test/api/v1/health/live");
    expect(request?.credentials).toBe("include");
  });

  it("does not type internal routes as Public API v1 operations", () => {
    const publicPath: keyof paths = "/api/v1/health/live";
    expect(publicPath).toBe("/api/v1/health/live");
    // @ts-expect-error internal operations are intentionally absent from the public OpenAPI surface
    const privatePath: keyof paths = "/api/v1/ops/knowledge/review-queue";
    void privatePath;
  });
});
