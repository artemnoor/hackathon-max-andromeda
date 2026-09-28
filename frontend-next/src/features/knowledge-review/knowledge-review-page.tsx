"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Clock3, ExternalLink, FileSearch, GitCompareArrows, ShieldAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/shared";
import {
  ApiError,
  applyKnowledgeReviewAction,
  getAuthSession,
  getKnowledgeReviewQueue,
  previewKnowledgeReviewPolicy,
} from "@/lib/api";
import type {
  KnowledgeReviewAction,
  KnowledgeReviewClaimPropositionRequest,
  KnowledgeReviewPreviewContext,
  KnowledgeReviewPolicyPreview,
  KnowledgeReviewQueue,
} from "@/lib/api";
import type { AuthSession } from "@/lib/types";
import { formatDateTime } from "@/lib/format";
import type { Route } from "@/lib/router";

type QueueItem = KnowledgeReviewQueue["items"][number];
type ReviewDecision = Extract<KnowledgeReviewAction, "approve" | "reject" | "edit" | "resolve_identity" | "mark_unresolved" | "mark_duplicate" | "merge">;
type ReviewDecisionPayload = { editedProposition?: KnowledgeReviewClaimPropositionRequest; canonicalSubjectId?: string };

const REVIEW_ACTIONS: Array<{ action: ReviewDecision; label: string; variant: "default" | "destructive" | "outline" }> = [
  { action: "approve", label: "Подтвердить утверждение источника", variant: "default" },
  { action: "reject", label: "Отклонить", variant: "destructive" },
  { action: "mark_unresolved", label: "Оставить неразрешённым", variant: "outline" },
];

function itemKey(item: QueueItem): string {
  return `${item.target.kind}:${item.target.objectId}:${item.target.revision}:${item.target.revisionHash}`;
}

function newIdempotencyKey(): string {
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(32));
  const digest = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `review-idempotency:${digest}`;
}

function updatedProposition(
  proposition: NonNullable<QueueItem["proposition"]>,
  predicate: string,
  valueText: string,
  unit: string,
): KnowledgeReviewClaimPropositionRequest {
  const common = {
    predicate,
    subjectKind: proposition.subject_kind,
    subjectId: proposition.subject_id,
    unit: unit.trim() || null,
  };
  switch (proposition.value.kind) {
    case "boolean":
      return { ...common, value: { kind: "boolean", value: valueText === "true" } };
    case "decimal":
      return { ...common, value: { kind: "decimal", value: valueText } };
    case "date":
      return { ...common, value: { kind: "date", value: valueText } };
    case "datetime":
      return { ...common, value: { kind: "datetime", value: valueText } };
    case "identifier":
      return { ...common, value: { kind: "identifier", value: valueText } };
    case "text":
      return { ...common, value: { kind: "text", value: valueText } };
  }
}

function reviewStateLabel(state: string): string {
  const labels: Record<string, string> = {
    needs_review: "Нужна проверка",
    unreviewed: "Не проверено",
    unresolved: "Ранее оставлено без решения",
    pending: "Ожидает решения policy steward",
  };
  return labels[state] ?? "Статус требует проверки";
}

function sourceTierLabel(tier?: string | null): string {
  const labels: Record<string, string> = {
    primary_normative: "Первичный нормативный документ",
    official_issuer: "Официальная публикация регулятора",
    official_university: "Официальный источник вуза",
    trusted_secondary: "Проверенный вторичный источник",
    unverified_secondary: "Непроверенный вторичный источник",
    community: "Сообщество",
    user_supplied: "Источник предоставлен пользователем",
    unknown: "Надёжность источника неизвестна",
  };
  return tier ? labels[tier] ?? "Класс источника не распознан" : "Класс надёжности не установлен";
}

function lifecycleLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    rumor: "Слух",
    hypothesis: "Гипотеза",
    announced: "Объявлено",
    proposal: "Предложение",
    draft: "Проект документа",
    under_review: "На рассмотрении",
    adopted: "Принято, публикация не подтверждена",
    published: "Опубликовано",
    future_effective: "Начнёт действовать позднее",
    effective: "Действует",
    superseded: "Заменено новой редакцией",
    repealed: "Отменено",
    withdrawn: "Отозвано",
    rejected: "Отклонено",
    unknown: "Юридический статус не установлен",
  };
  return value ? labels[value] ?? "Юридический статус требует проверки" : "Не указано";
}

export function KnowledgeReviewPage({ navigate }: { navigate: (route: Route) => void }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [queue, setQueue] = useState<KnowledgeReviewQueue | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [relatedTargetKey, setRelatedTargetKey] = useState("");
  const [loading, setLoading] = useState(true);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [policyPreview, setPolicyPreview] = useState<KnowledgeReviewPolicyPreview | null>(null);
  const [policyPreviewContext, setPolicyPreviewContext] = useState<KnowledgeReviewPreviewContext | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setErrorStatus(null);
    setNotice(null);
    try {
      const nextSession = await getAuthSession();
      setSession(nextSession);
      if (!nextSession.authenticated) {
        setQueue(null);
        return;
      }
      const result = await getKnowledgeReviewQueue();
      setQueue(result);
      setSelectedKey((current) => current && result.items.some((item) => itemKey(item) === current)
        ? current
        : result.items[0] ? itemKey(result.items[0]) : null);
    } catch (error) {
      setErrorStatus(error instanceof ApiError ? error.status : 500);
      setQueue(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadQueue();
  }, [loadQueue]);

  const items = queue?.items ?? [];
  const selected = useMemo(
    () => items.find((item) => itemKey(item) === selectedKey) ?? null,
    [items, selectedKey],
  );
  const duplicateCandidates = useMemo(
    () => items.filter((item) => item.target.kind === selected?.target.kind && itemKey(item) !== selectedKey),
    [items, selected?.target.kind, selectedKey],
  );

  useEffect(() => {
    setPolicyPreview(null);
    setPolicyPreviewContext(null);
  }, [selectedKey]);

  const previewPolicy = async (context: KnowledgeReviewPreviewContext) => {
    if (!selected || selected.target.kind !== "policy_rule" || previewing || submitting) return;
    setPreviewing(true);
    setPolicyPreview(null);
    setPolicyPreviewContext(null);
    setNotice(null);
    try {
      const result = await previewKnowledgeReviewPolicy({ target: selected.target, context });
      setPolicyPreview(result.preview);
      setPolicyPreviewContext(context);
      setNotice("Построен read-only preview для точной ревизии и заданного контекста.");
    } catch (error) {
      setNotice(error instanceof ApiError && error.status === 409
        ? "Кандидат больше не ожидает решения или ревизия устарела. Обновите очередь и постройте preview заново."
        : "Preview недоступен. Это не подтверждает отсутствие правила или влияния.");
    } finally {
      setPreviewing(false);
    }
  };

  const decide = async (action: ReviewDecision, payload?: ReviewDecisionPayload) => {
    if (!selected || !reason.trim() || submitting) return;
    const isPolicy = selected.target.kind === "policy_rule";
    if (isPolicy && (!policyPreview || !policyPreviewContext || !["approve", "reject"].includes(action))) return;
    if (!isPolicy && ["approve", "reject"].includes(action) && selected.evidence.length === 0) return;
    const duplicateAction = action === "merge" || action === "mark_duplicate";
    const related = duplicateCandidates.find((item) => itemKey(item) === relatedTargetKey);
    if (duplicateAction && !related) {
      setNotice("Для отметки дубликата выберите точную связанную запись из очереди.");
      return;
    }
    const dateText = selected.effectiveFrom ? `; дата действия ${formatDateTime(selected.effectiveFrom)}` : "";
    const confirmation = isPolicy
      ? `${action === "approve" ? "Подтвердить" : "Отклонить"} policy revision ${selected.target.objectId}, rev ${selected.target.revision}, hash ${selected.target.revisionHash.slice(0, 12)}; preview ${policyPreview?.preview_id}. ${dateText} Продолжить?`
      : `Действие ${action} для ${selected.target.objectId}, ревизия ${selected.target.revision}${dateText}. Для утверждения будет подтверждено только то, что источник содержит это утверждение; policy rule автоматически не активируется. Продолжить?`;
    if (!window.confirm(confirmation)) return;

    setSubmitting(true);
    setNotice(null);
    try {
      await applyKnowledgeReviewAction({
        target: selected.target,
        action,
        reason: reason.trim(),
        idempotencyKey: newIdempotencyKey(),
        relatedTarget: duplicateAction && related ? related.target : undefined,
        ...(isPolicy && policyPreview && policyPreviewContext ? {
          policyPreviewFingerprint: policyPreview.preview_id.split(":").at(-1),
          policyPreviewContext,
        } : {}),
        ...(payload?.editedProposition ? { editedProposition: payload.editedProposition } : {}),
        ...(payload?.canonicalSubjectId ? { canonicalSubjectId: payload.canonicalSubjectId } : {}),
      });
      setReason("");
      setRelatedTargetKey("");
      setPolicyPreview(null);
      setPolicyPreviewContext(null);
      setNotice("Решение записано в неизменяемый журнал. Очередь обновлена.");
      await loadQueue();
    } catch (error) {
      setNotice(error instanceof ApiError && error.status === 409
        ? "Ревизия устарела или действие конфликтует с другим решением. Обновите очередь и проверьте запись заново."
        : "Не удалось записать решение. Проверьте доступ и повторно загрузите очередь.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <Loading label="Проверяем доступ и загружаем очередь review…" />;
  if (!session?.authenticated) {
    return <Card><CardContent className="space-y-4 p-7"><PageHeader eyebrow="Внутренняя проверка" title="Войдите, чтобы продолжить" description="Review queue доступна только назначенным проверяющим и policy stewards." /><Button onClick={() => navigate({ view: "account" })}>Открыть кабинет и войти</Button></CardContent></Card>;
  }
  if (errorStatus === 401) return <ErrorState title="Сессия истекла" message="Войдите снова, затем откройте очередь review." onRetry={() => navigate({ view: "account" })} />;
  if (errorStatus === 403 || errorStatus === 404) return <EmptyState title="Нет доступа к очереди" message="Для этого аккаунта не назначена роль knowledge reviewer или policy steward." />;
  if (errorStatus) return <ErrorState title="Очередь недоступна" message="Не удалось загрузить внутренние review данные. Это не означает, что ожидающих записей нет." onRetry={() => void loadQueue()} />;

  return (
    <div data-testid="knowledge-review-page">
      <PageHeader
        eyebrow="Внутренняя проверка"
        title="Очередь знаний"
        description="Проверьте source assertion и происхождение каждой ревизии. Подтверждение claim фиксирует содержание источника, но само по себе не делает правило действующим."
        actions={<Button variant="outline" onClick={() => void loadQueue()}>Обновить очередь</Button>}
      />
      {notice && <p className="mb-4 rounded-lg border border-border bg-muted/40 px-4 py-3 text-sm" role="status" aria-live="polite">{notice}</p>}
      {queue?.truncated && <p className="mb-4 rounded-lg border border-amber-500/40 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="status">Показана ограниченная часть очереди. Используйте обновление после обработки элементов.</p>}
      {items.length === 0 ? (
        <EmptyState title="Очередь сейчас пуста" message="Нет доступных ожидающих ревизий в текущем срезе. Недоступность источника не интерпретируется как отсутствие правила." />
      ) : (
        <div className="grid items-start gap-5 xl:grid-cols-[minmax(17rem,0.8fr)_minmax(0,1.6fr)]">
          <section aria-label="Ожидающие ревизии" className="space-y-3">
            <h2 className="text-sm font-semibold text-muted-foreground">{items.length} записей в срезе</h2>
            {items.map((item) => (
              <button
                key={itemKey(item)}
                type="button"
                aria-pressed={itemKey(item) === selectedKey}
                onClick={() => { setSelectedKey(itemKey(item)); setReason(""); setNotice(null); }}
                className={`w-full rounded-xl border p-4 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${itemKey(item) === selectedKey ? "border-primary bg-primary/5" : "border-border bg-card hover:border-primary/50"}`}
              >
                <span className="flex items-start justify-between gap-3">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{item.title}</span>
                    <span className="mt-1 block text-xs text-muted-foreground">{item.target.kind.replaceAll("_", " ")} · ревизия {item.target.revision}</span>
                  </span>
                  <span className="shrink-0 rounded-full bg-muted px-2.5 py-1 text-xs">{reviewStateLabel(item.reviewState)}</span>
                </span>
                <span className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground"><Clock3 className="h-3.5 w-3.5" />{formatDateTime(item.createdAt)}</span>
              </button>
            ))}
          </section>

          {selected && <ReviewDetails
            item={selected}
            reason={reason}
            onReasonChange={setReason}
            relatedTargetKey={relatedTargetKey}
            onRelatedTargetChange={setRelatedTargetKey}
            duplicateCandidates={duplicateCandidates}
            submitting={submitting}
            onDecide={(action, payload) => void decide(action, payload)}
            onPolicyPreview={(context) => void previewPolicy(context)}
            policyPreview={policyPreview}
            policyPreviewContext={policyPreviewContext}
            previewing={previewing}
          />}
        </div>
      )}
    </div>
  );
}

export function ReviewDetails({
  item,
  reason,
  onReasonChange,
  relatedTargetKey,
  onRelatedTargetChange,
  duplicateCandidates,
  submitting,
  onDecide,
  onPolicyPreview = () => undefined,
  policyPreview = null,
  policyPreviewContext = null,
  previewing = false,
}: {
  item: QueueItem;
  reason: string;
  onReasonChange: (value: string) => void;
  relatedTargetKey: string;
  onRelatedTargetChange: (value: string) => void;
  duplicateCandidates: QueueItem[];
  submitting: boolean;
  onDecide: (action: ReviewDecision, payload?: ReviewDecisionPayload) => void;
  onPolicyPreview?: (context: KnowledgeReviewPreviewContext) => void;
  policyPreview?: KnowledgeReviewPolicyPreview | null;
  policyPreviewContext?: KnowledgeReviewPreviewContext | null;
  previewing?: boolean;
}) {
  const policyTarget = item.target.kind === "policy_rule";
  const unresolvedConflict = item.conflictsTruncated || item.conflicts.some((conflict) => conflict.state === "open");
  const [universityId, setUniversityId] = useState("");
  const [admissionYear, setAdmissionYear] = useState("");
  const [validAsOf, setValidAsOf] = useState("");
  const [directionId, setDirectionId] = useState("");
  const [programId, setProgramId] = useState("");
  const [admissionRoute, setAdmissionRoute] = useState("");
  const [competitionType, setCompetitionType] = useState("");
  const [applicantCategory, setApplicantCategory] = useState("");
  const [editPredicate, setEditPredicate] = useState(item.proposition?.predicate ?? "");
  const [editValue, setEditValue] = useState(String(item.proposition?.value.value ?? ""));
  const [editUnit, setEditUnit] = useState(item.proposition?.unit ?? "");
  const [identitySubjectId, setIdentitySubjectId] = useState(item.proposition?.subject_id ?? "");
  const identityResolutionSupported = item.proposition && ["university", "direction", "program"].includes(item.proposition.subject_kind);
  useEffect(() => {
    setEditPredicate(item.proposition?.predicate ?? "");
    setEditValue(String(item.proposition?.value.value ?? ""));
    setEditUnit(item.proposition?.unit ?? "");
    setIdentitySubjectId(item.proposition?.subject_id ?? "");
  }, [item.target.objectId, item.target.revision, item.target.revisionHash, item.proposition]);

  const submitPreview = () => {
    const date = new Date(validAsOf);
    const year = Number(admissionYear);
    if (!universityId.trim() || !Number.isInteger(year) || year < 2000 || year > 2100 || Number.isNaN(date.valueOf())) return;
    const values: NonNullable<KnowledgeReviewPreviewContext["applicability"]>["values"] = [];
    const optionalValues = [
      ["direction_id", directionId],
      ["program_id", programId],
      ["admission_route", admissionRoute],
      ["competition_type", competitionType],
      ["applicant_category", applicantCategory],
    ] as const;
    for (const [field, value] of optionalValues) {
      if (value.trim()) values.push({ field, availability: "present", origin: "user_provided", value: value.trim() });
    }
    onPolicyPreview({
      universityId: universityId.trim() as KnowledgeReviewPreviewContext["universityId"],
      admissionYear: year as KnowledgeReviewPreviewContext["admissionYear"],
      validAsOf: date.toISOString(),
      applicability: { values },
    });
  };
  const previewCanBeApproved = policyPreview?.candidate_trace.status === "resolved"
    && policyPreview.impact.status === "complete"
    && !unresolvedConflict;
  return (
    <article className="min-w-0 space-y-4" aria-label={`Детали ${item.target.objectId}`}>
      <Card>
        <CardHeader><CardTitle className="break-all text-lg">{item.title}</CardTitle><p className="text-sm text-muted-foreground">{item.target.objectId} · ревизия {item.target.revision} · hash {item.target.revisionHash.slice(0, 12)}</p></CardHeader>
        <CardContent className="space-y-5">
          <dl className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border p-3"><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Источник и надёжность</dt><dd className="mt-1 text-sm">{item.evidence.length ? sourceTierLabel(item.evidence[0]?.reliabilityTier) : "Evidence не найдена"}</dd></div>
            <div className="rounded-lg border p-3"><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Статус правила в источнике</dt><dd className="mt-1 text-sm">{lifecycleLabel(item.policyLifecycle ?? item.claimedStage)}</dd></div>
            <div className="rounded-lg border p-3"><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Область</dt><dd className="mt-1 break-words text-sm">{item.policyScope ?? "Scope в policy revision не задан"}</dd></div>
            <div className="rounded-lg border p-3"><dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Дата вступления в силу</dt><dd className="mt-1 text-sm">{item.effectiveFrom ? formatDateTime(item.effectiveFrom) : "Не установлена"}</dd></div>
          </dl>

          <section className="rounded-lg border bg-muted/20 p-4"><h3 className="text-sm font-semibold">Текущее canonical состояние</h3><p className="mt-1 text-sm text-muted-foreground">{item.canonicalSummary}</p></section>

          {item.assertionText && <section><h3 className="mb-2 text-sm font-semibold">Утверждение источника</h3><blockquote className="rounded-lg border-l-2 border-primary bg-muted/30 px-4 py-3 text-sm leading-relaxed">{item.assertionText}</blockquote><p className="mt-2 text-xs text-muted-foreground">Извлечено способом: {item.extractionMethod ?? "не указан"}; {item.extractor ?? "версия extractor не указана"}; confidence: {item.confidence ?? "не оценена"}.</p></section>}

          {item.proposition && <section className="rounded-lg border bg-muted/20 p-4"><h3 className="text-sm font-semibold">Typed proposition</h3><p className="mt-1 break-all text-xs text-muted-foreground">{item.proposition.subject_kind}{item.proposition.subject_id ? ` · ${item.proposition.subject_id}` : " · canonical subject не разрешён"}</p><pre className="mt-2 overflow-auto rounded bg-background p-3 text-xs">{JSON.stringify(item.proposition, null, 2)}</pre></section>}

          {item.relatedAssertions.length > 0 && <section><h3 className="mb-2 text-sm font-semibold">Связанные утверждения</h3><ul className="space-y-2">{item.relatedAssertions.map((assertion, index) => <li key={`${index}-${assertion}`} className="rounded-lg bg-muted/30 p-3 text-sm">{assertion}</li>)}</ul><p className="mt-2 break-all text-xs text-muted-foreground">Claim IDs: {item.linkedClaimIds.join(", ")}</p></section>}

          <section>
            <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><FileSearch className="h-4 w-4" /> Evidence и provenance</h3>
            {item.evidence.length === 0 ? <p className="rounded-lg border border-amber-500/40 bg-amber-50 p-3 text-sm text-amber-950">Evidence недоступна. Решение по записи заблокировано.</p> : <ul className="space-y-3">{item.evidence.map((evidence) => <li key={`${evidence.sourceObservationId}:${evidence.sourceUrl}:${evidence.page ?? ""}`} className="rounded-lg border p-3">
              <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="font-medium">{evidence.sourceName ?? evidence.sourceId}</p><p className="text-xs text-muted-foreground">Надёжность: {sourceTierLabel(evidence.reliabilityTier)}</p></div><a href={evidence.sourceUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm text-primary underline-offset-4 hover:underline">Открыть источник <ExternalLink className="h-3.5 w-3.5" /></a></div>
              <p className="mt-2 break-all text-xs text-muted-foreground">Снимок {evidence.snapshotSha256.slice(0, 16)}… · наблюдение {evidence.sourceObservationId}</p>
              <p className="mt-1 text-xs text-muted-foreground">Локатор: {[evidence.page ? `стр. ${evidence.page}` : null, evidence.table, evidence.row ? `строка ${evidence.row}` : null, evidence.section, evidence.field, evidence.recordKey].filter(Boolean).join(" · ") || "не указан"}{evidence.inferred ? " · inferred evidence" : ""}</p>
            </li>)}</ul>}
          </section>

          {policyTarget && <section className="rounded-lg border border-amber-500/50 bg-amber-50 p-4 text-amber-950" role="status">
            <h3 className="flex items-center gap-2 text-sm font-semibold"><ShieldAlert className="h-4 w-4" /> Гипотетическая проверка policy-кандидата</h3>
            <p className="mt-2 text-sm">Preview сравнивает текущий approved набор с этой exact pending revision и не меняет canonical состояние. Неизвестный ввод остаётся неизвестным.</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-sm"><span className="font-medium">University ID</span><input value={universityId} onChange={(event) => setUniversityId(event.target.value)} placeholder="university:bmstu" className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
              <label className="space-y-1 text-sm"><span className="font-medium">Приёмный год</span><input type="number" min={2000} max={2100} value={admissionYear} onChange={(event) => setAdmissionYear(event.target.value)} placeholder="2028" className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
              <label className="space-y-1 text-sm"><span className="font-medium">Проверять на дату</span><input type="datetime-local" value={validAsOf} onChange={(event) => setValidAsOf(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
              <label className="space-y-1 text-sm"><span className="font-medium">Direction ID (необязательно)</span><input value={directionId} onChange={(event) => setDirectionId(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
              <label className="space-y-1 text-sm"><span className="font-medium">Program ID (необязательно)</span><input value={programId} onChange={(event) => setProgramId(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
              <label className="space-y-1 text-sm"><span className="font-medium">Admission route (необязательно)</span><input value={admissionRoute} onChange={(event) => setAdmissionRoute(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
              <label className="space-y-1 text-sm"><span className="font-medium">Competition type (необязательно)</span><input value={competitionType} onChange={(event) => setCompetitionType(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
              <label className="space-y-1 text-sm"><span className="font-medium">Applicant category (необязательно)</span><input value={applicantCategory} onChange={(event) => setApplicantCategory(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
            </div>
            <Button type="button" className="mt-3" variant="outline" disabled={previewing || submitting || !universityId.trim() || !admissionYear || !validAsOf} onClick={submitPreview}>{previewing ? "Строим preview…" : "Построить current vs candidate preview"}</Button>
            {policyPreview && <div className="mt-4 space-y-4 rounded-lg border border-emerald-700/20 bg-background p-4 text-foreground">
              <div><p className="font-semibold">Preview готов · {policyPreview.approval_state}</p><p className="mt-1 break-all text-xs text-muted-foreground">{policyPreview.preview_id} · approved snapshot {policyPreview.approved_snapshot_hash}</p><p className="mt-1 text-sm">Текущая политика: {policyPreview.current_trace.status}; кандидат: {policyPreview.candidate_trace.status}; impact: {policyPreview.impact.status} / {policyPreview.impact.actionability}.</p></div>
              <section><h4 className="mb-2 text-sm font-semibold">Effective-policy diff</h4>{policyPreview.effective_diff.changes.length === 0 ? <p className="text-sm text-muted-foreground">Эффективный набор не изменился в выбранном контексте либо данных недостаточно; см. trace и uncertainties.</p> : <div className="overflow-x-auto rounded border"><table className="w-full min-w-[30rem] text-left text-sm"><thead className="bg-muted/50"><tr><th className="p-2">Поле</th><th className="p-2">Было</th><th className="p-2">Стало</th><th className="p-2">Изменение</th></tr></thead><tbody>{policyPreview.effective_diff.changes.map((change) => <tr key={change.path} className="border-t"><th className="break-words p-2">{change.path}</th><td className="break-words p-2">{change.before ?? "—"}</td><td className="break-words p-2">{change.after ?? "—"}</td><td className="p-2">{change.kind}</td></tr>)}</tbody></table></div>}</section>
              <section><h4 className="text-sm font-semibold">Impact и domain-owner results</h4><p className="mt-1 text-sm">Недостающие входы: {policyPreview.impact.missing_input_codes.length ? policyPreview.impact.missing_input_codes.join(", ") : "не указаны"}.</p><p className="mt-1 text-sm">Затронутые объекты: {policyPreview.impact.affected_objects.length ? policyPreview.impact.affected_objects.map((item) => `${item.node.kind}:${item.node.object_id}`).join(", ") : "не установлены"}.</p><details className="mt-2"><summary className="cursor-pointer text-sm font-medium">Показать typed domain results и evidence</summary><pre className="mt-2 max-h-80 overflow-auto rounded bg-muted p-3 text-xs">{JSON.stringify({ domainResults: policyPreview.impact.domain_results, evidence: policyPreview.impact.evidence, dependencyCycles: policyPreview.impact.dependency_cycles }, null, 2)}</pre></details></section>
              <div className="grid gap-3 md:grid-cols-2"><details><summary className="cursor-pointer text-sm font-medium">Current ResolutionTrace</summary><pre className="mt-2 max-h-80 overflow-auto rounded bg-muted p-3 text-xs">{JSON.stringify(policyPreview.current_trace, null, 2)}</pre></details><details><summary className="cursor-pointer text-sm font-medium">Candidate ResolutionTrace</summary><pre className="mt-2 max-h-80 overflow-auto rounded bg-muted p-3 text-xs">{JSON.stringify(policyPreview.candidate_trace, null, 2)}</pre></details></div>
              <section className="space-y-2 border-t pt-3"><label htmlFor="policy-review-reason" className="block text-sm font-medium">Причина решения</label><textarea id="policy-review-reason" value={reason} onChange={(event) => onReasonChange(event.target.value)} rows={3} maxLength={512} className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm" /><p className="text-xs text-muted-foreground">Решение будет привязано к fingerprint этого preview и записано в policy approval ledger.</p><div className="flex flex-wrap gap-2"><Button type="button" disabled={submitting || !reason.trim() || !policyPreview || !policyPreviewContext || !previewCanBeApproved || item.evidence.length === 0} onClick={() => onDecide("approve")}>Подтвердить эту policy revision</Button><Button type="button" variant="destructive" disabled={submitting || !reason.trim() || !policyPreview || !policyPreviewContext || item.evidence.length === 0} onClick={() => onDecide("reject")}>Отклонить эту policy revision</Button></div>{policyPreview && !previewCanBeApproved && <p className="text-sm text-amber-800" role="status">Approval закрыт: нужны resolved candidate trace, полный domain-owner impact и отсутствие unresolved conflicts. Reject остаётся доступен с этим preview.</p>}</section>
            </div>}
          </section>}

          {item.diff.length > 0 && <section><h3 className="mb-2 flex items-center gap-2 text-sm font-semibold"><GitCompareArrows className="h-4 w-4" /> Структурный diff</h3><div className="overflow-x-auto rounded-lg border"><table className="w-full min-w-[34rem] text-left text-sm"><thead className="bg-muted/50"><tr><th scope="col" className="p-2">Поле</th><th scope="col" className="p-2">Было</th><th scope="col" className="p-2">Стало</th><th scope="col" className="p-2">Тип</th></tr></thead><tbody>{item.diff.map((change) => <tr key={change.path} className="border-t"><th scope="row" className="max-w-60 break-words p-2 font-medium">{change.path}</th><td className="max-w-72 break-words p-2">{change.before ?? "—"}</td><td className="max-w-72 break-words p-2">{change.after ?? "—"}</td><td className="p-2">{change.kind}</td></tr>)}</tbody></table></div></section>}
          {policyTarget && item.diff.length === 0 && <p className="rounded-lg border p-3 text-sm text-muted-foreground">Сопоставимая предыдущая редакция или изменения полей не найдены; это не доказывает, что правило отсутствует.</p>}

          <section>
            <h3 className="mb-2 text-sm font-semibold">Конфликты</h3>
            {item.conflicts.length === 0 ? <p className="text-sm text-muted-foreground">Связанные conflict groups не найдены в доступном knowledge срезе.</p> : <ul className="space-y-3">{item.conflicts.map((conflict) => <li key={conflict.conflictId} className={`rounded-lg border p-3 ${conflict.state === "open" ? "border-destructive/40 bg-destructive/5" : ""}`}><p className="font-medium">{conflict.kind.replaceAll("_", " ")} · {conflict.state === "open" ? "не разрешён" : conflict.state === "resolved" ? "разрешён" : "закрыт без разрешения"}</p><p className="mt-1 text-xs text-muted-foreground">{conflict.scope ?? "Scope конфликта не установлен"} · {conflict.conflictId}</p><ul className="mt-2 space-y-2">{conflict.participants.map((participant) => <li key={`${participant.kind}:${participant.objectId}:${participant.revision}`} className="rounded bg-background p-2 text-xs"><p className="break-all font-medium">{participant.role}: {participant.objectId} · ревизия {participant.revision}</p>{participant.evidence.map((evidence) => <a key={`${evidence.sourceObservationId}:${evidence.sourceUrl}`} href={evidence.sourceUrl} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-primary underline-offset-4 hover:underline">{evidence.sourceName ?? evidence.sourceId} · evidence <ExternalLink className="h-3 w-3" /></a>)}</li>)}</ul></li>)}</ul>}
            {item.conflictsTruncated && <p className="mt-2 text-sm text-amber-800" role="status">Показана только часть конфликтов; подтверждение заблокировано до полной проверки.</p>}
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold">Журнал review действий</h3>
            {item.actionHistory.length === 0 ? <p className="text-sm text-muted-foreground">Действий по точной ревизии пока нет.</p> : <ol className="space-y-2">{item.actionHistory.map((action, index) => <li key={`${action.recordedAt}:${index}`} className="rounded-lg border p-3 text-sm"><p className="font-medium">{action.action.replaceAll("_", " ")} · {formatDateTime(action.recordedAt)}</p><p className="mt-1 text-muted-foreground">{action.actorAccountId} · {action.reason}</p><p className="mt-1 text-xs text-muted-foreground">Результат ревизия {action.resultRevision}, hash {action.resultHash.slice(0, 12)}…</p>{action.policyPreviewFingerprint && <p className="mt-1 break-all text-xs text-muted-foreground">Reviewer preview fingerprint: {action.policyPreviewFingerprint}</p>}</li>)}</ol>}
          </section>

          {!policyTarget && <section className="space-y-3 border-t pt-4">
            <h3 className="text-sm font-semibold">Решение по source assertion</h3>
            <label htmlFor="review-reason" className="block text-sm font-medium">Причина решения</label>
            <textarea id="review-reason" value={reason} onChange={(event) => onReasonChange(event.target.value)} rows={3} maxLength={512} required className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-describedby="review-reason-help" />
            <p id="review-reason-help" className="text-xs text-muted-foreground">Причина станет частью неизменяемого журнала. Утверждение подтверждает только содержание источника.</p>
            {duplicateCandidates.length > 0 && <div className="space-y-2"><label htmlFor="duplicate-target" className="block text-sm font-medium">Связать с точной записью для merge/duplicate</label><select id="duplicate-target" value={relatedTargetKey} onChange={(event) => onRelatedTargetChange(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"><option value="">Выберите другую запись</option>{duplicateCandidates.map((candidate) => <option key={itemKey(candidate)} value={itemKey(candidate)}>{candidate.target.objectId} · rev {candidate.target.revision}</option>)}</select></div>}
            <div className="flex flex-wrap gap-2">
              {REVIEW_ACTIONS.map(({ action, label, variant }) => <Button key={action} type="button" variant={variant} disabled={submitting || !reason.trim() || item.evidence.length === 0 || (action === "approve" && unresolvedConflict)} onClick={() => onDecide(action)}>{action === "approve" ? <Check /> : action === "reject" ? <X /> : null}{label}</Button>)}
              {duplicateCandidates.length > 0 && <>
                <Button type="button" variant="outline" disabled={submitting || !reason.trim() || !relatedTargetKey} onClick={() => onDecide("merge")}>Объединить как дубликат</Button>
                <Button type="button" variant="outline" disabled={submitting || !reason.trim() || !relatedTargetKey} onClick={() => onDecide("mark_duplicate")}>Отметить дубликатом</Button>
              </>}
            </div>
            {item.proposition && item.target.kind === "claim" && <div className="space-y-3 rounded-lg border p-4">
              <h4 className="text-sm font-semibold">Исправить типизированную классификацию</h4>
              <p className="text-xs text-muted-foreground">Исходный текст, evidence и временные данные неизменны. Изменение добавит новую pending revision; оно не подтверждает claim.</p>
              <label className="block space-y-1 text-sm"><span className="font-medium">Predicate</span><input value={editPredicate} onChange={(event) => setEditPredicate(event.target.value)} maxLength={96} className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
              {item.proposition.value.kind === "boolean" ? <label className="block space-y-1 text-sm"><span className="font-medium">Value</span><select value={editValue} onChange={(event) => setEditValue(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2"><option value="true">true</option><option value="false">false</option></select></label> : <label className="block space-y-1 text-sm"><span className="font-medium">Value ({item.proposition.value.kind})</span><input value={editValue} onChange={(event) => setEditValue(event.target.value)} className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>}
              <label className="block space-y-1 text-sm"><span className="font-medium">Unit (необязательно)</span><input value={editUnit} onChange={(event) => setEditUnit(event.target.value)} maxLength={64} className="w-full rounded-md border border-input bg-background px-3 py-2" /></label>
              <Button type="button" variant="outline" disabled={submitting || !reason.trim() || !editPredicate.trim() || item.evidence.length === 0} onClick={() => onDecide("edit", { editedProposition: updatedProposition(item.proposition!, editPredicate.trim(), editValue, editUnit) })}>Сохранить как новую review revision</Button>
              <h4 className="pt-2 text-sm font-semibold">Разрешить identity</h4>
              {identityResolutionSupported ? <><p className="text-xs text-muted-foreground">Canonical ID проверяется по существующему typed catalog owner. Свободный или отсутствующий ID не принимается.</p><label className="block space-y-1 text-sm"><span className="font-medium">Exact canonical subject ID</span><input value={identitySubjectId} onChange={(event) => setIdentitySubjectId(event.target.value)} maxLength={320} placeholder="direction:bmstu:09.03.01" className="w-full rounded-md border border-input bg-background px-3 py-2" /></label><Button type="button" variant="outline" disabled={submitting || !reason.trim() || !identitySubjectId.trim() || item.evidence.length === 0} onClick={() => onDecide("resolve_identity", { canonicalSubjectId: identitySubjectId.trim() })}>Проверить и разрешить identity</Button></> : <p className="text-xs text-muted-foreground">Для {item.proposition.subject_kind} canonical identity catalog пока не подключён; разрешение ID недоступно.</p>}
            </div>}
          </section>}
        </CardContent>
      </Card>
    </article>
  );
}
