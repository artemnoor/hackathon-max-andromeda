/* eslint-disable react-hooks/error-boundaries -- route handlers convert failures to HTTP responses. */
import { OgFrame, ProgramCard, SmallList } from "@/features/og/components";
import { PALETTES } from "@/features/og/theme";
import { ogResponse } from "@/features/og/render";
import { fetchInternal, errorResponse, prepare } from "../shared";

export async function GET(request: Request) {
  try {
    const { context, ids, theme } = await prepare(request, 1, 1);
    const payload = await fetchInternal<{ program: Record<string, unknown> }>(context, `/programs/${encodeURIComponent(ids[0]!)}`);
    const palette = PALETTES[theme];
    return ogResponse(<OgFrame theme={theme} eyebrow="Образовательная программа" title={String(payload.program.name ?? "Программа")}><ProgramCard program={payload.program} palette={palette} /><div style={{ display: "flex", flexDirection: "column", gap: 9, padding: 22, borderLeft: `4px solid ${palette.secondary}` }}><div style={{ display: "flex", fontSize: 24, fontWeight: 700 }}>Что проверить перед выбором</div><SmallList palette={palette} items={["содержание учебного плана", "Admission Fit и качество источников", "различия с финальными кандидатами"]} /></div></OgFrame>);
  } catch (error) {
    return errorResponse(error);
  }
}
