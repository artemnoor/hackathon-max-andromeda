"use client";

import { ListChecks } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useDecisionContext } from "@/features/decision/decision-context";

export function ShortlistControl({ onOpen }: { onOpen: () => void }) {
  const { activeShortlist, isLoading } = useDecisionContext();
  const count = activeShortlist.length;

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={onOpen}
      aria-label={`Открыть shortlist, сохранено программ: ${count}`}
      data-testid="shortlist-control"
      className="relative gap-1.5"
    >
      <ListChecks className="h-4 w-4" />
      <span className="hidden sm:inline">Мой выбор</span>
      {!isLoading && count > 0 && (
        <span className="grid min-w-5 place-items-center rounded-full bg-primary px-1.5 text-[10px] font-semibold leading-5 text-primary-foreground">
          {count}
        </span>
      )}
    </Button>
  );
}
