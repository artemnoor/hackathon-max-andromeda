"use client";

import { useEffect, useState } from "react";
import { UserPlus, UserRound, UserX } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, Loading, SectionTitle, Tag } from "@/components/shared";
import { addUniversityMember, getUniversityMembers, revokeUniversityMember } from "@/lib/api";
import type { UniversityAdminRole, UniversityMembership } from "@/lib/types";

export function MemberList({ universityId, canManage }: { universityId: string; canManage: boolean }) {
  const [members, setMembers] = useState<UniversityMembership[]>([]);
  const [accountId, setAccountId] = useState("");
  const [role, setRole] = useState<UniversityAdminRole>("editor");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = async () => {
    setLoading(true); setError(null);
    try { setMembers(await getUniversityMembers(universityId)); } catch { setError("Не удалось загрузить участников."); } finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [universityId]);

  const add = async () => {
    if (!accountId.trim()) return;
    setBusy(true); setError(null);
    try { await addUniversityMember(universityId, { accountId: accountId.trim(), role }); setAccountId(""); await load(); }
    catch { setError("Не удалось добавить участника. Нужен существующий аккаунт и права владельца."); }
    finally { setBusy(false); }
  };
  const revoke = async (member: UniversityMembership) => {
    if (!window.confirm("Отозвать доступ участника?")) return;
    setBusy(true);
    try { await revokeUniversityMember(universityId, member.membershipId, member.revision); await load(); }
    catch { setError("Доступ уже изменился или это последний владелец."); }
    finally { setBusy(false); }
  };

  if (loading) return <Loading label="Загружаем команду вуза…" />;
  return <Card data-testid="university-member-list">
    <CardHeader><SectionTitle hint={`${members.length}`}>Команда вуза</SectionTitle><p className="text-sm text-muted-foreground">Добавляются только существующие account ID. Пароли и email здесь не запрашиваются.</p></CardHeader>
    <CardContent className="space-y-4">
      {error && <ErrorState title="Действие не выполнено" message={error} onRetry={() => void load()} />}
      {canManage && <div className="grid gap-2 md:grid-cols-[1fr_180px_auto]"><Input value={accountId} onChange={(event) => setAccountId(event.target.value)} placeholder="account:…" aria-label="Идентификатор аккаунта" /><select className="rounded-md border border-input bg-transparent px-3 py-2 text-sm" value={role} onChange={(event) => setRole(event.target.value as UniversityAdminRole)} aria-label="Роль участника"><option value="viewer">Наблюдатель</option><option value="editor">Редактор</option><option value="owner">Владелец</option></select><Button onClick={() => void add()} disabled={busy || !accountId.trim()} className="gap-1"><UserPlus className="h-4 w-4" /> Добавить</Button></div>}
      {members.length === 0 ? <EmptyState title="Участников нет" /> : <div className="space-y-2">{members.map((member) => <div key={member.membershipId} className="flex items-center justify-between gap-3 rounded-lg border border-border/70 p-3"><div className="flex min-w-0 items-center gap-3"><span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-muted"><UserRound className="h-4 w-4" /></span><div className="min-w-0"><p className="truncate text-sm font-medium">{member.accountId}</p><p className="text-xs text-muted-foreground">{member.status === "active" ? "Активен" : "Отозван"}</p></div></div><div className="flex items-center gap-2"><Tag tone={member.role === "owner" ? "primary" : "muted"}>{member.role}</Tag>{canManage && member.status === "active" && <Button variant="ghost" size="icon" aria-label={`Отозвать доступ ${member.accountId}`} onClick={() => void revoke(member)} disabled={busy}><UserX className="h-4 w-4" /></Button>}</div></div>)}</div>}
    </CardContent>
  </Card>;
}
