/* eslint-disable react-hooks/error-boundaries -- route handlers convert failures to HTTP responses. */
import { ComparisonMatrix, Legend, OgFrame, SmallList } from "@/features/og/components";
import { PALETTES } from "@/features/og/theme";
import { ogResponse } from "@/features/og/render";
import { fetchInternal, errorResponse, prepare } from "../shared";

export async function GET(request: Request) {
  try {
    const { context, ids, theme } = await prepare(request, 2, 3);
    const summary = await fetchInternal<Record<string, unknown>>(context, `/compare/summary?programIds=${encodeURIComponent(ids.join(","))}`);
    const palette = PALETTES[theme];
    const sourceGaps = Array.isArray(summary.sourceGaps) ? summary.sourceGaps : [];
    const tradeoffs = Array.isArray(summary.tradeoffs) ? summary.tradeoffs.map((item) => typeof item === "object" && item !== null ? `${String((item as Record<string, unknown>).advantage ?? "")} · ${String((item as Record<string, unknown>).consideration ?? "")}` : String(item)) : [];
    return ogResponse(<OgFrame theme={theme} eyebrow="Сравнение" title="Чем программы отличаются?"><ComparisonMatrix summary={summary} palette={palette} /><div style={{ display: "flex", gap: 18 }}><div style={{ display: "flex", flexDirection: "column", flex: 1, padding: 18, borderRadius: 14, background: palette.card, border: `1px solid ${palette.border}` }}><div style={{ display: "flex", fontSize: 22, fontWeight: 700, marginBottom: 10 }}>Trade-offs</div><SmallList palette={palette} items={tradeoffs} /></div><div style={{ display: "flex", flexDirection: "column", flex: 1, padding: 18, borderRadius: 14, background: palette.card, border: `1px solid ${palette.border}` }}><div style={{ display: "flex", fontSize: 22, fontWeight: 700, marginBottom: 10 }}>Источники</div><SmallList palette={palette} items={sourceGaps} empty="source gaps не обнаружены" /></div></div><Legend palette={palette} rows={[{ label: "содержание", color: palette.secondary }, { label: "источник / риск", color: palette.primary }]} /></OgFrame>, 1200, 900);
  } catch (error) {
    return errorResponse(error);
  }
}
