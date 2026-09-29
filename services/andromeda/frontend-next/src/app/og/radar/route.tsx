/* eslint-disable react-hooks/error-boundaries -- route handlers convert failures to HTTP responses. */
import { OgFrame, SmallList } from "@/features/og/components";
import { PALETTES } from "@/features/og/theme";
import { ogResponse } from "@/features/og/render";
import { areaColor } from "@/lib/area-colors";
import { fetchInternal, errorResponse, prepare } from "../shared";

export async function GET(request: Request) {
  try {
    const { context, ids, theme } = await prepare(request, 2, 3);
    const summary = await fetchInternal<Record<string, unknown>>(context, `/compare/summary?programIds=${encodeURIComponent(ids.join(","))}`);
    const palette = PALETTES[theme];
    const programs = Array.isArray(summary.programs) ? summary.programs as Record<string, unknown>[] : [];
    const areas = [...new Set(programs.flatMap((program) => Array.isArray(program.areaBreakdown) ? (program.areaBreakdown as Record<string, unknown>[]).map((area) => String(area.code ?? area.area ?? "")) : []))].filter(Boolean).slice(0, 6);
    return ogResponse(<OgFrame theme={theme} eyebrow="Содержание" title="Профиль различий"><div style={{ display: "flex", gap: 24 }}>{programs.map((program) => <div key={String((program.program as Record<string, unknown> | undefined)?.id)} style={{ display: "flex", flexDirection: "column", flex: 1, padding: 20, border: `1px solid ${palette.border}`, borderRadius: 16, background: palette.card }}><div style={{ display: "flex", fontSize: 24, fontWeight: 700, marginBottom: 18 }}>{String((program.program as Record<string, unknown> | undefined)?.name ?? "Программа")}</div>{areas.map((code) => { const row = Array.isArray(program.areaBreakdown) ? (program.areaBreakdown as Record<string, unknown>[]).find((item) => String(item.code ?? item.area) === code) : undefined; return <div key={code} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 9, fontSize: 16 }}><span style={{ width: 10, height: 10, borderRadius: 5, background: areaColor(code) }} /><span style={{ flex: 1, overflow: "hidden" }}>{String(row?.name ?? code)}</span><span style={{ display: "flex" }}>{row?.share ? `${Math.round(Number(row.share) * 100)}%` : "—"}</span></div>; })}</div>)}</div>{!programs.length && <SmallList palette={palette} items={["сравнение недоступно", "исходные curriculum данные отсутствуют"]} />}</OgFrame>, 1200, 800);
  } catch (error) {
    return errorResponse(error);
  }
}
