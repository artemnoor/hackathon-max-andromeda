"use client";

import { useEffect, useMemo } from "react";
import { ArrowRight, ListChecks, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tag } from "@/components/shared";
import { useDecisionContext } from "./decision-context";
import type { Route } from "@/lib/router";

export function ShortlistDrawer({
  open,
  onClose,
  navigate,
}: {
  open: boolean;
  onClose: () => void;
  navigate: (route: Route) => void;
}) {
  const { activeShortlist, suggestions } = useDecisionContext();
  const details = useMemo(
    () => new Map((suggestions?.activeShortlist ?? []).map((item) => [item.programId, item])),
    [suggestions],
  );

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50" data-testid="shortlist-drawer">
      <button
        type="button"
        aria-label="Закрыть мой выбор"
        className="absolute inset-0 h-full w-full cursor-default bg-slate-950/30"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortlist-drawer-title"
        className="absolute right-0 top-0 flex h-full w-full max-w-md flex-col border-l border-border bg-background shadow-2xl"
      >
        <div className="flex items-center justify-between border-b border-border/70 px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">Сохранённый выбор</p>
            <h2 id="shortlist-drawer-title" className="font-serif text-xl font-semibold">Мой shortlist</h2>
          </div>
          <Button autoFocus type="button" variant="ghost" size="icon" onClick={onClose} aria-label="Закрыть">
            <X className="h-5 w-5" />
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5 warm-scroll">
          {activeShortlist.length === 0 ? (
            <div className="flex min-h-56 flex-col items-center justify-center gap-3 text-center">
              <span className="grid h-12 w-12 place-items-center rounded-full bg-accent text-accent-foreground">
                <ListChecks className="h-6 w-6" />
              </span>
              <h3 className="font-serif text-lg font-semibold">Пока ничего не сохранено</h3>
              <p className="max-w-xs text-sm text-muted-foreground">Добавляйте программы из каталога, карточки программы или предложений системы.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {activeShortlist.map((entry) => {
                const item = details.get(entry.programId);
                return (
                  <div key={entry.programId} className="rounded-xl border border-border/70 bg-card p-3">
                    <div className="flex items-start justify-between gap-3">
                      <button
                        type="button"
                        className="min-w-0 text-left"
                        onClick={() => { onClose(); navigate({ view: "program", id: entry.programId }); }}
                      >
                        <span className="block truncate font-mono text-xs text-primary">{item?.programCode ?? entry.programId}</span>
                        <span className="mt-1 block line-clamp-2 text-sm font-medium hover:text-primary">
                          {item?.programName ?? "Название программы пока недоступно"}
                        </span>
                      </button>
                      <Tag tone={entry.role === "primary" ? "primary" : "muted"}>
                        {entry.role === "primary" ? "Основная" : "Альтернатива"}
                      </Tag>
                    </div>
                    {item?.admissionRisk && item.admissionRisk !== "unknown" && (
                      <p className="mt-2 text-xs text-muted-foreground">Поступление: {item.admissionRisk}</p>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="border-t border-border/70 p-5">
          <div className="flex flex-col gap-2 sm:flex-row">
            {activeShortlist.length >= 2 && (
              <Button type="button" className="flex-1 gap-1" onClick={() => { onClose(); navigate({ view: "compare" }); }}>
                Сравнить <ArrowRight className="h-4 w-4" />
              </Button>
            )}
            <Button type="button" variant="outline" className="flex-1" onClick={() => { onClose(); navigate({ view: "decision" }); }}>
              Открыть мой выбор
            </Button>
          </div>
        </div>
      </aside>
    </div>
  );
}
