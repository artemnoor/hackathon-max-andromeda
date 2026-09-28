"use client";

import { ArrowRight, Info } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DecisionPage } from "@/features/decision/decision-page";
import type { Route } from "@/lib/router";

/**
 * Compatibility adapter for bookmarks created before the decision-centered UX.
 *
 * The old route remains addressable, but it no longer owns a workflow or
 * fetches profile/recommendation/route data. DecisionPage is the sole dashboard
 * for the shared DecisionContext and all choice mutations remain explicit.
 */
export function UnifiedFlowPage({ navigate }: { navigate: (route: Route) => void }) {
  return (
    <div data-testid="legacy-flow-compat" className="space-y-4">
      <Card className="border-primary/20 bg-primary/[0.03]">
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-start gap-2 text-sm text-muted-foreground">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            Этот сохранённый адрес теперь открывает «Мой выбор». Ваш shortlist и другие данные не меняются автоматически.
          </p>
          <Button type="button" variant="outline" size="sm" onClick={() => navigate({ view: "decision" })} className="shrink-0 gap-1">
            Открыть «Мой выбор» <ArrowRight className="h-4 w-4" />
          </Button>
        </CardContent>
      </Card>
      <DecisionPage navigate={navigate} />
    </div>
  );
}
