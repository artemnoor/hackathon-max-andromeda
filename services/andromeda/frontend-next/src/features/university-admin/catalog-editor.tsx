"use client";

import { useEffect, useState } from "react";
import { Archive, Plus, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, Loading, SectionTitle, Tag } from "@/components/shared";
import {
  archiveUniversityCategory,
  archiveUniversityUnit,
  createUniversityCategory,
  createUniversityUnit,
  getUniversityCatalog,
  getUniversityCategories,
  updateUniversityDisciplineEditorial,
  updateUniversityProgramEditorial,
  getUniversityUnits,
} from "@/lib/api";
import type { UniversityCatalog, UniversityCategory, UniversityUnit } from "@/lib/types";

type Props = { universityId: string; canEdit: boolean };

const fieldClass = "rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function CatalogEditor({ universityId, canEdit }: Props) {
  const [units, setUnits] = useState<UniversityUnit[]>([]);
  const [categories, setCategories] = useState<UniversityCategory[]>([]);
  const [catalog, setCatalog] = useState<UniversityCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [unitName, setUnitName] = useState("");
  const [categoryName, setCategoryName] = useState("");
  const [programId, setProgramId] = useState("");
  const [programDisplayName, setProgramDisplayName] = useState("");
  const [disciplineId, setDisciplineId] = useState("");
  const [disciplineDisplayName, setDisciplineDisplayName] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextUnits, nextCategories, nextCatalog] = await Promise.all([
        getUniversityUnits(universityId),
        getUniversityCategories(universityId),
        getUniversityCatalog(universityId),
      ]);
      setUnits(nextUnits);
      setCategories(nextCategories);
      setCatalog(nextCatalog);
      if (!programId && nextCatalog.programs[0]) setProgramId(nextCatalog.programs[0].programId);
      if (!disciplineId && nextCatalog.disciplines[0]) setDisciplineId(nextCatalog.disciplines[0].disciplineId);
    } catch {
      setError("Не удалось загрузить редакцию каталога.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [universityId]);

  const createUnit = async () => {
    if (!unitName.trim()) return;
    setBusy(true);
    try {
      await createUniversityUnit(universityId, {
        unitType: "faculty",
        parentUnitId: null,
        slug: unitName.trim().toLowerCase().replace(/[^a-z0-9а-яё]+/gi, "-").replace(/^-|-$/g, ""),
        name: unitName.trim(),
        description: null,
        status: "published",
        sortOrder: units.length,
      });
      setUnitName("");
      await load();
    } catch {
      setError("Не удалось создать подразделение. Проверьте права и уникальность slug.");
    } finally {
      setBusy(false);
    }
  };

  const createCategory = async () => {
    if (!categoryName.trim()) return;
    setBusy(true);
    try {
      await createUniversityCategory(universityId, {
        slug: categoryName.trim().toLowerCase().replace(/[^a-z0-9а-яё]+/gi, "-").replace(/^-|-$/g, ""),
        name: categoryName.trim(),
        description: null,
        categoryKind: "general",
        status: "published",
        sortOrder: categories.length,
      });
      setCategoryName("");
      await load();
    } catch {
      setError("Не удалось создать категорию. Проверьте права и уникальность slug.");
    } finally {
      setBusy(false);
    }
  };

  const archiveUnit = async (unit: UniversityUnit) => {
    if (!window.confirm(`Архивировать «${unit.name}»?`)) return;
    setBusy(true);
    try { await archiveUniversityUnit(universityId, unit.unitId, unit.revision); await load(); }
    catch { setError("Данные подразделения изменились. Обновите список и повторите действие."); }
    finally { setBusy(false); }
  };

  const archiveCategory = async (category: UniversityCategory) => {
    if (!window.confirm(`Архивировать «${category.name}»?`)) return;
    setBusy(true);
    try { await archiveUniversityCategory(universityId, category.categoryId, category.revision); await load(); }
    catch { setError("Данные категории изменились. Обновите список и повторите действие."); }
    finally { setBusy(false); }
  };

  const saveProgramOverlay = async () => {
    if (!programId) return;
    setBusy(true); setError(null);
    try { await updateUniversityProgramEditorial(universityId, programId, { displayName: programDisplayName.trim() || null, publicSummary: null, visibility: "visible", expectedRevision: null }); setProgramDisplayName(""); await load(); }
    catch { setError("Не удалось обновить представление программы."); }
    finally { setBusy(false); }
  };

  const saveDisciplineOverlay = async () => {
    if (!disciplineId) return;
    setBusy(true); setError(null);
    try { await updateUniversityDisciplineEditorial(universityId, disciplineId, { displayName: disciplineDisplayName.trim() || null, publicSummary: null, visibility: "visible", expectedRevision: null }); setDisciplineDisplayName(""); await load(); }
    catch { setError("Не удалось обновить представление предмета."); }
    finally { setBusy(false); }
  };

  if (loading) return <Loading label="Загружаем редакцию каталога…" />;
  if (error && !catalog) return <ErrorState message={error} onRetry={() => void load()} />;

  return (
    <div className="space-y-6" data-testid="university-catalog-editor">
      {error && <ErrorState title="Изменение не применено" message={error} onRetry={() => void load()} />}
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => void load()} disabled={busy} className="gap-1"><RefreshCw className="h-4 w-4" /> Обновить</Button>
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader><SectionTitle hint={`${units.length}`}>Факультеты и кафедры</SectionTitle></CardHeader>
          <CardContent className="space-y-4">
            {canEdit && (
              <div className="flex gap-2"><Input value={unitName} onChange={(event) => setUnitName(event.target.value)} placeholder="Название факультета" aria-label="Название подразделения" /><Button onClick={() => void createUnit()} disabled={busy || !unitName.trim()} className="gap-1"><Plus className="h-4 w-4" /> Добавить</Button></div>
            )}
            {units.length === 0 ? <EmptyState title="Подразделений пока нет" message="Добавьте факультет, затем кафедры можно связать с ним через API каталога." /> : (
              <div className="space-y-2">{units.map((unit) => <div key={unit.unitId} className="flex items-center justify-between gap-3 rounded-lg border border-border/70 p-3"><div><p className="font-medium">{unit.name}</p><p className="text-xs text-muted-foreground">{unit.unitType === "faculty" ? "Факультет" : "Кафедра"} · {unit.status}</p></div>{canEdit && unit.status !== "archived" && <Button variant="ghost" size="icon" aria-label={`Архивировать ${unit.name}`} onClick={() => void archiveUnit(unit)} disabled={busy}><Archive className="h-4 w-4" /></Button>}</div>)}</div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><SectionTitle hint={`${categories.length}`}>Категории каталога</SectionTitle></CardHeader>
          <CardContent className="space-y-4">
            {canEdit && (
              <div className="flex gap-2"><Input value={categoryName} onChange={(event) => setCategoryName(event.target.value)} placeholder="Например, Инженерные программы" aria-label="Название категории" /><Button onClick={() => void createCategory()} disabled={busy || !categoryName.trim()} className="gap-1"><Plus className="h-4 w-4" /> Добавить</Button></div>
            )}
            {categories.length === 0 ? <EmptyState title="Категорий пока нет" message="Категории помогают собрать программы и предметы в понятные витрины." /> : (
              <div className="space-y-2">{categories.map((category) => <div key={category.categoryId} className="flex items-center justify-between gap-3 rounded-lg border border-border/70 p-3"><div><p className="font-medium">{category.name}</p><div className="flex gap-1.5 pt-1"><Tag tone="muted">{category.categoryKind}</Tag><Tag tone="muted">{category.status}</Tag></div></div>{canEdit && category.status !== "archived" && <Button variant="ghost" size="icon" aria-label={`Архивировать ${category.name}`} onClick={() => void archiveCategory(category)} disabled={busy}><Archive className="h-4 w-4" /></Button>}</div>)}</div>
            )}
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader><SectionTitle hint={catalog ? `${catalog.programs.length} программ · ${catalog.disciplines.length} предметов` : undefined}>Канонический каталог</SectionTitle></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2"><div className="rounded-xl bg-muted/50 p-4"><p className="text-sm font-medium">Программы</p><p className="mt-1 text-2xl font-serif font-semibold">{catalog?.programs.length ?? 0}</p><p className="text-xs text-muted-foreground">Источник остаётся каноническим, вуз управляет только представлением.</p></div><div className="rounded-xl bg-muted/50 p-4"><p className="text-sm font-medium">Предметы</p><p className="mt-1 text-2xl font-serif font-semibold">{catalog?.disciplines.length ?? 0}</p><p className="text-xs text-muted-foreground">Скрытие и подписи задаются редакционными overlay.</p></div></CardContent>
      </Card>
      {canEdit && catalog && (catalog.programs.length > 0 || catalog.disciplines.length > 0) && <Card>
        <CardHeader><SectionTitle>Представление программ и предметов</SectionTitle><p className="text-sm text-muted-foreground">Канонические записи не меняются: здесь можно задать публичное название overlay.</p></CardHeader>
        <CardContent className="grid gap-5 md:grid-cols-2">
          {catalog.programs.length > 0 && <div className="space-y-2"><label className="text-sm font-medium" htmlFor="university-program-overlay">Программа</label><select id="university-program-overlay" className={fieldClass} value={programId} onChange={(event) => setProgramId(event.target.value)}>{catalog.programs.map((program) => <option key={program.programId} value={program.programId}>{program.name}</option>)}</select><Input value={programDisplayName} onChange={(event) => setProgramDisplayName(event.target.value)} placeholder="Публичное название" aria-label="Публичное название программы" /><Button onClick={() => void saveProgramOverlay()} disabled={busy} size="sm">Сохранить программу</Button></div>}
          {catalog.disciplines.length > 0 && <div className="space-y-2"><label className="text-sm font-medium" htmlFor="university-discipline-overlay">Предмет</label><select id="university-discipline-overlay" className={fieldClass} value={disciplineId} onChange={(event) => setDisciplineId(event.target.value)}>{catalog.disciplines.map((discipline) => <option key={discipline.disciplineId} value={discipline.disciplineId}>{discipline.name}</option>)}</select><Input value={disciplineDisplayName} onChange={(event) => setDisciplineDisplayName(event.target.value)} placeholder="Публичное название" aria-label="Публичное название предмета" /><Button onClick={() => void saveDisciplineOverlay()} disabled={busy} size="sm">Сохранить предмет</Button></div>}
        </CardContent>
      </Card>}
    </div>
  );
}
