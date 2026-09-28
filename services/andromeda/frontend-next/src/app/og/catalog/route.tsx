/* eslint-disable react-hooks/error-boundaries -- route handlers convert failures to HTTP responses. */
import { OgFrame, SmallList } from "@/features/og/components";
import { PALETTES } from "@/features/og/theme";
import { ogResponse } from "@/features/og/render";
import { fetchInternal, errorResponse, prepare } from "../shared";

export async function GET(request: Request) {
  try {
    const { context, theme } = await prepare(request, 0, 3);
    const payload = await fetchInternal<{ items: Record<string, unknown>[] }>(context, "/programs");
    const palette = PALETTES[theme];
    const items = payload.items ?? [];
    return ogResponse(<OgFrame theme={theme} eyebrow="Каталог" title="Актуальные программы"><SmallList palette={palette} items={items.slice(0, 12).map((item) => `${String(item.code ?? "")} · ${String(item.name ?? "Программа")}`)} empty="каталог пуст" /></OgFrame>, 1200, 760);
  } catch (error) {
    return errorResponse(error);
  }
}
