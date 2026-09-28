/* eslint-disable react-hooks/error-boundaries -- route handlers convert failures to HTTP responses. */
import { AreaBars, OgFrame, SmallList } from "@/features/og/components";
import { PALETTES } from "@/features/og/theme";
import { integer, text } from "@/features/og/format";
import { ogResponse } from "@/features/og/render";
import { fetchInternal, errorResponse, prepare } from "../shared";

export async function GET(request: Request) {
  try {
    const { context, ids, theme } = await prepare(request, 1, 3);
    const palette = PALETTES[theme];
    const programs = await Promise.all(ids.map((id) => fetchInternal<Record<string, unknown>>(context, `/programs/${encodeURIComponent(id)}/curriculum`)));
    return ogResponse(<OgFrame theme={theme} eyebrow="Учебный план" title="Нагрузка и содержание"><div style={{ display: "flex", gap: 18 }}>{programs.map((payload, index) => { const program = (payload.program ?? {}) as Record<string, unknown>; return <div key={ids[index]} style={{ display: "flex", flexDirection: "column", flex: 1, padding: 22, borderRadius: 16, background: palette.card, border: `1px solid ${palette.border}` }}><div style={{ display: "flex", fontSize: 24, fontWeight: 700, marginBottom: 12 }}>{text(program.name, ids[index])}</div><div style={{ display: "flex", fontSize: 19, color: palette.muted, marginBottom: 16 }}>{Array.isArray(payload.items) ? `${payload.items.length} дисциплин` : "количество дисциплин: нет данных"}</div><AreaBars breakdown={payload.areaBreakdown} palette={palette} /></div>; })}</div>{!programs.length && <SmallList palette={palette} items={["учебный план не найден", "проверьте source gap программы"]} />}</OgFrame>, 1200, 820);
  } catch (error) {
    return errorResponse(error);
  }
}
