import { authorizeOgRequest, errorResponse, fetchInternal, OgHttpError, parseIds, type OgRequestContext } from "@/lib/server-api";
import { parseTheme, type OgTheme } from "@/features/og/theme";

export async function prepare(request: Request, minIds = 1, maxIds = 3): Promise<{ context: OgRequestContext; ids: string[]; theme: OgTheme }> {
  const context = authorizeOgRequest(request);
  const url = new URL(request.url);
  return { context, ids: parseIds(url.searchParams.get("ids"), minIds, maxIds), theme: parseTheme(url.searchParams.get("theme")) };
}

export { errorResponse, fetchInternal, OgHttpError };
