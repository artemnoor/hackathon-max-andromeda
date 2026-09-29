/* eslint-disable react-hooks/error-boundaries -- route handlers convert failures to HTTP responses. */
import { OgFrame, SmallList } from "@/features/og/components";
import { PALETTES } from "@/features/og/theme";
import { ogResponse } from "@/features/og/render";
import { fetchInternal, errorResponse, prepare } from "../shared";

export async function GET(request: Request) {
  try {
    const { context, theme } = await prepare(request, 0, 3);
    const suggestions = await fetchInternal<Record<string, unknown>>(context, "/decision/suggestions");
    const palette = PALETTES[theme];
    const shortlist = Array.isArray(suggestions.activeShortlist) ? suggestions.activeShortlist as Record<string, unknown>[] : [];
    const gaps = Array.isArray(suggestions.sourceGaps) ? suggestions.sourceGaps : [];
    return ogResponse(<OgFrame theme={theme} eyebrow="Дайджест" title="Что известно о вашем выборе сейчас"><div style={{ display: "flex", gap: 18 }}><div style={{ display: "flex", flexDirection: "column", flex: 1, padding: 24, borderRadius: 16, background: palette.card, border: `1px solid ${palette.border}` }}><div style={{ display: "flex", fontSize: 26, fontWeight: 700, marginBottom: 14 }}>Shortlist</div><SmallList palette={palette} items={shortlist.map((item) => item.programName ?? item.programId)} empty="пока пуст" /></div><div style={{ display: "flex", flexDirection: "column", flex: 1, padding: 24, borderRadius: 16, background: palette.card, border: `1px solid ${palette.border}` }}><div style={{ display: "flex", fontSize: 26, fontWeight: 700, marginBottom: 14 }}>Source gaps</div><SmallList palette={palette} items={gaps} empty="нет дополнительных gaps" /></div></div><div style={{ display: "flex", padding: 20, borderLeft: `4px solid ${palette.primary}` }}><SmallList palette={palette} items={["новости, дедлайны и события не добавляются без официального live-источника", "сравнение и Admission Fit доступны отдельно"]} /></div></OgFrame>, 1200, 760);
  } catch (error) {
    return errorResponse(error);
  }
}
