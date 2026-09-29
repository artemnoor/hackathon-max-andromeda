"use client";

import { useEffect, useMemo, useState } from "react";
import { Building2, ShieldCheck } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorState, Loading, PageHeader, Stat, Tag } from "@/components/shared";
import { ApiError, getAuthSession, getUniversityMemberships } from "@/lib/api";
import type { AuthSession, UniversityMembership } from "@/lib/types";
import type { Route } from "@/lib/router";
import { CatalogEditor } from "@/features/university-admin/catalog-editor";
import { EventEditor } from "@/features/university-admin/event-editor";
import { MemberList } from "@/features/university-admin/member-list";
import { canEditUniversity, canManageUniversityMembers } from "@/features/university-admin/permissions";

export function UniversityAdminPage({ requestedUniversityId, navigate }: { requestedUniversityId?: string; navigate: (route: Route) => void }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [memberships, setMemberships] = useState<UniversityMembership[]>([]);
  const [selectedMembershipId, setSelectedMembershipId] = useState(requestedUniversityId ? "" : "");
  const [tab, setTab] = useState("overview");
  const [loading, setLoading] = useState(true);
  const [errorStatus, setErrorStatus] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true); setErrorStatus(null);
    getAuthSession().then(async (nextSession) => {
      if (!active) return;
      setSession(nextSession);
      if (!nextSession.authenticated) return;
      try {
        const nextMemberships = await getUniversityMemberships();
        if (!active) return;
        setMemberships(nextMemberships);
        const requested = requestedUniversityId ? nextMemberships.find((item) => item.universityId === requestedUniversityId) : undefined;
        if (requested) setSelectedMembershipId(requested.membershipId);
        else if (nextMemberships.length === 1) setSelectedMembershipId(nextMemberships[0].membershipId);
      } catch (reason) {
        if (active) setErrorStatus(reason instanceof ApiError ? reason.status : 500);
      }
    }).catch((reason) => active && setErrorStatus(reason instanceof ApiError ? reason.status : 500)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [requestedUniversityId]);

  const selected = useMemo(() => memberships.find((item) => item.membershipId === selectedMembershipId) ?? null, [memberships, selectedMembershipId]);
  const canEdit = selected ? canEditUniversity(selected.role) : false;
  const canManageMembers = selected ? canManageUniversityMembers(selected.role) : false;

  if (loading || !session) return <Loading label="Проверяем доступ к кабинету вуза…" />;
  if (!session.authenticated) return <Card><CardContent className="space-y-4 p-8"><PageHeader eyebrow="Админка вуза" title="Войдите, чтобы продолжить" description="Кабинет доступен только участникам конкретного вуза." /><Button onClick={() => navigate({ view: "account" })}>Открыть кабинет и войти</Button></CardContent></Card>;
  if (errorStatus === 401) return <ErrorState title="Сессия истекла" message="Войдите снова в личном кабинете." onRetry={() => navigate({ view: "account" })} />;
  if (errorStatus === 403) return <EmptyState title="Нет доступа к админке вуза" message="У аккаунта нет активной membership вуза. Доступ назначает оператор или владелец." />;
  if (errorStatus) return <ErrorState message="Не удалось проверить доступ к кабинету вуза." />;
  if (memberships.length === 0) return <EmptyState title="Нет доступных вузов" message="Для этого аккаунта ещё не назначена роль в админке вуза." />;
  if (!selected) return (
    <div data-testid="university-scope-selector">
      <PageHeader eyebrow="Админка вуза" title="Выберите вуз" description="У аккаунта несколько membership. Мы не выбираем вуз автоматически, чтобы не изменить чужой контент." />
      <div className="grid gap-4 md:grid-cols-2">{memberships.map((membership) => <button key={membership.membershipId} type="button" onClick={() => { setSelectedMembershipId(membership.membershipId); setTab("overview"); }} className="rounded-xl border border-border/70 bg-card p-5 text-left transition hover:border-primary/50 hover:shadow-sm"><div className="flex items-start justify-between gap-3"><div><p className="font-serif text-lg font-semibold">{membership.universityName ?? membership.universityId}</p><p className="mt-1 text-sm text-muted-foreground">{membership.universityId}</p></div><Tag tone="primary">{membership.role}</Tag></div></button>)}</div>
    </div>
  );

  const universityName = selected.universityName ?? selected.universityId;
  return <div data-testid="university-admin-page">
    <PageHeader eyebrow="Админка вуза" title={universityName} description="Управляйте витриной каталога и афишей. Все изменения проверяются backend по membership и ревизии." actions={<Button variant="outline" onClick={() => setSelectedMembershipId("")}>Сменить вуз</Button>} />
    <Card className="mb-6"><CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center"><span className="grid h-12 w-12 place-items-center rounded-2xl bg-primary text-primary-foreground"><Building2 className="h-6 w-6" /></span><div className="flex-1"><p className="font-serif text-lg font-semibold">{universityName}</p><p className="text-sm text-muted-foreground">{selected.universityId}</p></div><div className="flex gap-3"><Stat label="Роль" value={selected.role} /><Stat label="Статус" value={<span className="inline-flex items-center gap-1 text-base"><ShieldCheck className="h-4 w-4 text-emerald-600" /> active</span>} /></div></CardContent></Card>
    <Tabs value={tab} onValueChange={setTab} className="space-y-5">
      <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1"><TabsTrigger value="overview">Обзор</TabsTrigger><TabsTrigger value="catalog">Каталог</TabsTrigger><TabsTrigger value="events">События</TabsTrigger>{canManageMembers && <TabsTrigger value="members">Участники</TabsTrigger>}</TabsList>
      <TabsContent value="overview"><Card><CardContent className="grid gap-4 p-6 md:grid-cols-3"><div><p className="text-sm font-medium">Что можно менять</p><p className="mt-1 text-sm text-muted-foreground">Подразделения, категории и редакционные подписи каталога.</p></div><div><p className="text-sm font-medium">Афиша</p><p className="mt-1 text-sm text-muted-foreground">Черновики, публикация, аудитория и план каждого мероприятия.</p></div><div><p className="text-sm font-medium">Ваша роль</p><p className="mt-1 text-sm text-muted-foreground">{canManageMembers ? "Владелец управляет командой." : canEdit ? "Редактор управляет контентом." : "Наблюдатель может только просматривать."}</p></div></CardContent></Card></TabsContent>
      <TabsContent value="catalog"><CatalogEditor universityId={selected.universityId} canEdit={Boolean(canEdit)} /></TabsContent>
      <TabsContent value="events"><EventEditor universityId={selected.universityId} canEdit={Boolean(canEdit)} /></TabsContent>
      {canManageMembers && <TabsContent value="members"><MemberList universityId={selected.universityId} canManage /></TabsContent>}
    </Tabs>
  </div>;
}
