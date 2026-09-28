"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Download, Layers, GraduationCap, Calculator, ChevronRight } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { explainSourceGap, PageHeader, Loading, ErrorState, EmptyState, Stat, ProvenanceChip, safeExternalHref, Tag, SectionTitle } from "@/components/shared";
import { getProgram, getCurriculum, getProgramAdmissions, calculateAdmissionFit } from "@/lib/api";
import {
  directionLabel,
  studyFormLabel,
  fundingLabel,
  competitionLabel,
  taxonomyLabel,
} from "@/lib/labels";
import { formatDecimal, formatInt, formatMoney, formatDate } from "@/lib/format";
import type {
  ProgramResponse,
  CurriculumResponse,
  ProgramAdmissionsResponse,
  AdmissionFitResponse,
  AdmissionOffering,
  SourceGapReference,
} from "@/lib/types";
import type { Route } from "@/lib/router";
import { ADMISSION_FIT_LABELS } from "@/lib/labels";
import { ProgramShortlistActions } from "@/features/decision/program-shortlist-actions";

export function ProgramPage({ id, navigate }: { id: string; navigate: (route: Route) => void }) {
  const [program, setProgram] = useState<ProgramResponse | null>(null);
  const [curriculum, setCurriculum] = useState<CurriculumResponse | null>(null);
  const [admissions, setAdmissions] = useState<ProgramAdmissionsResponse | null>(null);
  const [programLoading, setProgramLoading] = useState(true);
  const [curriculumLoading, setCurriculumLoading] = useState(true);
  const [admissionsLoading, setAdmissionsLoading] = useState(true);
  const [programError, setProgramError] = useState<string | null>(null);
  const [curriculumError, setCurriculumError] = useState<string | null>(null);
  const [admissionsError, setAdmissionsError] = useState<string | null>(null);
  const [programRetry, setProgramRetry] = useState(0);
  const [curriculumRetry, setCurriculumRetry] = useState(0);
  const [admissionsRetry, setAdmissionsRetry] = useState(0);

  useEffect(() => {
    let active = true;
    setProgram(null);
    setProgramError(null);
    setProgramLoading(true);
    void getProgram(id)
      .then((value) => active && setProgram(value))
      .catch(() => active && setProgramError("Не удалось загрузить карточку программы. Проверьте ID и доступность API."))
      .finally(() => active && setProgramLoading(false));
    return () => {
      active = false;
    };
  }, [id, programRetry]);

  useEffect(() => {
    let active = true;
    setCurriculum(null);
    setCurriculumError(null);
    setCurriculumLoading(true);
    void getCurriculum(id)
      .then((value) => active && setCurriculum(value))
      .catch(() => active && setCurriculumError("Учебный план временно недоступен. Остальные данные программы можно просмотреть отдельно."))
      .finally(() => active && setCurriculumLoading(false));
    return () => {
      active = false;
    };
  }, [id, curriculumRetry]);

  useEffect(() => {
    let active = true;
    setAdmissions(null);
    setAdmissionsError(null);
    setAdmissionsLoading(true);
    void getProgramAdmissions(id)
      .then((value) => active && setAdmissions(value))
      .catch(() => active && setAdmissionsError("Данные о поступлении временно недоступны. Учебный план можно просмотреть отдельно."))
      .finally(() => active && setAdmissionsLoading(false));
    return () => {
      active = false;
    };
  }, [id, admissionsRetry]);

  if (programLoading && !program) return <Loading label="Загружаем карточку программы…" />;
  if (!program)
    return <ErrorState title="Программа недоступна" message={programError ?? undefined} onRetry={() => setProgramRetry((value) => value + 1)} />;

  const p = program.program;
  const studyPlanHref = safeExternalHref(p.studyPlanUrl);
  return (
    <div data-testid="program-page">
      <button
        onClick={() => navigate({ view: "catalog" })}
        className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground transition hover:text-primary"
      >
        <ArrowLeft className="h-4 w-4" /> Назад в каталог
      </button>

      <PageHeader
        eyebrow={`${p.code} · ${directionLabel(p.directionId)}`}
        title={p.name}
        description={`Учебный год ${p.educationYear}. Направление ${p.directionId} — ${directionLabel(p.directionId)}. Данные получены из открытых источников ${p.universityName ?? "университета"}.`}
        actions={
          <>
            {studyPlanHref && (
              <Button variant="outline" size="sm" className="gap-1" asChild>
                <a href={studyPlanHref} target="_blank" rel="noopener noreferrer">
                  <Download className="h-4 w-4" /> План (PDF)
                </a>
              </Button>
            )}
            <Button
              size="sm"
              className="gap-1 bg-primary text-primary-foreground hover:bg-primary/90"
              onClick={() => navigate({ view: "compare" })}
            >
              <Layers className="h-4 w-4" /> Сравнить
            </Button>
            <ProgramShortlistActions programId={p.id} navigate={navigate} compact />
          </>
        }
      />

      <div className="mb-6 space-y-2" data-testid="program-source-evidence">
        <ProvenanceChip prov={p.provenance?.[0]} />
        <SourceGapList gaps={p.sourceGaps} />
      </div>

      {programLoading && <p className="mb-4 text-sm text-muted-foreground" role="status" aria-live="polite">Обновляем карточку программы…</p>}

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Дисциплин" value={curriculum ? formatInt(curriculum.items.length) : "—"} hint={curriculumError ? "учебный план недоступен" : undefined} />
        <Stat
          label="Часов всего"
          value={curriculum ? formatInt(curriculum.items.reduce((s, i) => s + i.hours, 0)) : "—"}
        />
        <Stat
          label="ЗЕТ всего"
          value={curriculum ? formatDecimal(curriculum.items.reduce((s, i) => s + Number(i.credits ?? 0), 0), 1) : "—"}
        />
        <Stat label="Семестров" value={curriculum ? formatInt(new Set(curriculum.items.map((i) => i.semester).filter(Boolean)).size) : "—"} />
      </div>

      <Tabs defaultValue="curriculum">
        <TabsList className="mb-4">
          <TabsTrigger value="curriculum">Учебный план</TabsTrigger>
          <TabsTrigger value="admissions">Поступление</TabsTrigger>
          <TabsTrigger value="admission-fit">Оценка готовности</TabsTrigger>
        </TabsList>

        <TabsContent value="curriculum">
          {curriculumLoading && !curriculum && <Loading label="Загружаем учебный план…" />}
          {curriculumError && <ErrorState title="Учебный план недоступен" message={curriculumError} onRetry={() => setCurriculumRetry((value) => value + 1)} />}
          {!curriculumLoading && !curriculumError && !curriculum && (
            <EmptyState title="Учебный план пока не опубликован" message="Карточка программы доступна, но официальный учебный план не найден в текущем срезе данных." />
          )}
          {curriculum && <CurriculumTab curriculum={curriculum} />}
        </TabsContent>
        <TabsContent value="admissions">
          {admissionsLoading && !admissions && <Loading label="Загружаем условия поступления…" />}
          {admissionsError && <ErrorState title="Условия поступления недоступны" message={admissionsError} onRetry={() => setAdmissionsRetry((value) => value + 1)} />}
          {!admissionsLoading && !admissionsError && !admissions && (
            <EmptyState title="Условия поступления пока не опубликованы" message="В текущем срезе нет подтверждённых официальных условий набора для этой программы." />
          )}
          {admissions && <AdmissionsTab admissions={admissions} />}
        </TabsContent>
        <TabsContent value="admission-fit">
          {admissionsLoading && !admissions && <Loading label="Загружаем данные для оценки…" />}
          {admissionsError && <ErrorState title="Оценка готовности недоступна" message={admissionsError} onRetry={() => setAdmissionsRetry((value) => value + 1)} />}
          {!admissionsLoading && !admissionsError && !admissions && (
            <EmptyState title="Недостаточно данных для оценки" message="Сначала должен быть опубликован официальный вариант набора с требованиями к поступлению." />
          )}
          {admissions && <AdmissionFitTab offerings={admissions.offerings} programId={p.id} />}
        </TabsContent>
      </Tabs>
    </div>
  );
}

function CurriculumTab({ curriculum }: { curriculum: CurriculumResponse }) {
  return (
    <Card data-testid="curriculum-table">
      <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
        <div>
          <h2 className="font-serif text-xl font-semibold">Учебный план {curriculum.educationYear}</h2>
          <p className="text-sm text-muted-foreground">
            План снят {formatDate(curriculum.capturedAt)} · {curriculum.items.length} дисциплин
          </p>
          <div className="mt-2 space-y-1">
            <ProvenanceChip prov={curriculum.provenance?.[0]} />
            <SourceGapList gaps={curriculum.sourceGaps} />
          </div>
        </div>
        {safeExternalHref(curriculum.sourceUrl) && (
          <Button variant="ghost" size="sm" asChild>
            <a href={safeExternalHref(curriculum.sourceUrl) ?? undefined} target="_blank" rel="noopener noreferrer">
              <Download className="h-4 w-4" /> План
            </a>
          </Button>
        )}
      </CardHeader>
      {curriculum.items.length === 0 ? (
        <CardContent>
          <EmptyState title="В учебном плане нет дисциплин" message="Источник ответил без строк учебного плана. Это не трактуется как нулевая нагрузка." />
        </CardContent>
      ) : (
        <CardContent>
          <div className="overflow-x-auto rounded-xl border border-border/70">
            <Table className="min-w-[640px]">
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead>Дисциплина</TableHead>
                <TableHead className="w-20">Сем.</TableHead>
                <TableHead className="w-24">Часы</TableHead>
                <TableHead className="w-20">ЗЕТ</TableHead>
                <TableHead className="hidden w-40 md:table-cell">Область</TableHead>
                <TableHead className="hidden w-32 md:table-cell">Форма</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {curriculum.items.map((item) => (
                <TableRow key={item.id}>
                  <TableCell className="font-medium text-foreground">{item.discipline.name}</TableCell>
                  <TableCell className="tabular-nums text-muted-foreground">{item.semester ?? "—"}</TableCell>
                  <TableCell className="tabular-nums">{formatInt(item.hours)}</TableCell>
                  <TableCell className="tabular-nums text-muted-foreground">{formatDecimal(item.credits, 1)}</TableCell>
                  <TableCell className="hidden md:table-cell">
                    <Tag tone="muted">{taxonomyLabel(item.discipline.primaryArea)}</Tag>
                  </TableCell>
                  <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
                    {item.assessmentTypes?.join(", ") ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
            </Table>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

function SourceGapList({ gaps }: { gaps?: SourceGapReference[] | null }) {
  if (!gaps || gaps.length === 0) return null;
  return (
    <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-3 py-2 text-sm text-amber-950" role="status" aria-live="polite">
      <p className="font-medium">Что нужно учитывать в данных</p>
      <ul className="mt-1 space-y-1">
        {gaps.map((gap, index) => (
          <li key={`${gap.code}-${index}`} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <Tag tone="muted">{gap.severity === "blocking" ? "блокирует вывод" : gap.severity === "degradable" ? "можно продолжить" : "справочная информация"}</Tag>
            <span>{gap.message || explainSourceGap(gap.code)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AdmissionsTab({ admissions }: { admissions: ProgramAdmissionsResponse }) {
  if (admissions.offerings.length === 0) {
    return (
      <div className="space-y-4" data-testid="admissions-section">
        <EmptyState title="Варианты набора не опубликованы" message="Карточка программы есть, но в текущем срезе нет подтверждённых вариантов набора." />
        <SourceGapList gaps={admissions.program.sourceGaps} />
      </div>
    );
  }
  return (
    <div className="space-y-4" data-testid="admissions-section">
      {admissions.offerings.map((o) => (
        <Card key={o.id}>
          <CardHeader className="pb-3">
            <div className="flex flex-wrap items-center gap-2">
              <Tag tone="primary">{o.admissionYear}</Tag>
              <Tag>{studyFormLabel(o.studyForm)}</Tag>
              <Tag>{fundingLabel(o.fundingType)}</Tag>
              <Tag tone="muted">{o.scope === "program" ? "Программа" : "Направление"}</Tag>
              {o.places != null && <Tag tone="muted">{formatInt(o.places)} мест</Tag>}
            </div>
          </CardHeader>
          <CardContent className="grid gap-5 md:grid-cols-2">
            <div>
              <SectionTitle>Вступительные испытания</SectionTitle>
              <div className="space-y-2">
                {o.exams.map((e, i) => (
                  <div key={i} className="flex items-center justify-between rounded-lg border border-border/60 bg-card px-3 py-2 text-sm">
                    <span className="font-medium">{e.subject}</span>
                    <span className="flex items-center gap-2 text-muted-foreground">
                      {e.isChoice && <Tag tone="muted">на выбор</Tag>}
                      <span className="tabular-nums">мин. {e.minimumScore ?? "—"}</span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
            <div className="space-y-4">
              {o.passingScores.length > 0 && (
                <div>
                  <SectionTitle>Проходные баллы</SectionTitle>
                  <div className="space-y-2">
                    {o.passingScores.map((ps, i) => (
                      <div key={i} className="flex items-center justify-between rounded-lg border border-border/60 bg-card px-3 py-2 text-sm">
                        <span>{competitionLabel(ps.competitionType)}</span>
                        <span className="tabular-nums font-semibold">
                          {ps.status === "bvi" ? "БВИ" : formatDecimal(ps.score, 0)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {o.quotas.length > 0 && (
                <div>
                  <SectionTitle>Квоты</SectionTitle>
                  <div className="flex flex-wrap gap-2">
                    {o.quotas.map((q, i) => (
                      <Tag key={i} tone="muted">
                        {competitionLabel(q.quotaType)}: {q.places ?? "—"}
                      </Tag>
                    ))}
                  </div>
                </div>
              )}
              {o.tuition.length > 0 && (
                <div>
                  <SectionTitle>Стоимость обучения</SectionTitle>
                  {o.tuition.map((t, i) => (
                    <div key={i} className="flex items-center justify-between rounded-lg border border-border/60 bg-card px-3 py-2 text-sm">
                      <span className="text-muted-foreground">{t.academicYear} · {studyFormLabel(t.studyForm)}</span>
                      <span className="font-semibold tabular-nums">{formatMoney(t.amount, t.currency)}/год</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      ))}
      <ProvenanceChip prov={admissions.offerings[0]?.provenance[0]} />
      <SourceGapList gaps={admissions.program.sourceGaps} />
    </div>
  );
}

function AdmissionFitTab({ offerings, programId }: { offerings: AdmissionOffering[]; programId: string }) {
  const [offeringId, setOfferingId] = useState(offerings[0]?.id ?? "");
  const [scores, setScores] = useState<{ subject: string; value: string }[]>([{ subject: "", value: "" }]);
  const [result, setResult] = useState<AdmissionFitResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const compute = async () => {
    setFormError(null);
    if (!offeringId) {
      setFormError("Для оценки выберите опубликованный вариант набора.");
      return;
    }
    const parsedScores: { subject: string; score: number }[] = [];
    const normalizedSubjects = new Set<string>();
    for (const score of scores) {
      const subject = score.subject.trim();
      const rawValue = score.value.trim();
      if (!subject && !rawValue) continue;
      if (!subject || !rawValue || !/^\d{1,3}$/.test(rawValue)) {
        setFormError("Для каждой заполненной строки укажите предмет и целое число от 0 до 100.");
        return;
      }
      const numericValue = Number(rawValue);
      if (numericValue < 0 || numericValue > 100) {
        setFormError("Баллы должны быть в диапазоне от 0 до 100.");
        return;
      }
      const normalizedSubject = subject.toLocaleLowerCase("ru-RU");
      if (normalizedSubjects.has(normalizedSubject)) {
        setFormError("Укажите каждый предмет только один раз.");
        return;
      }
      normalizedSubjects.add(normalizedSubject);
      parsedScores.push({ subject, score: numericValue });
    }
    if (parsedScores.length === 0) {
      setFormError("Добавьте хотя бы один фактический балл. Пустые значения не трактуются как нулевые.");
      return;
    }
    setLoading(true);
    try {
      const res = await calculateAdmissionFit(programId, {
        version: 1,
        offeringId,
        applicant: {
          version: 1,
          scores: parsedScores,
        },
      });
      setResult(res);
    } catch {
      setFormError("Не удалось рассчитать оценку по выбранному набору. Попробуйте ещё раз.");
    } finally {
      setLoading(false);
    }
  };

  const toneCls = result
    ? (ADMISSION_FIT_LABELS[result.status]?.tone ?? "muted") === "good"
      ? "text-emerald-700 bg-emerald-50 border-emerald-200"
      : (ADMISSION_FIT_LABELS[result.status]?.tone ?? "muted") === "warn"
        ? "text-amber-700 bg-amber-50 border-amber-200"
        : (ADMISSION_FIT_LABELS[result.status]?.tone ?? "muted") === "bad"
          ? "text-orange-700 bg-orange-50 border-orange-200"
          : "text-stone-600 bg-stone-50 border-stone-200"
    : "";

  return (
    <Card data-testid="admission-fit-panel">
      <CardHeader className="pb-3">
        <h2 className="flex items-center gap-2 font-serif text-xl font-semibold">
          <Calculator className="h-5 w-5 text-primary" /> Оценка готовности к поступлению
        </h2>
        <p className="text-sm text-muted-foreground">
          Отдельное от Content Fit измерение по введённым баллам, опубликованным минимальным требованиям и историческим ориентирам. Это не обещание результата и не гарантия зачисления.
        </p>
      </CardHeader>
      <CardContent className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Вариант набора</Label>
            {offerings.length > 0 ? <Select value={offeringId} onValueChange={setOfferingId}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {offerings.map((o) => (
                  <SelectItem key={o.id} value={o.id}>
                    {o.admissionYear} · {studyFormLabel(o.studyForm)} · {fundingLabel(o.fundingType)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select> : <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">У программы нет опубликованного варианта набора для оценки.</p>}
          </div>
          <div className="space-y-2">
            <Label>Ваши баллы</Label>
            {scores.map((s, i) => (
              <div key={i} className="flex gap-2">
                <Input
                  aria-label={`Предмет ${i + 1}`}
                  value={s.subject}
                  onChange={(e) => setScores((prev) => prev.map((x, j) => (j === i ? { ...x, subject: e.target.value } : x)))}
                  placeholder="Предмет"
                />
                <Input
                  aria-label={`Баллы по предмету ${i + 1}`}
                  type="number"
                  min={0}
                  max={100}
                  value={s.value}
                  onChange={(e) => setScores((prev) => prev.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
                  className="w-24"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  aria-label={`Удалить строку баллов ${i + 1}`}
                  onClick={() => setScores((prev) => prev.filter((_, j) => j !== i))}
                  className="text-muted-foreground"
                >
                  ✕
                </Button>
              </div>
            ))}
            <Button
              variant="outline"
              size="sm"
              onClick={() => setScores((prev) => [...prev, { subject: "", value: "" }])}
            >
              + Добавить предмет
            </Button>
          </div>
          {formError && <p className="text-sm text-destructive" role="alert">{formError}</p>}
          <Button onClick={compute} disabled={loading || offerings.length === 0} className="gap-2 bg-primary text-primary-foreground hover:bg-primary/90">
            {loading ? "Считаем…" : "Проверить готовность"} <ChevronRight className="h-4 w-4" />
          </Button>
        </div>

        <div>
          {result ? (
            <div className="space-y-4">
              <div className={`rounded-xl border p-4 ${toneCls}`}>
                <p className="text-sm font-medium">Итог</p>
                <p className="font-serif text-3xl font-bold tabular-nums">{ADMISSION_FIT_LABELS[result.status]?.label ?? "Статус не определён"}</p>
                <p className="text-sm opacity-80">Индекс готовности: {result.score}/100 · сумма введённых баллов {result.applicantTotalScore ?? "не указана"}</p>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Мин. готовность" value={metricLabel(result.breakdown.minimumReadiness)} />
                <Stat label="Проходная готовность" value={metricLabel(result.breakdown.passingReadiness)} />
                <Stat label="Полнота данных" value={metricLabel(result.breakdown.dataCompleteness)} />
              </div>
              {result.reasons.length > 0 && (
                <div>
                  <SectionTitle>Почему так</SectionTitle>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    {result.reasons.map((r, i) => <li key={i}>• {r}</li>)}
                  </ul>
                </div>
              )}
              {result.dataGaps.length > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                  {result.dataGaps.join(" ")}
                </div>
              )}
            </div>
          ) : (
            <div className="flex h-full flex-col items-center justify-center rounded-xl border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground">
              <GraduationCap className="mb-2 h-8 w-8 text-primary/50" />
              Выберите вариант набора, введите баллы ЕГЭ и нажмите «Рассчитать».
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function metricLabel(value: { value: number | null; status: string }): string {
  if (value.value !== null) return `${value.value}/100`;
  return value.status === "not_available" ? "данных недостаточно" : "частичные данные";
}
