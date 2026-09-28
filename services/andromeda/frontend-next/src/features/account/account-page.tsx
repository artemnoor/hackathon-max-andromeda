"use client";

import { useEffect, useState } from "react";
import { UserRound, LogOut, Sparkles, Mail } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader, Loading, ProfileRequired, Stat, SectionTitle, Tag } from "@/components/shared";
import { getAuthSession, getCurrentProfile, getUniversityMemberships, logoutAccount } from "@/lib/api";
import { formatPercent, formatDate } from "@/lib/format";
import type { AuthSession, UniversityMembership, UserProfileSnapshot } from "@/lib/types";
import type { Route as RouteType } from "@/lib/router";
import { DecisionPage } from "@/features/decision/decision-page";

export function AccountPage({ navigate }: { navigate: (route: RouteType) => void }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [profile, setProfile] = useState<UserProfileSnapshot | null>(null);
  const [memberships, setMemberships] = useState<UniversityMembership[]>([]);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    Promise.all([getAuthSession(), getCurrentProfile().catch(() => null), getUniversityMemberships().catch(() => [])])
      .then(([s, p, m]) => {
        setSession(s);
        setProfile(p);
        setMemberships(m);
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading || !session) return <Loading label="Загружаем кабинет…" />;

  if (!session.authenticated) {
    return (
      <div data-testid="account-page" className="space-y-6">
        <PageHeader eyebrow="Кабинет" title="Личный кабинет" />
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
            <div className="grid h-12 w-12 place-items-center rounded-full bg-accent text-accent-foreground">
              <UserRound className="h-6 w-6" />
            </div>
            <h3 className="font-serif text-lg font-semibold">Вы вошли как гость</h3>
            <p className="max-w-md text-sm text-muted-foreground">
              Гостевая сессия уже позволяет проходить тест и смотреть рекомендации. Зарегистрируйтесь, чтобы сохранить
              профиль между устройствами.
            </p>
            <div className="flex gap-2">
              <Button onClick={() => navigate({ view: "decision" })} className="bg-primary text-primary-foreground hover:bg-primary/90">Открыть мой выбор</Button>
              <Button variant="outline" onClick={() => navigate({ view: "proftest" })}>Уточнить предпочтения</Button>
            </div>
          </CardContent>
        </Card>
        <DecisionPage navigate={navigate} />
      </div>
    );
  }

  const acc = session.account!;
  return (
    <div data-testid="account-page">
      <PageHeader
        eyebrow="Кабинет"
        title={`Привет, ${acc.displayName ?? acc.email}`}
        description="Аккаунт, профиль предпочтений и сохранённый выбор. События и поддерживающие сценарии доступны отдельно."
        actions={
          <Button variant="outline" size="sm" className="gap-1" onClick={async () => { await logoutAccount(); load(); }}>
            <LogOut className="h-4 w-4" /> Выйти
          </Button>
        }
      />

      <Card className="mb-6">
        <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
          <span className="grid h-14 w-14 place-items-center rounded-2xl bg-primary font-serif text-2xl font-semibold text-primary-foreground">
            {acc.email[0]?.toUpperCase()}
          </span>
          <div className="flex-1">
            <p className="flex items-center gap-2 font-serif text-lg font-semibold">{acc.displayName ?? acc.email}</p>
            <p className="flex items-center gap-1 text-sm text-muted-foreground"><Mail className="h-3.5 w-3.5" /> {acc.email}</p>
          </div>
          <div className="flex gap-3">
            <Stat label="С нами с" value={formatDate(acc.createdAt)} />
          </div>
        </CardContent>
      </Card>

      {memberships.length > 0 && (
        <Card className="mb-6 border-primary/20 bg-primary/5">
          <CardContent className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
            <div><p className="font-serif text-lg font-semibold">Кабинет вуза</p><p className="text-sm text-muted-foreground">У вас есть доступ к управлению каталогом и афишей {memberships.length > 1 ? `${memberships.length} вузов` : "вуза"}.</p></div>
            <Button onClick={() => navigate({ view: "university-admin", id: memberships.length === 1 ? memberships[0].universityId : undefined })}>Открыть админку</Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="pb-3">
            <SectionTitle hint={profile ? `ревизия ${profile.revision}` : ""}>Профиль</SectionTitle>
          </CardHeader>
          <CardContent>
            {profile ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Уверенность" value={formatPercent(profile.profile.confidence, 0)} />
                  <Stat label="Обновлён" value={formatDate(profile.updatedAt)} />
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {profile.profile.interests.map((i) => <Tag key={i} tone="muted">{i}</Tag>)}
                </div>
                <Button variant="outline" size="sm" onClick={() => navigate({ view: "proftest" })} className="gap-1">
                  <Sparkles className="h-4 w-4" /> Пройти тест заново
                </Button>
              </div>
            ) : (
              <ProfileRequired onAction={() => navigate({ view: "proftest" })} />
            )}
          </CardContent>
        </Card>
      </div>

      <DecisionPage navigate={navigate} />
    </div>
  );
}
