/* eslint-disable react-hooks/error-boundaries -- route handlers convert failures to HTTP responses. */
import { OgFrame, SmallList } from "@/features/og/components";
import { PALETTES } from "@/features/og/theme";
import { statusLabel, text } from "@/features/og/format";
import { ogResponse } from "@/features/og/render";
import { fetchInternal, errorResponse, prepare } from "../shared";

export async function GET(request: Request) {
  try {
    const { context, theme } = await prepare(request, 0, 3);
    const suggestions = await fetchInternal<Record<string, unknown>>(context, "/decision/suggestions");
    const palette = PALETTES[theme];
    const source = [...(Array.isArray(suggestions.primaryCandidates) ? suggestions.primaryCandidates : []), ...(Array.isArray(suggestions.alternativeCandidates) ? suggestions.alternativeCandidates : [])].slice(0, 5) as Record<string, unknown>[];
    return ogResponse(<OgFrame theme={theme} eyebrow="Поступление" title="Реалистичность вариантов"><div style={{ display: "flex", flexDirection: "column", gap: 18 }}>{source.map((item) => { const status = item.admissionStatus ?? item.admissionRisk; return <div key={String(item.programId)} style={{ display: "flex", alignItems: "center", gap: 18, fontSize: 22 }}><div style={{ display: "flex", width: 310, fontWeight: 700 }}>{text(item.programName)}</div><div style={{ flex: 1, height: 22, borderRadius: 11, background: palette.border, display: "flex" }}><div style={{ display: "flex", paddingLeft: 12, color: palette.muted, fontSize: 17 }}>статус по доступным данным</div></div><div style={{ display: "flex", width: 250, color: palette.secondary }}>{statusLabel(status)}</div></div>; })}</div>{!source.length && <SmallList palette={palette} items={["добавьте баллы в DecisionContext", "отсутствие данных не означает невозможность оценки"]} />}</OgFrame>, 1200, 760);
  } catch (error) {
    return errorResponse(error);
  }
}
