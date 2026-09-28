"use client";

import { ArrowRight, CircleAlert, Scale } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { safeExternalHref, SectionTitle, Tag } from "@/components/shared";
import type { Route } from "@/lib/router";
import type { ComparisonKeyDifference, ComparisonSummaryResponse, ComparisonTradeoff } from "@/lib/types";

export function CompareSummary({ data, navigate }: { data: ComparisonSummaryResponse; navigate: (route: Route) => void }) {
  const names = new Map(data.programs.map((item) => [item.program.id, item.program]));
  const differences = data.keyDifferences;
  const tradeoffs = data.tradeoffs;

  return (
    <section className="space-y-4" data-testid="comparison-summary" aria-labelledby="comparison-summary-title">
      <Card className="border-primary/20 bg-primary/5">
        <CardHeader className="pb-3">
          <SectionTitle hint={`${data.programs.length} программы`}>Короткий вывод</SectionTitle>
          <p id="comparison-summary-title" className="max-w-3xl text-sm text-muted-foreground">
            Программы не ранжируются в одного победителя: ниже — проверяемые различия и компромиссы, чтобы решение осталось вашим.
          </p>
        </CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.programs.map((overview) => (
            <div key={overview.program.id} className="rounded-xl border border-border/70 bg-background/80 p-4">
              <p className="font-mono text-xs text-primary">{overview.program.code}</p>
              <button type="button" className="mt-1 text-left font-serif text-lg font-semibold hover:text-primary" onClick={() => navigate({ view: "program", id: overview.program.id })}>
                {overview.program.name}
              </button>
              {overview.totals ? (
                <p className="mt-2 text-xs text-muted-foreground">{overview.totals.hours} ч · {overview.totals.credits} ЗЕТ</p>
              ) : (
                <p className="mt-2 flex items-center gap-1 text-xs text-amber-700"><CircleAlert className="h-3.5 w-3.5" />Учебный план неизвестен</p>
              )}
              {overview.sourceGaps.map((gap) => (
                <div key={gap.code} className="mt-2 rounded-lg bg-amber-50 px-2.5 py-2 text-xs text-amber-950">
                  <p className="font-medium">{gap.explanation ?? gap.message}</p>
                  <p className="mt-1">{gap.impact ?? "Сравнение продолжается, но этот блок нельзя считать полным."}</p>
                  {safeExternalHref(gap.sourceUrl) && <a className="mt-1 inline-block underline" href={safeExternalHref(gap.sourceUrl) ?? undefined} target="_blank" rel="noopener noreferrer">Официальный источник</a>}
                </div>
              ))}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3"><SectionTitle hint="только evidence-backed claims">Ключевые различия</SectionTitle></CardHeader>
        <CardContent>
          {differences.length === 0 ? (
            <p className="text-sm text-muted-foreground">Поддержанных различий в выбранном срезе не найдено.</p>
          ) : (
            <div className="space-y-3">
              {differences.map((difference, index) => <DifferenceRow key={`${difference.programAId}-${difference.programBId}-${difference.dimension}-${difference.label}-${index}`} difference={difference} names={names} />)}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3"><SectionTitle hint="advantage ≠ universal superiority"><span className="flex items-center gap-2"><Scale className="h-5 w-5 text-primary" /> Trade-offs</span></SectionTitle></CardHeader>
        <CardContent>
          {tradeoffs.length === 0 ? (
            <p className="text-sm text-muted-foreground">Для этого набора недостаточно сопоставимых данных, чтобы построить trade-offs.</p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {tradeoffs.map((tradeoff, index) => <TradeoffCard key={`${tradeoff.programId}-${tradeoff.pairedProgramId}-${index}`} tradeoff={tradeoff} names={names} />)}
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="border-dashed">
        <CardHeader className="pb-3"><SectionTitle>Admission context</SectionTitle></CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>Сравнение содержания не гарантирует поступление. Исторические проходные значения и ваши баллы нужно проверить отдельно для каждой программы.</p>
          <Button type="button" variant="outline" size="sm" onClick={() => navigate({ view: "catalog" })} className="gap-1">Открыть проверку в программе <ArrowRight className="h-4 w-4" /></Button>
        </CardContent>
      </Card>

      {data.sourceGaps.length > 0 && (
        <div className="rounded-lg border border-amber-300/60 bg-amber-50 px-4 py-3 text-sm text-amber-950" role="status" aria-live="polite">
          <p className="font-medium">Пробелы источников</p>
          <ul className="mt-1 space-y-2">{data.sourceGaps.map((gap, index) => <li key={`${gap.code}-${index}`}><span className="font-medium">{gap.explanation ?? gap.message}</span><br />{gap.impact ?? "Сравнение продолжается, но этот блок нельзя считать полным."} {gap.suggestedAction ?? "Откройте официальный источник и проверьте обновление данных."}</li>)}</ul>
        </div>
      )}
    </section>
  );
}
function DifferenceRow({ difference, names }: { difference: ComparisonKeyDifference; names: Map<string, { code: string; name: string }> }) {
  const left = names.get(difference.programAId)?.code ?? difference.programAId;
  const right = names.get(difference.programBId)?.code ?? difference.programBId;
  const direction = difference.direction === "more_in_a" ? `больше в ${left}` : difference.direction === "more_in_b" ? `больше в ${right}` : difference.direction === "different" ? "различается" : "неизвестно";
  return (
    <div className="rounded-lg border border-border/70 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium">{difference.label}</p>
        <Tag tone="muted">{difference.dimension} · {direction}</Tag>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">{left}: {difference.valueA ?? "нет данных"} · {right}: {difference.valueB ?? "нет данных"}</p>
      <p className="mt-1 text-xs text-muted-foreground">Сравнено: {left} ↔ {right} · evidence: {difference.evidence.map((item) => `${item.kind}:${item.key}`).join(", ")}</p>
    </div>
  );
}

function TradeoffCard({ tradeoff, names }: { tradeoff: ComparisonTradeoff; names: Map<string, { code: string; name: string }> }) {
  const program = names.get(tradeoff.programId);
  const paired = names.get(tradeoff.pairedProgramId);
  return (
    <div className="rounded-xl border border-border/70 bg-background/60 p-4">
      <p className="font-mono text-xs text-primary">{program?.code ?? tradeoff.programId} · в сравнении с {paired?.code ?? tradeoff.pairedProgramId}</p>
      <p className="mt-2 text-sm font-medium">{tradeoff.advantage}</p>
      <p className="mt-1 text-sm text-muted-foreground">Учесть: {tradeoff.consideration}</p>
      <p className="mt-2 text-xs text-muted-foreground">Evidence: {tradeoff.evidence.map((item) => `${item.kind}:${item.key}`).join(", ")}</p>
    </div>
  );
}
