"use client";

import { useMemo, useState } from "react";
import { Search, ArrowRight, BookOpen, GraduationCap } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader, Tag, Loading, ErrorState, EmptyState } from "@/components/shared";
import { directionLabel } from "@/lib/labels";
import type { ProgramSummary } from "@/lib/types";
import type { Route } from "@/lib/router";
import { ProgramShortlistActions } from "@/features/decision/program-shortlist-actions";
import { useDecisionContext } from "@/features/decision/decision-context";

export function CatalogPage({
  programs,
  loading,
  error,
  onRetry,
  navigate,
}: {
  programs: ProgramSummary[];
  loading: boolean;
  error: string | null;
  onRetry?: () => void;
  navigate: (route: Route) => void;
}) {
  const [query, setQuery] = useState("");
  const [direction, setDirection] = useState("all");
  const [year, setYear] = useState("all");
  const [university, setUniversity] = useState("all");
  const { activeShortlist } = useDecisionContext();

  const directions = useMemo(() => [...new Set(programs.map((p) => p.directionId))].sort(), [programs]);
  const years = useMemo(() => [...new Set(programs.map((p) => p.educationYear))].sort().reverse(), [programs]);
  const universities = useMemo(() => [...new Set(programs.map((p) => p.universityId).filter((value): value is string => Boolean(value)))].sort(), [programs]);
  const universityNames = useMemo(
    () => [...new Set(programs.map((program) => program.universityName).filter((value): value is string => Boolean(value)))].sort(),
    [programs],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return programs.filter((p) => {
      if (direction !== "all" && p.directionId !== direction) return false;
      if (year !== "all" && p.educationYear !== year) return false;
      if (university !== "all" && p.universityId !== university) return false;
      if (!q) return true;
      return (
        p.name.toLowerCase().includes(q) ||
        p.code.toLowerCase().includes(q) ||
        p.directionId.toLowerCase().includes(q) ||
        directionLabel(p.directionId).toLowerCase().includes(q)
      );
    });
  }, [programs, query, direction, year, university]);

  if (loading) return <Loading label="Загружаем каталог программ…" />;
  if (error) return <ErrorState title="Каталог недоступен" message={error} onRetry={onRetry} />;

  return (
    <div data-testid="catalog-page">
      <PageHeader
        eyebrow="Каталог"
        title="Каталог образовательных программ"
        description={`${universityNames.length > 0 ? `Программы ${universityNames.join(" и ")}` : "Программы поддерживаемых университетов"} с привязкой к учебным планам, поступлению и сравнению. Источник — официальные открытые данные.`}
        actions={activeShortlist.length >= 2 ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-testid="catalog-shortlist-next"
            onClick={() => navigate({ view: "compare" })}
          >
            Сравнить мой shortlist <ArrowRight className="h-4 w-4" />
          </Button>
        ) : undefined}
      />

      <Card className="mb-6 border-border/70 bg-card/80">
        <CardContent className="flex min-w-0 flex-col gap-3 p-4 md:flex-row md:items-center">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск по коду, названию или направлению…"
              className="pl-9"
            />
          </div>
          <div className="grid min-w-0 grid-cols-1 gap-2 sm:flex sm:flex-wrap">
            <Select value={university} onValueChange={setUniversity}>
              <SelectTrigger className="w-full sm:w-[180px]"><SelectValue placeholder="Университет" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все университеты</SelectItem>
                {universities.map((id) => <SelectItem key={id} value={id}>{programs.find((p) => p.universityId === id)?.universityName ?? id.replace("university:", "")}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={direction} onValueChange={setDirection}>
              <SelectTrigger className="w-full sm:w-[200px]">
                <SelectValue placeholder="Направление" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все направления</SelectItem>
                {directions.map((d) => (
                  <SelectItem key={d} value={d}>
                    {d} · {directionLabel(d)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={year} onValueChange={setYear}>
              <SelectTrigger className="w-full sm:w-[130px]">
                <SelectValue placeholder="Год" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Все годы</SelectItem>
                {years.map((y) => (
                  <SelectItem key={y} value={y}>{y}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      <p className="mb-4 text-sm text-muted-foreground">
        Найдено программ: <span className="font-semibold text-foreground">{filtered.length}</span>
      </p>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((p) => (
          <Card
            key={p.id}
            className="group flex flex-col border-border/70 transition hover:-translate-y-0.5 hover:shadow-md"
          >
            <CardHeader className="pb-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span className="inline-flex max-w-full min-w-0 items-center gap-1 rounded-md bg-primary/10 px-2 py-0.5 font-mono text-xs font-semibold text-primary">
                  <GraduationCap className="h-3.5 w-3.5" />
                  <span className="break-words">{p.code}</span>
                </span>
                <Tag tone="muted">{p.educationYear}</Tag>
                {p.universityName && <Tag tone="muted"><span className="break-words">{p.universityName}</span></Tag>}
              </div>
              <h3 className="mt-2 break-words font-serif text-lg font-semibold leading-snug text-foreground">
                {p.name}
              </h3>
            </CardHeader>
            <CardContent className="flex-1 pb-3">
              <p className="text-sm text-muted-foreground">
                Направление <span className="font-medium text-foreground">{directionLabel(p.directionId)}</span>
              </p>
            </CardContent>
            <CardFooter className="flex flex-col items-stretch gap-2 border-t border-border/60 pt-3">
              <div className="flex flex-col items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
                <span className="inline-flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
                  <BookOpen className="h-3.5 w-3.5" /> учебный план · поступление
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  className="shrink-0 gap-1 self-end text-primary group-hover:bg-primary group-hover:text-primary-foreground sm:self-auto"
                  onClick={() => navigate({ view: "program", id: p.id })}
                >
                  Открыть <ArrowRight className="h-4 w-4 transition group-hover:translate-x-0.5" />
                </Button>
              </div>
              <ProgramShortlistActions programId={p.id} compact />
            </CardFooter>
          </Card>
        ))}
      </div>

      {filtered.length === 0 && programs.length > 0 && (
        <EmptyState
          title="По этим фильтрам программ нет"
          message="Измените запрос или сбросьте фильтры, чтобы вернуться ко всему поддерживаемому каталогу."
          action={<Button type="button" variant="outline" onClick={() => { setQuery(""); setDirection("all"); setYear("all"); setUniversity("all"); }}>Сбросить фильтры</Button>}
        />
      )}
      {filtered.length === 0 && programs.length === 0 && (
        <EmptyState title="Каталог пока пуст" message="В текущем срезе нет опубликованных программ. Попробуйте обновить данные позже или обратитесь к администратору источника." />
      )}
    </div>
  );
}
