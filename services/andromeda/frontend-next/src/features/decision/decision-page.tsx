"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Check, CircleAlert, Eye, RefreshCw, Sparkles, X } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState, explainSourceGap, ErrorState, Loading, PageHeader, SectionTitle, Stat, Tag } from "@/components/shared";
import { useDecisionContext } from "./decision-context";
import type { Route } from "@/lib/router";
import type { DecisionShortlistEntry, DecisionShortlistItem, DecisionSuggestion } from "@/lib/types";
import { trackDecisionEvent } from "@/lib/analytics";

export function DecisionPage({ navigate }: { navigate: (route: Route) => void }) {
  const {
    context,
    suggestions,
    activeShortlist,
    removedShortlist,
    primaryShortlist,
    alternativeShortlist,
    isLoading,
    isSuggestionsLoading,
    isMutating,
    error,
    mutationError,
    conflict,
    refresh,
    refreshSuggestions,
    clearMutationError,
    removeShortlist,
    restoreShortlist,
    setRole,
    acceptSuggestion,
    rejectSuggestion,
    selectFinalChoice,
    reopenFinalChoice,
  } = useDecisionContext();
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [choiceToConfirm, setChoiceToConfirm] = useState<string | null>(null);
  const returnedToChoiceRef = useRef(false);

  useEffect(() => {
    void refreshSuggestions();
  }, [refreshSuggestions]);

  useEffect(() => {
    if (context && !returnedToChoiceRef.current) {
      returnedToChoiceRef.current = true;
      trackDecisionEvent("shortlist_returned_to", { source: "decision", action: "return" });
    }
  }, [context]);

  useEffect(() => {
    if (isSuggestionsLoading || !suggestions) return;
    for (const candidate of suggestions.suggestions) {
      trackDecisionEvent(
        "system_suggestion_shown",
        { source: "suggestion", action: "show", programId: candidate.programId },
        { dedupeKey: `suggestion-shown:${suggestions.contextRevision}:${candidate.programId.replaceAll(":", "-")}` },
      );
    }
  }, [isSuggestionsLoading, suggestions]);

  const activeDetails = useMemo(
    () => new Map((suggestions?.activeShortlist ?? []).map((item) => [item.programId, item])),
    [suggestions],
  );
  const candidates = suggestions?.suggestions ?? [];
  const run = async (action: string, operation: () => Promise<unknown>) => {
    setPendingAction(action);
    clearMutationError();
    try {
      await operation();
    } catch {
      // The provider keeps the explicit server state and exposes a safe
      // message. This boundary only prevents an unhandled promise rejection.
    } finally {
      setPendingAction(null);
    }
  };

  if (isLoading && !context) return <Loading label="Загружаем ваш выбор…" />;
  if (!context && error) return <ErrorState title="Мой выбор недоступен" message={error} onRetry={() => void refresh()} />;
  if (!context) return <Loading label="Готовим пространство выбора…" />;

  const hasChoice = activeShortlist.length > 0 || removedShortlist.length > 0;
  const knownPreferences = Boolean(context.preferences);
  const knownAdmission = Boolean(context.state.admissionConstraints);
  const selectedProgramId = context.state.selectedProgramId ?? null;
  const selectedDetail = selectedProgramId ? activeDetails.get(selectedProgramId) : undefined;

  return (
    <div data-testid="decision-page" className="space-y-6">
      <PageHeader
        eyebrow="Ваш контекст выбора"
        title="Мой выбор"
        description="Здесь хранятся ваши варианты. Andromeda может предложить кандидатов и показать риски, но не принимает решение за вас."
        actions={
          <>
            <Button type="button" variant="outline" size="sm" onClick={() => void refreshSuggestions()} disabled={isSuggestionsLoading} className="gap-1">
              <RefreshCw className={`h-4 w-4 ${isSuggestionsLoading ? "animate-spin" : ""}`} /> Обновить предложения
            </Button>
            {activeShortlist.length >= 2 && (
              <Button type="button" size="sm" onClick={() => navigate({ view: "compare" })} className="gap-1">
                Сравнить <ArrowRight className="h-4 w-4" />
              </Button>
            )}
          </>
        }
      />

      {(error || mutationError) && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-300/60 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="status" aria-live="polite">
          <p className="flex items-start gap-2">
            <CircleAlert className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{mutationError ?? error}</span>
          </p>
          {conflict && <Button type="button" variant="outline" size="sm" onClick={() => void refresh()}>Обновить выбор</Button>}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Основные варианты" value={primaryShortlist.length} hint="ваше решение" />
        <Stat label="Альтернативы" value={alternativeShortlist.length} hint="ваше решение" />
        <Stat label="Ревизия" value={context.state.revision} hint="синхронизируется с сервером" />
        <Stat label="Профиль" value={context.profileRevision !== null && context.profileRevision !== undefined ? `v${context.profileRevision}` : "—"} hint={knownPreferences ? "данные актуальны" : "можно уточнить"} />
      </div>

      {!hasChoice && (
        <EmptyState
          title="Shortlist пока пуст"
          message="Начните с любого удобного сценария: откройте каталог, ответьте на несколько вопросов или сравните уже известные программы."
          action={
            <div className="flex flex-wrap justify-center gap-2">
              <Button type="button" onClick={() => navigate({ view: "catalog" })}>Открыть каталог</Button>
              <Button type="button" variant="outline" onClick={() => navigate({ view: "proftest" })}>Уточнить предпочтения</Button>
              <Button type="button" variant="outline" onClick={() => navigate({ view: "compare" })}>Сравнить программы</Button>
            </div>
          }
        />
      )}

      {hasChoice && (
        <>
          <ShortlistSection
            title="Основные варианты"
            hint="Программы, которые вы оставили в центре выбора"
            entries={primaryShortlist}
            details={activeDetails}
            emptyMessage="Пока нет основных вариантов. Сделайте основным одну из альтернатив."
            pendingAction={pendingAction}
            disabled={isMutating}
            navigate={navigate}
            onRemove={(id) => void run(`remove:${id}`, () => removeShortlist(id))}
            onSetRole={(id) => void run(`role:${id}`, () => setRole(id, "alternative"))}
          />
          <ShortlistSection
            title="Альтернативы"
            hint="Сохранённые вами запасные варианты"
            entries={alternativeShortlist}
            details={activeDetails}
            emptyMessage="Добавленные альтернативы появятся здесь."
            pendingAction={pendingAction}
            disabled={isMutating}
            navigate={navigate}
            onRemove={(id) => void run(`remove:${id}`, () => removeShortlist(id))}
            onSetRole={(id) => void run(`role:${id}`, () => setRole(id, "primary"))}
          />
          {removedShortlist.length > 0 && (
            <Card className="border-dashed">
              <CardHeader className="pb-3"><SectionTitle hint="ничего не удалено без вашего действия">Ранее сохранённые</SectionTitle></CardHeader>
              <CardContent className="space-y-2">
                {removedShortlist.map((entry) => (
                  <div key={entry.programId} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/60 p-3">
                    <div className="min-w-0">
                      <p className="truncate font-mono text-xs text-primary">{activeDetails.get(entry.programId)?.programCode ?? entry.programId}</p>
                      <p className="text-sm text-muted-foreground">{activeDetails.get(entry.programId)?.programName ?? "Название загрузится при восстановлении"}</p>
                    </div>
                    <Button type="button" size="sm" variant="outline" disabled={disabledFor(pendingAction, `restore:${entry.programId}`, isMutating)} onClick={() => void run(`restore:${entry.programId}`, () => restoreShortlist(entry.programId))}>
                      Вернуть
                    </Button>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </>
      )}

      {hasChoice && (
        <FinalChoiceCard
          selectedProgramId={selectedProgramId}
          selectedDetail={selectedDetail}
          activeShortlist={activeShortlist}
          details={activeDetails}
          choiceToConfirm={choiceToConfirm}
          disabled={isMutating}
          pendingAction={pendingAction}
          onRequestSelect={setChoiceToConfirm}
          onConfirmSelect={(id) => void run(`final:${id}`, async () => { await selectFinalChoice(id); setChoiceToConfirm(null); })}
          onReopen={() => void run("reopen-final", reopenFinalChoice)}
        />
      )}

      <Card>
        <CardHeader className="pb-3">
          <SectionTitle hint="derived data · не ваше решение"><span className="flex items-center gap-2"><Sparkles className="h-5 w-5 text-primary" /> Предложения системы</span></SectionTitle>
          <p className="text-sm text-muted-foreground">Мы показываем кандидатов на основе доступных данных. Добавление в shortlist требует вашего отдельного действия.</p>
        </CardHeader>
        <CardContent>
          {isSuggestionsLoading && <Loading label="Ищем кандидатов…" />}
          {!isSuggestionsLoading && candidates.length === 0 && (
            <div className="rounded-lg border border-dashed border-border p-5 text-sm text-muted-foreground">
              Предложений пока нет. {suggestions?.missingData.length ? `Нужно уточнить: ${suggestions.missingData.join(", ")}.` : "Можно начать с каталога или уточнить предпочтения."}
            </div>
          )}
          {!isSuggestionsLoading && candidates.length > 0 && (
            <div className="space-y-3">
              {candidates.map((candidate) => (
                <SuggestionCard
                  key={candidate.programId}
                  candidate={candidate}
                  disabled={isMutating}
                  pendingAction={pendingAction}
                  navigate={navigate}
                  onAccept={(id) => void run(`accept:${id}`, () => acceptSuggestion(id))}
                  onReject={(id) => void run(`reject:${id}`, () => rejectSuggestion(id))}
                />
              ))}
            </div>
          )}
          {suggestions?.sourceGaps.length ? <p className="mt-4 text-xs text-muted-foreground">Ограничения источников: {suggestions.sourceGaps.map(explainSourceGap).join(" ")}</p> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3"><SectionTitle>Что уже известно</SectionTitle></CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <KnownDataRow label="ЕГЭ и ограничения поступления" known={knownAdmission} action={() => navigate({ view: "catalog" })} actionLabel="Проверить в каталоге" />
          <KnownDataRow label="Предпочтения по содержанию программ" known={knownPreferences} action={() => navigate({ view: "proftest" })} actionLabel="Уточнить предпочтения" />
          <KnownDataRow label="Рассмотренные программы" known={context.state.choice.consideredProgramIds.length > 0} action={() => navigate({ view: "catalog" })} actionLabel="Открыть каталог" />
          <div className="rounded-lg border border-dashed border-border/70 p-3">
            <p className="text-sm font-medium">Неизвестно или требует источника</p>
            <p className="mt-1 text-sm text-muted-foreground">{context.missingData.length ? context.missingData.join(", ") : "Критичных пробелов пока нет"}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function disabledFor(pending: string | null, action: string, disabled: boolean): boolean {
  return disabled || pending === action;
}

function FinalChoiceCard({
  selectedProgramId,
  selectedDetail,
  activeShortlist,
  details,
  choiceToConfirm,
  disabled,
  pendingAction,
  onRequestSelect,
  onConfirmSelect,
  onReopen,
}: {
  selectedProgramId: string | null;
  selectedDetail?: DecisionShortlistItem;
  activeShortlist: DecisionShortlistEntry[];
  details: Map<string, DecisionShortlistItem>;
  choiceToConfirm: string | null;
  disabled: boolean;
  pendingAction: string | null;
  onRequestSelect: (programId: string | null) => void;
  onConfirmSelect: (programId: string) => void;
  onReopen: () => void;
}) {
  const title = selectedDetail?.programName ?? selectedProgramId ?? "Программа не выбрана";
  const university = selectedProgramId ? universityLabel(selectedProgramId) : null;
  return (
    <Card className="border-primary/40 bg-primary/[0.04]" data-testid="final-choice-card">
      <CardHeader className="pb-3"><SectionTitle hint="только ваше явное действие">Финальный выбор</SectionTitle></CardHeader>
      <CardContent className="space-y-4">
        {selectedProgramId ? (
          <div className="rounded-xl border border-primary/30 bg-background p-4">
            <p className="text-xs font-medium uppercase tracking-[0.16em] text-primary">Вы выбрали</p>
            <p className="mt-2 font-serif text-xl font-semibold">{title}</p>
            <p className="mt-1 text-sm text-muted-foreground">{university} · {selectedDetail?.programCode ?? selectedProgramId}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <Tag tone="muted">Поступление: {selectedDetail?.admissionStatus ?? selectedDetail?.admissionRisk ?? "нет данных"}</Tag>
              {selectedDetail?.contentFit && <Tag tone="primary">Content Fit: {selectedDetail.contentFit.contentFit}</Tag>}
              {selectedDetail?.sourceGaps.map((gap) => <Tag key={gap} tone="muted">{explainSourceGap(gap)}</Tag>)}
            </div>
            <p className="mt-3 text-sm text-muted-foreground">Это сохранённое решение не меняется от обновления рекомендаций. Можно открыть программу, сравнить её с shortlist или изменить выбор.</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button type="button" size="sm" variant="outline" disabled={disabled} onClick={onReopen}>Изменить выбор</Button>
            </div>
          </div>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">Выберите одну из сохранённых программ, когда будете готовы. Andromeda не назначает финальный вариант автоматически.</p>
            <div className="grid gap-2 md:grid-cols-2">
              {activeShortlist.map((entry) => {
                const detail = details.get(entry.programId);
                const confirming = choiceToConfirm === entry.programId;
                return (
                  <div key={entry.programId} className="rounded-lg border border-border/70 bg-background p-3">
                    <p className="font-medium">{detail?.programName ?? entry.programId}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{universityLabel(entry.programId)} · {detail?.admissionStatus ?? detail?.admissionRisk ?? "поступление: нет данных"}</p>
                    {!confirming ? (
                      <Button type="button" size="sm" className="mt-3" disabled={disabled} onClick={() => onRequestSelect(entry.programId)}>Выбрать эту программу</Button>
                    ) : (
                      <div className="mt-3 rounded-lg border border-amber-300/70 bg-amber-50 p-3 text-sm text-amber-950" role="dialog" aria-label="Подтверждение финального выбора">
                        <p>Сохранить этот вариант как финальный выбор?</p>
                        <div className="mt-2 flex gap-2"><Button type="button" size="sm" disabled={pendingAction === `final:${entry.programId}`} onClick={() => onConfirmSelect(entry.programId)}>Подтвердить</Button><Button type="button" size="sm" variant="ghost" onClick={() => onRequestSelect(null)}>Отмена</Button></div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function universityLabel(programId: string): string {
  const slug = programId.split(":")[1];
  if (slug === "bmstu") return "МГТУ им. Н. Э. Баумана";
  if (slug === "hse") return "НИУ ВШЭ";
  return slug ? `Университет: ${slug}` : "Университет не указан";
}

function ShortlistSection({
  title,
  hint,
  entries,
  details,
  emptyMessage,
  pendingAction,
  disabled,
  navigate,
  onRemove,
  onSetRole,
}: {
  title: string;
  hint: string;
  entries: DecisionShortlistEntry[];
  details: Map<string, DecisionShortlistItem>;
  emptyMessage: string;
  pendingAction: string | null;
  disabled: boolean;
  navigate: (route: Route) => void;
  onRemove: (programId: string) => void;
  onSetRole: (programId: string) => void;
}) {
  return (
    <Card>
      <CardHeader className="pb-3"><SectionTitle hint={hint}>{title}</SectionTitle></CardHeader>
      <CardContent className="space-y-3">
        {entries.length === 0 && <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">{emptyMessage}</p>}
        {entries.map((entry) => (
          <ShortlistCard
            key={entry.programId}
            entry={entry}
            detail={details.get(entry.programId)}
            disabled={disabled}
            pendingAction={pendingAction}
            navigate={navigate}
            onRemove={onRemove}
            onSetRole={onSetRole}
          />
        ))}
      </CardContent>
    </Card>
  );
}

function ShortlistCard({
  entry,
  detail,
  disabled,
  pendingAction,
  navigate,
  onRemove,
  onSetRole,
}: {
  entry: DecisionShortlistEntry;
  detail?: DecisionShortlistItem;
  disabled: boolean;
  pendingAction: string | null;
  navigate: (route: Route) => void;
  onRemove: (programId: string) => void;
  onSetRole: (programId: string) => void;
}) {
  const admission = detail?.admissionStatus ?? detail?.admissionRisk ?? "нет данных";
  return (
    <div className="rounded-xl border border-border/70 bg-card p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <p className="font-mono text-xs text-primary">{detail?.programCode ?? entry.programId}</p>
          <button type="button" className="mt-1 text-left font-serif text-lg font-semibold hover:text-primary" onClick={() => navigate({ view: "program", id: entry.programId })}>
            {detail?.programName ?? "Название программы пока недоступно"}
          </button>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Tag tone={entry.role === "primary" ? "primary" : "muted"}>{entry.role === "primary" ? "Основная" : "Альтернатива"}</Tag>
            <Tag tone="muted">Поступление: {admission}</Tag>
            {detail?.sourceGaps.map((gap) => <Tag key={gap} tone="muted">{explainSourceGap(gap)}</Tag>)}
          </div>
        </div>
        <p className="text-xs text-muted-foreground">сохранено вами</p>
      </div>
      {detail?.reasons.whyMayNotFit.length ? <p className="mt-3 text-sm text-muted-foreground">Что стоит проверить: {detail.reasons.whyMayNotFit.slice(0, 2).join("; ")}</p> : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button type="button" size="sm" variant="outline" disabled={disabledFor(pendingAction, `role:${entry.programId}`, disabled)} onClick={() => onSetRole(entry.programId)}>
          {entry.role === "primary" ? "Оставить альтернативой" : "Сделать основным"}
        </Button>
        <Button type="button" size="sm" variant="ghost" disabled={disabledFor(pendingAction, `remove:${entry.programId}`, disabled)} onClick={() => onRemove(entry.programId)}>
          Убрать из shortlist
        </Button>
      </div>
    </div>
  );
}

function SuggestionCard({
  candidate,
  disabled,
  pendingAction,
  navigate,
  onAccept,
  onReject,
}: {
  candidate: DecisionSuggestion;
  disabled: boolean;
  pendingAction: string | null;
  navigate: (route: Route) => void;
  onAccept: (programId: string) => void;
  onReject: (programId: string) => void;
}) {
  const contentFit = candidate.contentFit?.contentFit;
  return (
    <div className="rounded-xl border border-border/70 bg-background p-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <p className="font-mono text-xs text-primary">{candidate.programCode}</p>
          <button type="button" className="mt-1 text-left font-serif text-lg font-semibold hover:text-primary" onClick={() => navigate({ view: "program", id: candidate.programId })}>
            {candidate.programName}
          </button>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Tag tone="muted">Предложение системы</Tag>
            <Tag tone="muted">Поступление: {candidate.admissionStatus ?? candidate.admissionRisk}</Tag>
            {contentFit !== undefined && contentFit !== null && <Tag tone="primary">Content Fit: {contentFit}</Tag>}
          </div>
        </div>
        <Tag tone={candidate.partition === "alternative" ? "muted" : "primary"}>{candidate.partition === "alternative" ? "Альтернатива" : "Кандидат"}</Tag>
      </div>
      <div className="mt-4 grid gap-3 text-sm md:grid-cols-2">
        <ReasonList icon={<Check className="h-4 w-4 text-emerald-600" />} title="Почему включено" items={candidate.reasons.whyIncluded} empty="Недостаточно данных для объяснения" />
        <ReasonList icon={<Eye className="h-4 w-4 text-orange-600" />} title="Что может не подойти" items={candidate.reasons.whyMayNotFit} empty="Доказательств для этого вывода пока недостаточно." />
      </div>
      <ConstraintOutcomeList outcomes={candidate.constraintOutcomes} />
      {candidate.sourceGaps.length > 0 && <p className="mt-3 text-xs text-muted-foreground">{candidate.sourceGaps.map(explainSourceGap).join(" ")}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button type="button" size="sm" disabled={disabledFor(pendingAction, `accept:${candidate.programId}`, disabled)} onClick={() => onAccept(candidate.programId)}>Добавить в shortlist</Button>
        <Button type="button" size="sm" variant="outline" disabled={disabledFor(pendingAction, `reject:${candidate.programId}`, disabled)} onClick={() => onReject(candidate.programId)}>Не предлагать</Button>
      </div>
    </div>
  );
}

function ConstraintOutcomeList({ outcomes }: { outcomes: DecisionSuggestion["constraintOutcomes"] }) {
  if (outcomes.length === 0) return null;
  return <div className="mt-3 rounded-lg border border-border/60 bg-card/70 p-3 text-xs"><p className="font-medium">Проверка ваших условий</p><ul className="mt-1 space-y-1 text-muted-foreground">{outcomes.map((outcome) => <li key={outcome.dimension} className={outcome.satisfied === false ? "text-orange-800" : outcome.applicability === "insufficient_data" ? "text-amber-800" : undefined}>{constraintLabel(outcome.dimension)}: {outcome.message}</li>)}</ul></div>;
}

function constraintLabel(dimension: string): string {
  return { applicant_scores: "Баллы", admission_year: "Год", funding: "Финансирование", study_form: "Форма", max_tuition: "Стоимость", location: "Место" }[dimension] ?? dimension;
}

function ReasonList({ icon, title, items, empty }: { icon: React.ReactNode; title: string; items: string[]; empty: string }) {
  return (
    <div>
      <p className="mb-1 flex items-center gap-1.5 font-medium">{icon}{title}</p>
      {items.length > 0 ? <ul className="space-y-1 text-muted-foreground">{items.slice(0, 3).map((item) => <li key={item}>• {item}</li>)}</ul> : <p className="text-muted-foreground">{empty}</p>}
    </div>
  );
}

function KnownDataRow({ label, known, action, actionLabel }: { label: string; known: boolean; action: () => void; actionLabel: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border/70 p-3">
      <p className="flex items-center gap-2 text-sm"><span className={known ? "text-emerald-600" : "text-muted-foreground"}>{known ? "✓" : "—"}</span>{label}</p>
      {!known && <Button type="button" variant="ghost" size="sm" onClick={action}>{actionLabel}</Button>}
    </div>
  );
}
