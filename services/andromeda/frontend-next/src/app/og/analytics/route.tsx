/* eslint-disable react-hooks/error-boundaries -- route handlers convert failures to HTTP responses. */
import { AnalyticsMetricTable, OgFrame } from "@/features/og/components";
import { PALETTES } from "@/features/og/theme";
import { ogResponse } from "@/features/og/render";
import { fetchInternal, errorResponse, OgHttpError, prepare } from "../shared";

const ALLOWED_METRICS = new Set(["math_share", "programming_share", "ai_share", "physics_share", "business_share", "analytics_share"]);

export async function GET(request: Request) {
  try {
    const { context, ids, theme } = await prepare(request, 1, 3);
    const url = new URL(request.url);
    const metric = url.searchParams.get("metric") ?? "math_share";
    if (!ALLOWED_METRICS.has(metric)) throw new OgHttpError(400, "unsupported analytics metric");
    const result = await fetchInternal<{ rows?: unknown[] }>(context, "/analytics/query", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ entity: "program", metrics: [metric], scope: "program", scopeIds: ids, limit: 3 }),
    });
    const palette = PALETTES[theme];
    return ogResponse(<OgFrame theme={theme} eyebrow="Аналитика учебного плана" title={`Метрика: ${metric}`}><AnalyticsMetricTable result={result} metric={metric} palette={palette} /></OgFrame>, 1200, 800);
  } catch (error) {
    return errorResponse(error);
  }
}
