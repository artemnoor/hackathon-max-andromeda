"use client";

import { useEffect, useState } from "react";
import { ArrowRight, CalendarDays, Compass, GitCompare, MapPin, Route as RouteIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Loading, PageHeader, ScoreBadge, Tag } from "@/components/shared";
import { ApiError, getPersonalRoute } from "@/lib/api";
import { STEP_KIND_LABELS } from "@/lib/labels";
import { formatDateTime } from "@/lib/format";
import type { PersonalRouteResponse } from "@/lib/types";
import type { Route } from "@/lib/router";
import { ProgramShortlistActions } from "@/features/decision/program-shortlist-actions";

const STEP_ICON: Record<string, React.ComponentType<{ className?: string }>> = {
  explore_program: Compass,
  compare_programs: GitCompare,
  attend_event: CalendarDays,
};

/**
 * Compatibility/support surface. It consumes the legacy read-only endpoint,
 * but never gates the decision dashboard or mutates the shared shortlist.
 */
export function PersonalRoutePage({ navigate }: { navigate: (route: Route) => void }) {
  const [data, setData] = useState<PersonalRouteResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getPersonalRoute()
      .then((result) => {
        if (active) setData(result);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        if (reason instanceof ApiError && reason.status === 404) setNotFound(true);
        else setError("Дополнительные материалы временно недоступны.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  if (loading) return <Loading label="Загружаем дополнительные материалы…" />;
  if (error) return <ErrorState title="Поддержка выбора недоступна" message={error} />;
  if (notFound || !data) return <SupportEmptyState navigate={navigate} />;

  if (data.status === "no_recommendations" || data.steps.length === 0) {
    return <SupportEmptyState navigate={navigate} message={data.summary} />;
  }

  return (
    <div data-testid="personal-route-page" className="space-y-5">
      <PageHeader
        eyebrow="Поддержка выбора"
        title="Дополнительные шаги"
        description={`${data.summary} Это необязательные идеи: порядок решения и shortlist остаются за вами.`}
        actions={<Tag tone="muted">необязательно</Tag>}
      />

      <Card className="border-dashed">
        <CardContent className="p-4 text-sm text-muted-foreground">
          Материалы ниже собраны из уже доступных предложений, событий и площадок. Открытие этого раздела ничего не добавляет и не убирает в «Мой выбор».
        </CardContent>
      </Card>

      <div className="space-y-4" data-testid="personal-route-support-items">
        {data.steps.map((step) => {
          const Icon = STEP_ICON[step.kind] ?? RouteIcon;
          return (
            <Card key={step.position} className="relative">
              <CardContent className="p-5">
                <div className="mb-2 flex items-center gap-2">
                  <Icon className="h-4 w-4 text-primary" />
                  <span className="text-xs font-bold uppercase tracking-wide text-primary">
                    Дополнительно · {STEP_KIND_LABELS[step.kind] ?? "Материал"}
                  </span>
                </div>
                <p className="mb-3 text-sm text-muted-foreground">{step.reason}</p>

                {step.recommendation && (
                  <div className="mb-3 flex flex-col gap-3 rounded-lg border border-border/60 bg-card p-3 sm:flex-row sm:items-center">
                    <ScoreBadge value={step.recommendation.contentFit} />
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-xs text-primary">{step.recommendation.programCode}</p>
                      <button type="button" onClick={() => navigate({ view: "program", id: step.recommendation!.programId })} className="text-left font-semibold hover:text-primary">
                        {step.recommendation.programName}
                      </button>
                    </div>
                    <ProgramShortlistActions programId={step.recommendation.programId} compact />
                  </div>
                )}

                {step.event && (
                  <div className="mb-3 rounded-lg border border-border/60 bg-card p-3">
                    <button type="button" onClick={() => navigate({ view: "event", id: step.event!.id })} className="text-left font-semibold hover:text-primary">
                      {step.event.title}
                    </button>
                    <p className="mt-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                      <CalendarDays className="h-3 w-3" /> {formatDateTime(step.event.startsAt)}
                      {step.venue?.name && <><MapPin className="ml-2 h-3 w-3" /> {step.venue.name}</>}
                    </p>
                  </div>
                )}

                <div className="flex flex-wrap gap-2">
                  {step.kind === "explore_program" && step.programIds[0] && (
                    <Button size="sm" className="gap-1" onClick={() => navigate({ view: "program", id: step.programIds[0] })}>
                      Открыть программу <ArrowRight className="h-4 w-4" />
                    </Button>
                  )}
                  {step.kind === "compare_programs" && (
                    <Button size="sm" className="gap-1" onClick={() => navigate({ view: "compare" })}>
                      Сравнить варианты <ArrowRight className="h-4 w-4" />
                    </Button>
                  )}
                  {step.kind === "attend_event" && step.event && (
                    <Button size="sm" variant="outline" onClick={() => navigate({ view: "event", id: step.event!.id })}>
                      Подробнее о событии
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function SupportEmptyState({ navigate, message }: { navigate: (route: Route) => void; message?: string }) {
  return (
    <div data-testid="personal-route-empty">
      <PageHeader eyebrow="Поддержка выбора" title="Дополнительные шаги" description="Этот раздел необязателен и не заменяет «Мой выбор»." />
      <EmptyState
        title="Дополнительных материалов пока нет"
        message={message ?? "Можно начать с любого сценария — профтест не требуется для каталога, поступления или сравнения."}
        action={
          <div className="flex flex-wrap justify-center gap-2">
            <Button type="button" onClick={() => navigate({ view: "decision" })}>Открыть «Мой выбор»</Button>
            <Button type="button" variant="outline" onClick={() => navigate({ view: "catalog" })}>Открыть каталог</Button>
            <Button type="button" variant="outline" onClick={() => navigate({ view: "events" })}>Посмотреть события</Button>
          </div>
        }
      />
    </div>
  );
}
