"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeftRight, GitCompare, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader, Loading, ErrorState, Stat, SectionTitle, Tag } from "@/components/shared";
import { comparePrograms, getComparisonSummary } from "@/lib/api";
import { directionLabel } from "@/lib/labels";
import { formatDecimal, formatInt, formatShare } from "@/lib/format";
import type { AreaBreakdownItem, ComparisonResponse, ComparisonSummaryResponse, ProgramSummary } from "@/lib/types";
import type { Route } from "@/lib/router";
import { useDecisionContext } from "@/features/decision/decision-context";
import { ProgramShortlistActions } from "@/features/decision/program-shortlist-actions";
import { CompareSummary } from "./compare-summary";
import { trackDecisionEvent } from "@/lib/analytics";
import { areaColor } from "@/lib/area-colors";

export function ComparePage({
  programs,
  navigate,
}: {
  programs: ProgramSummary[];
  navigate: (route: Route) => void;
}) {
  const { activeShortlist } = useDecisionContext();
  const [aId, setAId] = useState(programs[0]?.id ?? "");
  const [bId, setBId] = useState(programs[1]?.id ?? "");
  const [cId, setCId] = useState("");
  const [scope, setScope] = useState<"all" | "semester">("all");
  const [semester, setSemester] = useState(3);
  const [data, setData] = useState<ComparisonResponse | null>(null);
  const [summary, setSummary] = useState<ComparisonSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const shortlistSeededRef = useRef(false);

  useEffect(() => {
    if (!shortlistSeededRef.current && activeShortlist.length >= 2) {
      const shortlistIds = activeShortlist
        .map((entry) => entry.programId)
        .filter((programId) => programs.some((program) => program.id === programId));
      if (shortlistIds.length >= 2) {
        setAId(shortlistIds[0]);
        setBId(shortlistIds[1]);
        shortlistSeededRef.current = true;
      }
    }
    if (programs.length && !aId) setAId(programs[0].id);
    if (programs.length > 1 && !bId) setBId(programs[1].id);
  }, [activeShortlist, programs, aId, bId]);

  const run = async (a: string, b: string, sc: "all" | "semester", sem: number) => {
    if (!a || !b || a === b) return;
    setLoading(true);
    setError(null);
    try {
      const res = await comparePrograms([a, b], { scope: sc, semester: sc === "semester" ? sem : undefined });
      setData(res);
      trackDecisionEvent(
        "comparison_completed",
        { source: "compare", action: "complete", programIds: [a, b] },
        { dedupeKey: comparisonEventKey("completed", [a, b], sc, sem) },
      );
    } catch {
      setError("Не удалось загрузить сравнение.");
    } finally {
      setLoading(false);
    }
  };

  const runSummary = async (ids: string[], sc: "all" | "semester", sem: number) => {
    if (ids.length < 2 || new Set(ids).size !== ids.length) return;
    trackDecisionEvent(
      "comparison_started",
      { source: "compare", action: "start", programIds: ids },
      { dedupeKey: comparisonEventKey("started", ids, sc, sem) },
    );
    setSummaryLoading(true);
    setSummaryError(null);
    try {
      setSummary(await getComparisonSummary(ids, { scope: sc, semester: sc === "semester" ? sem : undefined }));
      trackDecisionEvent(
        "comparison_completed",
        { source: "compare", action: "complete", programIds: ids },
        { dedupeKey: comparisonEventKey("completed", ids, sc, sem) },
      );
    } catch {
      setSummaryError("Не удалось загрузить краткое сравнение. Детальные данные можно открыть отдельно.");
    } finally {
      setSummaryLoading(false);
    }
  };

  useEffect(() => {
    void run(aId, bId, scope, semester);
  }, [aId, bId, scope, semester]);

  useEffect(() => {
    void runSummary([aId, bId, ...(cId ? [cId] : [])], scope, semester);
  }, [aId, bId, cId, scope, semester]);

  return (
    <div data-testid="compare-page">
      <PageHeader
        eyebrow="Сравнение"
        title="Сравнение программ"
        description="Выберите две программы и сопоставьте учебные планы: дисциплины, нагрузку в часах и кредитах. Переключайтесь между полным планом и отдельным семестром."
        actions={activeShortlist.length >= 2 ? (
          <Button type="button" variant="outline" size="sm" data-testid="compare-to-decision" onClick={() => navigate({ view: "decision" })}>
            К моему выбору
          </Button>
        ) : undefined}
      />

      <Card className="mb-6">
        <CardContent className="flex min-w-0 flex-col gap-4 p-4 lg:flex-row lg:items-end">
          <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2 lg:grid-cols-[1fr_auto_1fr]">
            <ProgramSelect label="Программа A" value={aId} onChange={setAId} programs={programs} exclude={bId} testId="program-a" />
            <div className="hidden items-center justify-center lg:flex">
              <ArrowLeftRight className="h-5 w-5 text-muted-foreground" />
            </div>
            <ProgramSelect label="Программа B" value={bId} onChange={setBId} programs={programs} exclude={aId} testId="program-b" />
          </div>
          <div className="flex min-w-0 flex-wrap items-end gap-3">
            {cId && <ProgramSelect label="Программа C" value={cId} onChange={setCId} programs={programs} exclude={[aId, bId]} testId="program-c" />}
            <Button type="button" size="sm" variant="outline" onClick={() => {
              if (cId) {
                setCId("");
                return;
              }
              const next = programs.find((program) => program.id !== aId && program.id !== bId);
              if (next) setCId(next.id);
            }} disabled={!cId && !programs.some((program) => program.id !== aId && program.id !== bId)}>
              {cId ? "Убрать третью" : "Добавить 3-ю программу"}
            </Button>
            <div>
              <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Режим</p>
              <Tabs value={scope} onValueChange={(v) => setScope(v as "all" | "semester")}>
                <TabsList>
                  <TabsTrigger value="all" data-testid="comparison-scope-all">Весь план</TabsTrigger>
                  <TabsTrigger value="semester" data-testid="comparison-scope-semester">Семестр</TabsTrigger>
                </TabsList>
              </Tabs>
            </div>
            {scope === "semester" && (
              <div>
                <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">Семестр</p>
                <Select value={String(semester)} onValueChange={(v) => setSemester(Number(v))}>
                <SelectTrigger className="w-24" data-testid="comparison-semester"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {[1, 2, 3, 4, 5, 6, 7, 8].map((s) => (
                      <SelectItem key={s} value={String(s)}>{s}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {activeShortlist.length >= 2 && (
        <Card className="mb-6 border-primary/20 bg-primary/5">
          <CardContent className="p-4">
            <p className="mb-2 text-sm font-medium">Выбрать из моего shortlist</p>
            <div className="grid gap-3 md:grid-cols-2">
              <div>
                <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Программа A</p>
                <div className="flex flex-wrap gap-2">
                  {activeShortlist.filter((entry) => entry.programId !== bId).map((entry) => (
                    <Button key={entry.programId} type="button" size="sm" variant={entry.programId === aId ? "default" : "outline"} onClick={() => setAId(entry.programId)}>
                      {entry.programId}
                    </Button>
                  ))}
                </div>
              </div>
              <div>
                <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Программа B</p>
                <div className="flex flex-wrap gap-2">
                  {activeShortlist.filter((entry) => entry.programId !== aId).map((entry) => (
                    <Button key={entry.programId} type="button" size="sm" variant={entry.programId === bId ? "default" : "outline"} onClick={() => setBId(entry.programId)}>
                      {entry.programId}
                    </Button>
                  ))}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {summaryLoading && !summary && <Loading label="Формируем краткое сравнение…" />}
      {summaryLoading && summary && <p className="mb-3 text-sm text-muted-foreground" role="status" aria-live="polite">Обновляем краткое сравнение…</p>}
      {summaryError && <ErrorState title="Краткое сравнение недоступно" message={summaryError} onRetry={() => void runSummary([aId, bId, ...(cId ? [cId] : [])], scope, semester)} />}
      {summary && <CompareSummary data={summary} navigate={navigate} />}
      {loading && !data && <Loading label="Загружаем доказательства из учебных планов…" />}
      {loading && data && <p className="mb-3 text-sm text-muted-foreground" role="status" aria-live="polite">Обновляем доказательства из учебных планов…</p>}
      {error && <ErrorState title="Детальное сравнение недоступно" message={error} onRetry={() => void run(aId, bId, scope, semester)} />}
      {data && (
        <section aria-labelledby="comparison-evidence-title" className="space-y-4">
          <div>
            <h2 id="comparison-evidence-title" className="font-serif text-2xl font-semibold">Детальные данные</h2>
            <p className="text-sm text-muted-foreground">Учебные часы, ЗЕТ, категории, дисциплины и источники — evidence к краткому выводу выше.</p>
          </div>
          <CompareResult data={data} navigate={navigate} />
        </section>
      )}
    </div>
  );
}

function comparisonEventKey(kind: "started" | "completed", programIds: readonly string[], scope: "all" | "semester", semester: number): string {
  return `comparison-${kind}:${programIds.map((id) => id.replaceAll(":", "-")).join("-")}-${scope}-${semester}`;
}

function ProgramSelect({
  label,
  value,
  onChange,
  programs,
  exclude,
  testId,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  programs: ProgramSummary[];
  exclude: string | readonly string[];
  testId: string;
}) {
  const excluded = new Set(typeof exclude === "string" ? [exclude] : exclude);
  return (
    <div className="min-w-0">
      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="w-full min-w-0" data-testid={testId}><SelectValue className="min-w-0" /></SelectTrigger>
        <SelectContent>
          {programs.filter((p) => !excluded.has(p.id)).map((p) => (
            <SelectItem key={p.id} value={p.id}>
              {p.code} · {p.name.split("·")[0].trim()}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function CompareResult({ data, navigate }: { data: ComparisonResponse; navigate: (route: Route) => void }) {
  const a = data.programA;
  const b = data.programB;
  return (
    <div className="space-y-6">
      <div className="grid gap-3 md:grid-cols-2">
        <ProgramHeader program={a} tone="A" navigate={navigate} />
        <ProgramHeader program={b} tone="B" navigate={navigate} />
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Часы A" value={formatInt(data.totalsA.totalHours)} />
        <Stat label="Часы B" value={formatInt(data.totalsB.totalHours)} />
        <Stat label="ЗЕТ A" value={formatDecimal(data.totalsA.totalCredits, 1)} />
        <Stat label="ЗЕТ B" value={formatDecimal(data.totalsB.totalCredits, 1)} />
      </div>

      <AreaComparisonChart data={data} />

      <Card>
        <CardHeader className="pb-3">
          <SectionTitle hint={`${data.rows.length} строк`}>Дисциплины</SectionTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-[28rem] overflow-auto warm-scroll rounded-xl border border-border/70" data-testid="comparison-table">
            <Table className="min-w-[640px]">
              <TableHeader className="sticky top-0">
                <TableRow className="bg-muted/70">
                  <TableHead>Дисциплина</TableHead>
                  <TableHead className="w-16">Сем.</TableHead>
                  <TableHead className="text-right">Часы A</TableHead>
                  <TableHead className="text-right">Часы B</TableHead>
                  <TableHead className="text-right">Δ</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.rows.map((row, i) => (
                  <TableRow key={i}>
                    <TableCell className="font-medium">
                      {row.discipline}
                      {!row.presentA && <Tag tone="muted">только B</Tag>}
                      {!row.presentB && <Tag tone="muted">только A</Tag>}
                    </TableCell>
                    <TableCell className="tabular-nums text-muted-foreground">{row.semester ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.hoursA ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.hoursB ?? "—"}</TableCell>
                    <TableCell className={`text-right tabular-nums ${(row.deltaHours ?? 0) > 0 ? "text-emerald-600" : (row.deltaHours ?? 0) < 0 ? "text-orange-600" : "text-muted-foreground"}`}>
                      {row.deltaHours == null ? "—" : `${row.deltaHours > 0 ? "+" : ""}${row.deltaHours}`}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

type AreaComparisonRow = {
  code: string;
  name: string;
  shareA: number;
  shareB: number;
  color: string;
};

function areaShare(value: string | number | null | undefined): number {
  const parsed = typeof value === "number" ? value : Number(value ?? 0);
  return Number.isFinite(parsed) ? Math.max(0, Math.min(1, parsed)) : 0;
}

function mergeAreaBreakdowns(
  areaBreakdownA: AreaBreakdownItem[] | null | undefined,
  areaBreakdownB: AreaBreakdownItem[] | null | undefined,
): AreaComparisonRow[] {
  const merged = new Map<string, AreaComparisonRow>();

  for (const item of areaBreakdownA ?? []) {
    const current = merged.get(item.code) ?? { code: item.code, name: item.name, shareA: 0, shareB: 0, color: areaColor(item.code) };
    merged.set(item.code, { ...current, name: current.name || item.name, shareA: areaShare(item.share) });
  }
  for (const item of areaBreakdownB ?? []) {
    const current = merged.get(item.code) ?? { code: item.code, name: item.name, shareA: 0, shareB: 0, color: areaColor(item.code) };
    merged.set(item.code, { ...current, name: current.name || item.name, shareB: areaShare(item.share) });
  }

  return [...merged.values()]
    .sort((left, right) => {
      const totalDelta = right.shareA + right.shareB - left.shareA - left.shareB;
      return totalDelta || left.name.localeCompare(right.name, "ru");
    })
    .map((row) => ({ ...row, color: areaColor(row.code) }));
}

function AreaComparisonChart({ data }: { data: ComparisonResponse }) {
  const rows = mergeAreaBreakdowns(data.areaBreakdownA, data.areaBreakdownB);

  return (
    <Card data-testid="comparison-area-chart">
      <CardHeader className="pb-3">
        <SectionTitle hint={rows.length ? `${rows.length} категорий` : "нет данных"}>
          Содержание по категориям
        </SectionTitle>
        <p className="max-w-3xl text-sm text-muted-foreground">
          Доля учебной нагрузки, распределённая по 22 областям taxonomy. Один и тот же цвет обозначает одну и ту же категорию в обеих программах.
        </p>
      </CardHeader>
      <CardContent>
        {rows.length === 0 ? (
          <p className="rounded-xl border border-dashed border-border/70 p-5 text-sm text-muted-foreground">
            Для выбранного среза нет распределения по категориям.
          </p>
        ) : (
          <div className="grid gap-4 md:grid-cols-2" data-testid="area-breakdown" aria-label="Сравнение категорий дисциплин">
            <AreaPieCard label="A" programCode={data.programA.code} rows={rows} shareKey="shareA" />
            <AreaPieCard label="B" programCode={data.programB.code} rows={rows} shareKey="shareB" />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function pieGradient(rows: readonly AreaComparisonRow[], shareKey: "shareA" | "shareB"): string {
  const total = rows.reduce((sum, row) => sum + row[shareKey], 0);
  if (total <= 0) return "conic-gradient(#e7e5e4 0 100%)";

  let cursor = 0;
  const segments = rows.flatMap((row) => {
    const value = row[shareKey];
    if (value <= 0) return [];
    const start = (cursor / total) * 100;
    cursor += value;
    const end = (cursor / total) * 100;
    return [`${row.color} ${start.toFixed(4)}% ${end.toFixed(4)}%`];
  });
  return `conic-gradient(${segments.join(", ")})`;
}

function AreaPieCard({
  label,
  programCode,
  rows,
  shareKey,
}: {
  label: "A" | "B";
  programCode: string;
  rows: readonly AreaComparisonRow[];
  shareKey: "shareA" | "shareB";
}) {
  const total = rows.reduce((sum, row) => sum + row[shareKey], 0);

  return (
    <article className="rounded-xl border border-border/60 bg-background/40 p-4" data-testid={`area-pie-${label.toLowerCase()}`}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-primary">Программа {label}</p>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{programCode}</p>
        </div>
        <span className="rounded-full bg-accent px-2 py-1 text-[10px] font-medium text-accent-foreground">по часам</span>
      </div>
      <div className="flex flex-col items-center gap-5">
        <div
          className="relative grid aspect-square w-[min(17rem,72vw)] place-items-center rounded-full p-2 shadow-sm ring-1 ring-border/70"
          style={{ background: pieGradient(rows, shareKey) }}
          role="img"
          aria-label={`Круговая диаграмма содержания программы ${label}`}
        >
          <div className="grid aspect-square w-[44%] place-items-center rounded-full bg-card px-2 text-center shadow-inner ring-1 ring-border/60">
            <strong className="font-serif text-2xl font-semibold tabular-nums text-foreground">{total > 0 ? formatShare(total) : "—"}</strong>
            <span className="text-[10px] leading-tight text-muted-foreground">учебной нагрузки</span>
          </div>
        </div>
        <ul className="grid w-full gap-1.5 border-t border-border/60 pt-4 sm:grid-cols-2" aria-label={`Легенда программы ${label}`}>
          {rows.map((row) => (
            <li key={row.code} className="flex min-w-0 items-center gap-2 text-xs">
              <span className="h-2.5 w-2.5 shrink-0 rounded-[3px] ring-1 ring-black/10" style={{ backgroundColor: row.color }} aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate text-muted-foreground" title={row.name}>{row.name}</span>
              <strong className="shrink-0 font-mono text-[11px] tabular-nums text-foreground">{formatShare(row[shareKey])}</strong>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

function ProgramHeader({ program, tone, navigate }: { program: ProgramSummary; tone: "A" | "B"; navigate: (route: Route) => void }) {
  return (
    <Card className="border-l-4 border-l-primary">
      <CardContent className="p-4">
        <div className="mb-1 flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-full bg-primary text-xs font-bold text-primary-foreground">{tone}</span>
          <span className="font-mono text-xs font-semibold text-primary">{program.code}</span>
        </div>
        <button onClick={() => navigate({ view: "program", id: program.id })} className="text-left font-serif text-lg font-semibold leading-snug hover:text-primary">
          {program.name}
        </button>
        <p className="mt-1 text-xs text-muted-foreground">{directionLabel(program.directionId)} · {program.educationYear}</p>
        <ProgramShortlistActions programId={program.id} navigate={navigate} compact />
      </CardContent>
    </Card>
  );
}
