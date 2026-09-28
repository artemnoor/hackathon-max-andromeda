"use client";

import { useEffect, useState } from "react";
import { Sparkles, Check, CircleAlert } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { explainSourceGap, PageHeader, Loading, ErrorState, ScoreBadge, Stat, Tag } from "@/components/shared";
import type { DecisionSuggestion } from "@/lib/types";
import type { Route } from "@/lib/router";
import { useDecisionContext } from "@/features/decision/decision-context";

export function RecommendationsPage({ navigate }: { navigate: (route: Route) => void }) {
  const {
    suggestions,
    isSuggestionsLoading,
    error,
    mutationError,
    acceptSuggestion,
    rejectSuggestion,
    refreshSuggestions,
  } = useDecisionContext();
  const [pendingSuggestion, setPendingSuggestion] = useState<string | null>(null);

  useEffect(() => {
    void refreshSuggestions();
  }, [refreshSuggestions]);

  const accept = async (candidate: DecisionSuggestion) => {
    setPendingSuggestion(candidate.programId);
    try {
      await acceptSuggestion(candidate.programId, candidate.partition === "alternative" ? "alternative" : "primary");
      await refreshSuggestions();
    } catch {
      // The provider exposes the safe mutation error and preserves state.
    } finally {
      setPendingSuggestion(null);
    }
  };
  const reject = async (candidate: DecisionSuggestion) => {
    setPendingSuggestion(candidate.programId);
    try {
      await rejectSuggestion(candidate.programId);
      await refreshSuggestions();
    } catch {
      // The provider exposes the safe mutation error and preserves state.
    } finally {
      setPendingSuggestion(null);
    }
  };

  if (isSuggestionsLoading && !suggestions) return <Loading label="Ищем кандидатов по доступным данным…" />;
  if (!suggestions && error) {
    return (
      <div data-testid="recommendations-page">
        <PageHeader eyebrow="Подобрать" title="Предложения системы" description="Система не скрывает недоступность расчёта за сообщением о незаполненном профиле." />
        <ErrorState title="Предложения временно недоступны" message={error} onRetry={() => void refreshSuggestions()} />
      </div>
    );
  }
  if (!suggestions) return <Loading label="Готовим предложения системы…" />;
  return (
    <div data-testid="recommendations-page">
        <PageHeader
          eyebrow="Подобрать"
          title="Предложения системы"
          description="Это объяснимые кандидаты для вашего выбора, а не решение за вас. Admission risk, Content Fit и пробелы данных показаны отдельно."
          actions={<Button variant="outline" size="sm" onClick={() => void refreshSuggestions()} disabled={isSuggestionsLoading} className="gap-1"><Sparkles className="h-4 w-4" /> Обновить</Button>}
        />
        {mutationError && <p className="mb-4 flex items-center gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-950" role="status" aria-live="polite"><CircleAlert className="h-4 w-4" />{mutationError}</p>}
        <Card className="mb-6">
          <CardContent className="grid gap-4 p-4 md:grid-cols-3">
            <Stat label="Основных кандидатов" value={suggestions.primaryCandidates.length} hint="предлагает система" />
            <Stat label="Альтернатив" value={suggestions.alternativeCandidates.length} hint="предлагает система" />
            <Stat label="Ревизия контекста" value={suggestions.contextRevision} hint="explicit choice не меняется от GET" />
          </CardContent>
        </Card>
        {suggestions.suggestions.length > 0 ? (
          <div className="space-y-3">
            {suggestions.suggestions.map((candidate) => <DecisionSuggestionCard key={candidate.programId} candidate={candidate} pending={pendingSuggestion === candidate.programId || pendingSuggestion !== null} onAccept={() => void accept(candidate)} onReject={() => void reject(candidate)} navigate={navigate} />)}
          </div>
        ) : (
          <Card className="border-dashed"><CardContent className="p-6 text-sm text-muted-foreground">Кандидаты пока не сформированы. {suggestions.missingData.length ? `Не хватает данных: ${suggestions.missingData.join(", ")}.` : "Откройте каталог или уточните предпочтения."}</CardContent></Card>
        )}
    </div>
  );
}
function DecisionSuggestionCard({
  candidate,
  pending,
  onAccept,
  onReject,
  navigate,
}: {
  candidate: DecisionSuggestion;
  pending: boolean;
  onAccept: () => void;
  onReject: () => void;
  navigate: (route: Route) => void;
}) {
  const fit = candidate.contentFit?.contentFit;
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="min-w-0">
            <p className="font-mono text-xs text-primary">{candidate.programCode}</p>
            <button type="button" onClick={() => navigate({ view: "program", id: candidate.programId })} className="mt-1 text-left font-serif text-lg font-semibold hover:text-primary">{candidate.programName}</button>
            <div className="mt-2 flex flex-wrap gap-1.5">
              <Tag tone="muted">Системное предложение</Tag>
              <Tag tone="muted">Поступление: {candidate.admissionStatus ?? candidate.admissionRisk}</Tag>
              {fit !== undefined && fit !== null && <ScoreBadge value={fit} />}
            </div>
          </div>
          <Tag tone={candidate.partition === "alternative" ? "muted" : "primary"}>{candidate.partition === "alternative" ? "Альтернатива" : "Основной кандидат"}</Tag>
        </div>
        <div className="mt-4 grid gap-3 text-sm md:grid-cols-2">
          <div><p className="mb-1 flex items-center gap-1 font-medium"><Check className="h-4 w-4 text-emerald-600" />Почему включено</p><p className="text-muted-foreground">{candidate.reasons.whyIncluded.join("; ") || "Недостаточно данных для объяснения"}</p></div>
          <div><p className="mb-1 font-medium">Что может не подойти</p><p className="text-muted-foreground">{candidate.reasons.whyMayNotFit.join("; ") || "Доказательств для этого вывода пока недостаточно."}</p></div>
        </div>
        {candidate.sourceGaps.length > 0 && <p className="mt-3 text-xs text-muted-foreground">Данные: {candidate.sourceGaps.map(explainSourceGap).join(" ")}</p>}
        <div className="mt-4 flex flex-wrap gap-2">
          <Button type="button" size="sm" disabled={pending} onClick={onAccept}>Добавить в shortlist</Button>
          <Button type="button" size="sm" variant="outline" disabled={pending} onClick={onReject}>Не предлагать</Button>
        </div>
      </CardContent>
    </Card>
  );
}
