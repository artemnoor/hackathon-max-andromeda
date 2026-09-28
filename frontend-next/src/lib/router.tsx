"use client";

import { useCallback, useEffect, useState } from "react";

export type View =
  | "home"
  | "assistant"
  | "decision"
  | "catalog"
  | "program"
  | "compare"
  | "proftest"
  | "admission"
  | "recommendations"
  | "events"
  | "event"
  | "personal-route"
  | "flow"
  | "account"
  | "ops"
  | "university-admin"
  | "knowledge-review"
  | "university-catalog";

export type Route = {
  view: View;
  id?: string;
  origin?: "source" | "university";
  universityId?: string;
};

const DEFAULT_ROUTE: Route = { view: "home" };

function parseSearch(search: string): Route {
  const params = new URLSearchParams(search);
  const view = (params.get("view") as View | null) ?? "home";
  const id = params.get("id") ?? undefined;
  const eventId = params.get("eventId") ?? undefined;
  const origin = params.get("origin") as Route["origin"] | null;
  const universityId = params.get("universityId") ?? undefined;
  if (view === "event") return { view, id: eventId, origin: origin ?? "source", universityId };
  return { view, id };
}

export function buildHref(route: Route): string {
  const params = new URLSearchParams();
  params.set("view", route.view);
  if (route.view === "event" && route.id) params.set("eventId", route.id);
  else if (route.id) params.set("id", route.id);
  if (route.view === "event" && route.origin) params.set("origin", route.origin);
  if (route.view === "event" && route.universityId) params.set("universityId", route.universityId);
  const qs = params.toString();
  return qs ? `/?${qs}` : "/";
}

export function useRouter(): {
  route: Route;
  navigate: (route: Route) => void;
} {
  // Start with a stable default for SSR/first render to avoid hydration mismatch,
  // then sync to the real URL on the client.
  const [route, setRoute] = useState<Route>(DEFAULT_ROUTE);

  useEffect(() => {
    setRoute(parseSearch(window.location.search));
    const onPop = () => setRoute(parseSearch(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((next: Route) => {
    const href = buildHref(next);
    if (href === window.location.pathname + window.location.search) return;
    window.history.pushState({}, "", href);
    setRoute(next);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  return { route, navigate };
}

export const NAV_ITEMS: { view: View; label: string; icon: string }[] = [
  { view: "decision", label: "Мой выбор", icon: "ListChecks" },
  { view: "catalog", label: "Каталог", icon: "Library" },
  { view: "compare", label: "Сравнить", icon: "GitCompare" },
  { view: "proftest", label: "Подобрать", icon: "Compass" },
  { view: "admission", label: "Поступление", icon: "GraduationCap" },
  { view: "recommendations", label: "Предложения", icon: "Sparkles" },
  { view: "events", label: "События", icon: "CalendarDays" },
  { view: "personal-route", label: "Поддержка", icon: "Route" },
  { view: "university-catalog", label: "Вузы", icon: "Building2" },
];
