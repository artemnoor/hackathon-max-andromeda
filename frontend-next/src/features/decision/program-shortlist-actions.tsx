"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useDecisionContext } from "./decision-context";
import type { Route } from "@/lib/router";
import type { ShortlistRole } from "@/lib/types";

export function ProgramShortlistActions({
  programId,
  navigate,
  compact = false,
}: {
  programId: string;
  navigate?: (route: Route) => void;
  compact?: boolean;
}) {
  const {
    context,
    isMutating,
    mutationError,
    markConsidered,
    addShortlist,
    removeShortlist,
    restoreShortlist,
    setRole,
    restoreExcluded,
  } = useDecisionContext();
  const [pending, setPending] = useState<string | null>(null);
  const entry = context?.state.choice.shortlistEntries.find((item) => item.programId === programId);
  const active = entry?.state === "active";
  const removed = entry?.state === "removed";
  const excluded = context?.state.choice.excludedProgramIds.includes(programId) ?? false;
  const considered = context?.state.choice.consideredProgramIds.includes(programId) ?? false;

  const run = async (key: string, operation: () => Promise<unknown>) => {
    setPending(key);
    try {
      await operation();
    } catch {
      // The provider retains the last server context and exposes the safe
      // error text. Do not report a local success for a failed mutation.
    } finally {
      setPending(null);
    }
  };
  const disabled = isMutating || pending !== null;

  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? "" : "pt-1"}`}>
      {!considered && !active && !removed && !excluded && (
        <Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => void run("consider", () => markConsidered(programId))}>
          Рассмотреть
        </Button>
      )}
      {active && (
        <>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => void run("role", () => setRole(programId, entry?.role === "primary" ? "alternative" : "primary"))}
          >
            {entry?.role === "primary" ? "Оставить альтернативой" : "Сделать основным"}
          </Button>
          <Button type="button" size="sm" variant="ghost" disabled={disabled} onClick={() => void run("remove", () => removeShortlist(programId))}>
            Убрать из shortlist
          </Button>
        </>
      )}
      {removed && (
        <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void run("restore", () => restoreShortlist(programId))}>
          Вернуть в shortlist
        </Button>
      )}
      {!active && !removed && !excluded && (
        <Button type="button" size="sm" disabled={disabled} onClick={() => void run("add", () => addShortlist(programId, "primary"))}>
          Добавить в shortlist
        </Button>
      )}
      {excluded && (
        <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={() => void run("restore-excluded", () => restoreExcluded(programId))}>
          Вернуть в предложения
        </Button>
      )}
      {navigate && active && (
        <Button type="button" size="sm" variant="ghost" onClick={() => navigate({ view: "decision" })}>
          К моему выбору
        </Button>
      )}
      {mutationError && <span className="basis-full text-xs text-destructive" role="status" aria-live="polite">{mutationError}</span>}
    </div>
  );
}

export function shortlistRoleLabel(role: ShortlistRole): string {
  return role === "primary" ? "Основная" : "Альтернатива";
}
