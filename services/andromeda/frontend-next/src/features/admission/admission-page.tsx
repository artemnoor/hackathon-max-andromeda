"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowRight, CircleAlert, GraduationCap, Plus, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { explainSourceGap, ErrorState, Loading, PageHeader, SectionTitle, Stat, Tag } from "@/components/shared";
import { useDecisionContext } from "@/features/decision/decision-context";
import type { Route } from "@/lib/router";
import type { DecisionConstraintsRequest, DecisionSuggestion } from "@/lib/types";
import { trackDecisionEvent } from "@/lib/analytics";

type ScoreRow = { subject: string; score: string };

export function AdmissionPage({ navigate }: { navigate: (route: Route) => void }) {
  const {
    context,
    suggestions,
    isLoading,
    isSuggestionsLoading,
    isMutating,
    mutationError,
    updateConstraints,
    refreshSuggestions,
    addShortlist,
  } = useDecisionContext();
  const [scores, setScores] = useState<ScoreRow[]>([
    { subject: "Математика", score: "" },
    { subject: "Русский язык", score: "" },
    { subject: "Информатика и ИКТ", score: "" },
  ]);
  const [admissionYear, setAdmissionYear] = useState("");
  const [funding, setFunding] = useState("all");
  const [studyForm, setStudyForm] = useState("all");
  const [maxTuition, setMaxTuition] = useState("");
  const [location, setLocation] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [pendingProgram, setPendingProgram] = useState<string | null>(null);

  useEffect(() => {
    if (isSuggestionsLoading || !suggestions || (!submitted && !context?.state.admissionConstraints)) return;
    const count = suggestions.primaryCandidates.length
      + suggestions.alternativeCandidates.length
      + suggestions.ineligibleCandidates.length
      + suggestions.insufficientDataCandidates.length;
    trackDecisionEvent(
      "admission_fit_viewed",
      { source: "admission", action: "view", status: count > 0 ? "available" : "unknown", count },
      { dedupeKey: `admission-fit-viewed:${context?.state.revision ?? "unknown"}` },
    );
  }, [context, isSuggestionsLoading, submitted, suggestions]);

  const outcomes = useMemo(() => ({
    primary: suggestions?.primaryCandidates ?? [],
    alternative: suggestions?.alternativeCandidates ?? [],
    ineligible: suggestions?.ineligibleCandidates ?? [],
    insufficient: suggestions?.insufficientDataCandidates ?? [],
  }), [suggestions]);

  const saveProgram = async (programId: string, role: "primary" | "alternative") => {
    setPendingProgram(programId);
    try {
      await addShortlist(programId, role);
      await refreshSuggestions();
    } catch {
      // Provider retains the explicit context and exposes a safe message.
    } finally {
      setPendingProgram(null);
    }
  };

  const submit = async () => {
    setFormError(null);
    const parsedScores: { subject: string; score: number }[] = [];
    const normalizedSubjects = new Set<string>();
    for (const row of scores) {
      const subject = row.subject.trim();
      const rawScore = row.score.trim();
      if (!subject && !rawScore) continue;
      if (!subject || !rawScore || !/^\d{1,3}$/.test(rawScore)) {
        setFormError("Для каждой заполненной строки укажите предмет и целое число от 0 до 100.");
        return;
      }
      const score = Number(rawScore);
      if (score < 0 || score > 100) {
        setFormError("Баллы ЕГЭ должны быть в диапазоне от 0 до 100.");
        return;
      }
      const normalizedSubject = subject.toLocaleLowerCase("ru-RU");
      if (normalizedSubjects.has(normalizedSubject)) {
        setFormError("Укажите каждый предмет только один раз.");
        return;
      }
      normalizedSubjects.add(normalizedSubject);
      parsedScores.push({ subject, score });
    }
    const year = admissionYear.trim() ? Number(admissionYear) : null;
    if (year !== null && (!Number.isInteger(year) || year < 2000 || year > 2100)) {
      setFormError("Укажите корректный год поступления.");
      return;
    }
    const tuition = maxTuition.trim() ? Number(maxTuition) : null;
    if (tuition !== null && (!Number.isFinite(tuition) || tuition < 0)) {
      setFormError("Максимальная стоимость должна быть неотрицательным числом.");
      return;
    }
    const constraints: DecisionConstraintsRequest = {
      version: 1,
      applicant: parsedScores.length > 0 ? { version: 1, scores: parsedScores } : null,
      admissionYear: year,
      fundingPreference: funding === "all" ? null : funding as "budget" | "paid" | "targeted" | "unknown",
      studyForm: studyForm === "all" ? null : studyForm as "full_time" | "part_time" | "evening" | "online" | "unknown",
      maxTuition: tuition,
      location: location.trim() || null,
    };
    try {
      await updateConstraints(constraints);
      setSubmitted(true);
      await refreshSuggestions();
    } catch {
      // Provider retains form/context and exposes a safe error message.
    }
  };

  if (isLoading && !context) return <Loading label="Загружаем условия поступления…" />;
  return (
    <div data-testid="admission-page" className="space-y-6">
      <PageHeader
        eyebrow="Проверить поступление"
        title="Куда я могу поступить"
        description="Сохраните известные факты о себе, затем получите batch-оценку по кандидатам. Исторический проходной балл — ориентир, а не гарантия поступления."
      />

      <Card>
        <CardHeader className="pb-3"><SectionTitle>Ваши условия</SectionTitle><p className="text-sm text-muted-foreground">Заполняйте только то, что уже знаете. Пустые поля останутся неизвестными, а не превратятся в нули.</p></CardHeader>
        <CardContent className="space-y-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2"><Label htmlFor="admission-year">Год поступления</Label><Input id="admission-year" type="number" min={2000} max={2100} value={admissionYear} onChange={(event) => setAdmissionYear(event.target.value)} /></div>
            <div className="space-y-2"><Label>Форма обучения</Label><Select value={studyForm} onValueChange={setStudyForm}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Любая форма</SelectItem><SelectItem value="full_time">Очная</SelectItem><SelectItem value="part_time">Заочная</SelectItem><SelectItem value="evening">Очно-заочная</SelectItem><SelectItem value="online">Онлайн</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label>Финансирование</Label><Select value={funding} onValueChange={setFunding}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">Любое</SelectItem><SelectItem value="budget">Бюджет</SelectItem><SelectItem value="paid">Платное</SelectItem><SelectItem value="targeted">Целевое</SelectItem></SelectContent></Select></div>
            <div className="space-y-2"><Label htmlFor="max-tuition">Максимальная стоимость в год, ₽ <span className="font-normal text-muted-foreground">(необязательно)</span></Label><Input id="max-tuition" type="number" min={0} value={maxTuition} onChange={(event) => setMaxTuition(event.target.value)} placeholder="Не указывать" /></div>
          </div>
          <div className="space-y-2"><Label htmlFor="location">Город или ограничение по месту <span className="font-normal text-muted-foreground">(необязательно)</span></Label><Input id="location" value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Например, Москва" /></div>
          <div className="space-y-2">
            <div className="flex items-center justify-between"><Label>Баллы ЕГЭ</Label><span className="text-xs text-muted-foreground">можно оставить пустым</span></div>
            {scores.map((row, index) => <div key={index} className="flex gap-2"><Input aria-label={`Предмет ${index + 1}`} value={row.subject} onChange={(event) => setScores((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, subject: event.target.value } : item))} placeholder="Предмет" /><Input aria-label="0–100" type="number" min={0} max={100} value={row.score} onChange={(event) => setScores((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, score: event.target.value } : item))} placeholder="0–100" className="w-28" /><Button type="button" variant="ghost" size="icon" onClick={() => setScores((current) => current.filter((_, itemIndex) => itemIndex !== index))} aria-label="Удалить предмет"><Trash2 className="h-4 w-4" /></Button></div>)}
            <Button type="button" size="sm" variant="outline" onClick={() => setScores((current) => [...current, { subject: "", score: "" }])} className="gap-1"><Plus className="h-4 w-4" /> Добавить предмет</Button>
          </div>
          {formError && <p className="flex items-center gap-2 text-sm text-destructive" role="alert"><CircleAlert className="h-4 w-4" />{formError}</p>}
          {mutationError && <p className="flex items-center gap-2 rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-950" role="status" aria-live="polite"><CircleAlert className="h-4 w-4" />{mutationError}</p>}
          <Button type="button" onClick={() => void submit()} disabled={isMutating} className="gap-2"><GraduationCap className="h-4 w-4" />{isMutating ? "Сохраняем условия…" : "Проверить варианты"}<ArrowRight className="h-4 w-4" /></Button>
        </CardContent>
      </Card>

      {submitted && suggestions && (
        <AdmissionOutcomes suggestions={outcomes} missingData={suggestions.missingData} isLoading={isSuggestionsLoading} navigate={navigate} pendingProgram={pendingProgram} onSave={saveProgram} />
      )}
      {!submitted && context?.state.admissionConstraints && suggestions && <AdmissionOutcomes suggestions={outcomes} missingData={suggestions.missingData} isLoading={isSuggestionsLoading} navigate={navigate} pendingProgram={pendingProgram} onSave={saveProgram} />}
    </div>
  );
}

function AdmissionOutcomes({ suggestions, missingData, isLoading, navigate, pendingProgram, onSave }: { suggestions: { primary: DecisionSuggestion[]; alternative: DecisionSuggestion[]; ineligible: DecisionSuggestion[]; insufficient: DecisionSuggestion[] }; missingData: string[]; isLoading: boolean; navigate: (route: Route) => void; pendingProgram: string | null; onSave: (programId: string, role: "primary" | "alternative") => Promise<void> }) {
  if (isLoading) return <Loading label="Считаем варианты поступления…" />;
  const sections = [
    { key: "primary", title: "Реалистичные варианты", items: suggestions.primary, tone: "good" },
    { key: "alternative", title: "Пограничные варианты", items: suggestions.alternative, tone: "warn" },
    { key: "ineligible", title: "Малореалистичные варианты", items: suggestions.ineligible, tone: "bad" },
    { key: "insufficient", title: "Недостаточно данных", items: suggestions.insufficient, tone: "unknown" },
  ] as const;
  return (
    <div className="space-y-4" data-testid="admission-outcomes">
      <div className="rounded-xl border border-amber-300/60 bg-amber-50 p-4 text-sm text-amber-950"><p className="font-medium">Важно про результат</p><p className="mt-1">Это оценка риска по доступным источникам и историческим ориентирам. Она не гарантирует поступление и не заменяет правила приёмной кампании.</p></div>
      {missingData.length > 0 && <div className="rounded-xl border border-border/70 bg-card p-4 text-sm"><p className="font-medium">Что ещё не удалось проверить</p><ul className="mt-2 list-disc space-y-1 pl-5 text-muted-foreground">{missingData.slice(0, 8).map((item) => <li key={item}>{item}</li>)}</ul></div>}
      {sections.map((section) => <OutcomeSection key={section.key} title={section.title} items={section.items} tone={section.tone} navigate={navigate} pendingProgram={pendingProgram} onSave={onSave} />)}
    </div>
  );
}

function OutcomeSection({ title, items, tone, navigate, pendingProgram, onSave }: { title: string; items: DecisionSuggestion[]; tone: "good" | "warn" | "bad" | "unknown"; navigate: (route: Route) => void; pendingProgram: string | null; onSave: (programId: string, role: "primary" | "alternative") => Promise<void> }) {
  const colors = { good: "border-emerald-200 bg-emerald-50/60", warn: "border-amber-200 bg-amber-50/60", bad: "border-orange-200 bg-orange-50/60", unknown: "border-border/70 bg-card" };
  return (
    <Card className={colors[tone]}>
      <CardHeader className="pb-3"><SectionTitle hint={`${items.length}`}>{title}</SectionTitle></CardHeader>
      <CardContent className="space-y-3">
        {items.length === 0 && <p className="text-sm text-muted-foreground">В этой группе пока нет программ.</p>}
        {items.map((item) => <div key={item.programId} className="rounded-xl border border-border/70 bg-background/80 p-4"><div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between"><div className="min-w-0"><p className="font-mono text-xs text-primary">{item.programCode}</p><button type="button" className="mt-1 text-left font-serif text-lg font-semibold hover:text-primary" onClick={() => navigate({ view: "program", id: item.programId })}>{item.programName}</button><div className="mt-2 flex flex-wrap gap-1.5"><Tag tone="muted">Риск: {item.admissionRisk}</Tag>{item.admissionStatus && <Tag tone="muted">Статус: {item.admissionStatus}</Tag>}</div>{item.sourceGaps.length > 0 && <p className="mt-2 text-xs text-muted-foreground">{item.sourceGaps.map(explainSourceGap).join(" ")}</p>}</div><div className="text-right text-xs text-muted-foreground">{item.admissionFit ? `оценка ${item.admissionFit.score}/100` : "оценка неизвестна"}</div></div><p className="mt-3 text-sm text-muted-foreground">{item.reasons.admissionRisk.join("; ") || "Причины и источник риска не указаны."}</p><ConstraintOutcomeList outcomes={item.constraintOutcomes} /><div className="mt-3 flex flex-wrap gap-2"><Button type="button" size="sm" onClick={() => void onSave(item.programId, "primary")} disabled={pendingProgram !== null}>Добавить в основные</Button><Button type="button" size="sm" variant="outline" onClick={() => void onSave(item.programId, "alternative")} disabled={pendingProgram !== null}>Оставить альтернативой</Button><Button type="button" size="sm" variant="ghost" onClick={() => navigate({ view: "program", id: item.programId })}>Посмотреть почему</Button><Button type="button" size="sm" variant="ghost" onClick={() => navigate({ view: "compare" })}>Сравнить</Button></div></div>)}
      </CardContent>
    </Card>
  );
}

function ConstraintOutcomeList({ outcomes }: { outcomes: DecisionSuggestion["constraintOutcomes"] }) {
  if (outcomes.length === 0) return null;
  return <div className="mt-3 rounded-lg border border-border/60 bg-card/70 p-3 text-xs"><p className="font-medium">Проверка ваших условий</p><ul className="mt-1 space-y-1 text-muted-foreground">{outcomes.map((outcome) => <li key={outcome.dimension} className={outcome.satisfied === false ? "text-orange-800" : outcome.applicability === "insufficient_data" ? "text-amber-800" : undefined}>{constraintLabel(outcome.dimension)}: {outcome.message}</li>)}</ul></div>;
}

function constraintLabel(dimension: string): string {
  return { applicant_scores: "Баллы", admission_year: "Год", funding: "Финансирование", study_form: "Форма", max_tuition: "Стоимость", location: "Место" }[dimension] ?? dimension;
}
