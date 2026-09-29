"use client";

import { useEffect, useState } from "react";
import { ArrowRight, Building2, CalendarDays } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState, Loading, PageHeader, SectionTitle, Tag } from "@/components/shared";
import { getUniversities, getUniversityCatalog } from "@/lib/api";
import type { UniversityCatalog, UniversityDiscovery } from "@/lib/types";
import type { Route } from "@/lib/router";

export function UniversityCatalogPage({ universityId, navigate }: { universityId?: string; navigate: (route: Route) => void }) {
  const [universities, setUniversities] = useState<UniversityDiscovery[]>([]);
  const [catalog, setCatalog] = useState<UniversityCatalog | null>(null);
  const [selectedId, setSelectedId] = useState(universityId ?? "");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getUniversities().then((items) => { setUniversities(items); if (!selectedId && items.length === 1) setSelectedId(items[0].id); }).catch(() => setError("Не удалось найти поддерживаемые вузы.")).finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    if (!selectedId) { setCatalog(null); return; }
    setLoading(true); setError(null);
    getUniversityCatalog(selectedId).then(setCatalog).catch(() => setError("Каталог этого вуза пока недоступен.")).finally(() => setLoading(false));
  }, [selectedId]);

  return <div data-testid="university-catalog-page">
    <PageHeader eyebrow="Университеты" title="Каталог вуза" description="Смотрите факультеты, категории, образовательные программы и предметы, которые вуз подготовил для абитуриентов." actions={catalog ? <Button variant="outline" className="gap-1" onClick={() => navigate({ view: "events", id: catalog.universityId })}><CalendarDays className="h-4 w-4" /> Афиша вуза</Button> : undefined} />
    <Card className="mb-6"><CardContent className="flex flex-col gap-3 p-4 md:flex-row md:items-center"><label className="text-sm font-medium" htmlFor="public-university-select">Выберите вуз</label><select id="public-university-select" className="min-h-9 flex-1 rounded-md border border-input bg-transparent px-3 py-2 text-sm" value={selectedId} onChange={(event) => { setSelectedId(event.target.value); navigate({ view: "university-catalog", id: event.target.value }); }}><option value="">Не выбран</option>{universities.map((university) => <option key={university.id} value={university.id}>{university.name} · {university.city}</option>)}</select></CardContent></Card>
    {loading && <Loading label="Загружаем каталог вуза…" />}
    {error && <ErrorState message={error} onRetry={() => selectedId && setSelectedId(selectedId)} />}
    {!loading && !catalog && !error && <EmptyState title="Выберите вуз" message="Публичный каталог доступен без регистрации." />}
    {catalog && !loading && <div className="space-y-6"><Card><CardContent className="flex flex-col gap-3 p-6 md:flex-row md:items-start"><span className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-primary text-primary-foreground"><Building2 className="h-6 w-6" /></span><div><h2 className="font-serif text-2xl font-semibold">{catalog.universityName}</h2><p className="text-sm text-muted-foreground">{catalog.city} · {catalog.address}</p><a href={catalog.officialSite} target="_blank" rel="noreferrer" className="mt-1 inline-block text-sm text-primary hover:underline">Официальный сайт</a></div></CardContent></Card><div className="grid gap-6 lg:grid-cols-2"><Card><CardHeader><SectionTitle hint={`${catalog.units.length}`}>Факультеты и кафедры</SectionTitle></CardHeader><CardContent className="space-y-2">{catalog.units.length === 0 ? <p className="text-sm text-muted-foreground">Редакционные подразделения ещё не опубликованы.</p> : catalog.units.map((unit) => <div key={unit.unitId} className="rounded-lg border border-border/70 p-3"><p className="font-medium">{unit.name}</p><p className="text-xs text-muted-foreground">{unit.unitType === "faculty" ? "Факультет" : "Кафедра"}</p></div>)}</CardContent></Card><Card><CardHeader><SectionTitle hint={`${catalog.categories.length}`}>Категории</SectionTitle></CardHeader><CardContent className="flex flex-wrap gap-2">{catalog.categories.length === 0 ? <p className="text-sm text-muted-foreground">Категории ещё не опубликованы.</p> : catalog.categories.map((category) => <Tag key={category.categoryId} tone="primary">{category.name}</Tag>)}</CardContent></Card></div><Card><CardHeader><SectionTitle hint={`${catalog.programs.length}`}>Образовательные программы</SectionTitle></CardHeader><CardContent className="grid gap-3 md:grid-cols-2">{catalog.programs.length === 0 ? <p className="text-sm text-muted-foreground">Программы не найдены в текущем срезе.</p> : catalog.programs.map((program) => <button key={program.programId} type="button" onClick={() => navigate({ view: "program", id: program.programId })} className="rounded-xl border border-border/70 p-4 text-left transition hover:border-primary/50"><p className="font-medium">{program.displayName ?? program.name}</p>{program.publicSummary && <p className="mt-1 text-sm text-muted-foreground">{program.publicSummary}</p>}<span className="mt-2 inline-flex items-center gap-1 text-xs text-primary">Открыть программу <ArrowRight className="h-3 w-3" /></span></button>)}</CardContent></Card><Card><CardHeader><SectionTitle hint={`${catalog.disciplines.length}`}>Предметы</SectionTitle></CardHeader><CardContent className="flex flex-wrap gap-2">{catalog.disciplines.length === 0 ? <p className="text-sm text-muted-foreground">Предметы пока не опубликованы.</p> : catalog.disciplines.map((discipline) => <Tag key={discipline.disciplineId}>{discipline.displayName ?? discipline.name}</Tag>)}</CardContent></Card></div>}
  </div>;
}
