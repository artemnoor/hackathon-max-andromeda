/* eslint-disable react-hooks/error-boundaries -- route handlers convert failures to HTTP responses. */
import { OgFrame, ProgramCard, SmallList } from "@/features/og/components";
import { PALETTES } from "@/features/og/theme";
import { ogResponse } from "@/features/og/render";
import { fetchInternal, errorResponse, prepare } from "../shared";

export async function GET(request: Request) {
  try {
    const { context, theme } = await prepare(request, 0, 3);
    const suggestions = await fetchInternal<Record<string, unknown>>(context, "/decision/suggestions");
    const palette = PALETTES[theme];
    const items = Array.isArray(suggestions.activeShortlist) ? suggestions.activeShortlist as Record<string, unknown>[] : [];
    return ogResponse(<OgFrame theme={theme} eyebrow="Мой выбор" title={items.length ? "Сохранённый shortlist" : "Shortlist пока пуст"}><div style={{ display: "flex", flexDirection: "column", gap: 14 }}>{items.slice(0, 5).map((item) => <ProgramCard key={String(item.programId)} program={{ id: item.programId, code: item.programCode, name: item.programName }} palette={palette} risk={String(item.admissionRisk ?? "")} />)}</div>{!items.length && <SmallList palette={palette} items={["добавьте программу из каталога", "сравните финальные варианты", "проверьте реалистичность поступления"]} />}</OgFrame>, 1200, Math.max(760, 230 + Math.min(items.length, 5) * 125));
  } catch (error) {
    return errorResponse(error);
  }
}
