"use client";

import { useEffect, useState } from "react";
import { CalendarPlus, Check, Eye, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, Loading, SectionTitle, Tag } from "@/components/shared";
import { createUniversityEvent, getUniversityAdminEvents, publishUniversityEvent } from "@/lib/api";
import type { EventFormat, EventKind, UniversityAudienceMode, UniversityEvent, UniversityEventStatus } from "@/lib/types";
import type { UniversityEventRequest } from "@/lib/api";

type Props = { universityId: string; canEdit: boolean };
const fieldClass = "rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

function csv(value: string): string[] { return value.split(",").map((item) => item.trim()).filter(Boolean); }

export function EventEditor({ universityId, canEdit }: Props) {
  const [events, setEvents] = useState<UniversityEvent[]>([]);
  const [status, setStatus] = useState<UniversityEventStatus | "all">("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<EventKind>("open_day");
  const [format, setFormat] = useState<EventFormat>("offline");
  const [description, setDescription] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [audienceMode, setAudienceMode] = useState<UniversityAudienceMode>("all_university");
  const [unitIds, setUnitIds] = useState("");
  const [programIds, setProgramIds] = useState("");
  const [categoryIds, setCategoryIds] = useState("");
  const [registrationUrl, setRegistrationUrl] = useState("");
  const [locationLabel, setLocationLabel] = useState("");
  const [locationAddress, setLocationAddress] = useState("");
  const [venueId, setVenueId] = useState("");
  const [agendaTitle, setAgendaTitle] = useState("");
  const [agenda, setAgenda] = useState<{ itemId: string; position: number; title: string; description: string | null; }[]>([]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try { const result = await getUniversityAdminEvents(universityId, status === "all" ? undefined : status); setEvents(result.items); }
    catch { setError("Не удалось загрузить афишу вуза."); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, [universityId, status]);

  const addAgendaItem = () => {
    if (!agendaTitle.trim()) return;
    setAgenda((items) => [...items, { itemId: `agenda:${crypto.randomUUID()}`, position: items.length + 1, title: agendaTitle.trim(), description: null }]);
    setAgendaTitle("");
  };

  const create = async () => {
    if (!title.trim() || !startsAt) return;
    setBusy(true);
    setError(null);
    const payload: UniversityEventRequest = {
      slug: title.trim().toLowerCase().replace(/[^a-z0-9а-яё]+/gi, "-").replace(/^-|-$/g, ""),
      title: title.trim(),
      kind,
      format,
      startsAt: new Date(startsAt).toISOString(),
      endsAt: endsAt ? new Date(endsAt).toISOString() : null,
      description: description.trim() || null,
      registrationUrl: registrationUrl.trim() || null,
      venueId: venueId.trim() || null,
      locationLabel: locationLabel.trim() || null,
      locationAddress: locationAddress.trim() || null,
      onlineUrl: null,
      audienceMode,
      unitIds: audienceMode === "selected_units" ? csv(unitIds) : [],
      programIds: audienceMode === "selected_programs" ? csv(programIds) : [],
      categoryIds: csv(categoryIds),
      agenda: agenda.map((item) => ({ ...item })),
    };
    try {
      await createUniversityEvent(universityId, payload);
      setTitle(""); setDescription(""); setStartsAt(""); setEndsAt(""); setUnitIds(""); setProgramIds(""); setCategoryIds(""); setRegistrationUrl(""); setLocationLabel(""); setLocationAddress(""); setVenueId(""); setAgenda([]);
      await load();
    } catch { setError("Не удалось сохранить событие. Проверьте время, связи и права редактора."); }
    finally { setBusy(false); }
  };

  const publish = async (event: UniversityEvent) => {
    if (event.revision === undefined || !window.confirm(`Опубликовать «${event.title}»? Оно станет видно пользователям ${event.audienceMode === "all_university" ? "всего университета" : "в выбранном охвате"}.`)) return;
    setBusy(true);
    try { await publishUniversityEvent(universityId, event.eventId, event.revision); await load(); }
    catch { setError("Событие уже изменилось или не прошло проверку публикации. Обновите список."); }
    finally { setBusy(false); }
  };

  if (loading) return <Loading label="Загружаем события вуза…" />;
  return (
    <div className="space-y-6" data-testid="university-event-editor">
      {error && <ErrorState title="Операция не выполнена" message={error} onRetry={() => void load()} />}
      {canEdit && <Card>
        <CardHeader><SectionTitle>Создать мероприятие</SectionTitle><p className="text-sm text-muted-foreground">День открытых дверей — обычный тип события. Добавьте план и явно выберите охват.</p></CardHeader>
        <CardContent className="grid gap-3 md:grid-cols-2">
          <Input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Название мероприятия" aria-label="Название мероприятия" />
          <select className={fieldClass} value={kind} onChange={(event) => setKind(event.target.value as EventKind)} aria-label="Тип мероприятия"><option value="open_day">День открытых дверей</option><option value="lecture">Лекция</option><option value="competition">Конкурс</option><option value="career">Карьерное событие</option><option value="additional_education">Дополнительное образование</option><option value="other">Другое</option></select>
          <select className={fieldClass} value={format} onChange={(event) => setFormat(event.target.value as EventFormat)} aria-label="Формат мероприятия"><option value="offline">Очно</option><option value="online">Онлайн</option><option value="hybrid">Гибрид</option></select>
          <select className={fieldClass} value={audienceMode} onChange={(event) => setAudienceMode(event.target.value as UniversityAudienceMode)} aria-label="Охват мероприятия"><option value="all_university">Весь вуз</option><option value="selected_units">Выбранные факультеты и кафедры</option><option value="selected_programs">Выбранные программы</option><option value="unaffiliated">Без привязки</option></select>
          <Input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} aria-label="Начало мероприятия" />
          <Input type="datetime-local" value={endsAt} onChange={(event) => setEndsAt(event.target.value)} aria-label="Окончание мероприятия" />
          <Input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Описание и план в свободной форме" aria-label="Описание мероприятия" className="md:col-span-2" />
          <Input value={locationLabel} onChange={(event) => setLocationLabel(event.target.value)} placeholder="Место: главный корпус" aria-label="Место мероприятия" />
          <Input value={locationAddress} onChange={(event) => setLocationAddress(event.target.value)} placeholder="Адрес" aria-label="Адрес мероприятия" />
          <Input value={venueId} onChange={(event) => setVenueId(event.target.value)} placeholder="ID существующей площадки (необязательно)" aria-label="Площадка мероприятия" />
          <Input value={registrationUrl} onChange={(event) => setRegistrationUrl(event.target.value)} placeholder="Ссылка на регистрацию" aria-label="Ссылка на регистрацию" />
          {audienceMode === "selected_units" && <Input value={unitIds} onChange={(event) => setUnitIds(event.target.value)} placeholder="ID подразделений через запятую" aria-label="Подразделения мероприятия" className="md:col-span-2" />}
          {audienceMode === "selected_programs" && <Input value={programIds} onChange={(event) => setProgramIds(event.target.value)} placeholder="ID программ через запятую" aria-label="Программы мероприятия" className="md:col-span-2" />}
          <Input value={categoryIds} onChange={(event) => setCategoryIds(event.target.value)} placeholder="ID категорий через запятую (необязательно)" aria-label="Категории мероприятия" className="md:col-span-2" />
          <div className="rounded-lg border border-border/70 p-3 md:col-span-2"><p className="mb-2 text-sm font-medium">План мероприятия</p><div className="flex gap-2"><Input value={agendaTitle} onChange={(event) => setAgendaTitle(event.target.value)} placeholder="Например, встреча с кафедрой" aria-label="Пункт плана" /><Button type="button" variant="outline" onClick={addAgendaItem}>Добавить пункт</Button></div>{agenda.length > 0 && <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm">{agenda.map((item) => <li key={item.itemId}>{item.title}</li>)}</ol>}</div>
          <Button onClick={() => void create()} disabled={busy || !title.trim() || !startsAt} className="gap-1 md:col-span-2"><CalendarPlus className="h-4 w-4" /> Сохранить черновик</Button>
        </CardContent>
      </Card>}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-3"><SectionTitle hint={`${events.length}`}>Афиша и черновики</SectionTitle><div className="flex items-center gap-2"><select className={fieldClass} value={status} onChange={(event) => setStatus(event.target.value as UniversityEventStatus | "all")} aria-label="Фильтр статуса"><option value="all">Все статусы</option><option value="draft">Черновики</option><option value="published">Опубликованные</option><option value="archived">Архив</option></select><Button variant="outline" size="icon" onClick={() => void load()} aria-label="Обновить события"><RefreshCw className="h-4 w-4" /></Button></div></CardHeader>
        <CardContent>{events.length === 0 ? <EmptyState title="Событий пока нет" message="Создайте первое мероприятие и добавьте пункты его программы." /> : <div className="space-y-3">{events.map((event) => <div key={event.eventId} className="flex flex-col gap-3 rounded-xl border border-border/70 p-4 md:flex-row md:items-center md:justify-between"><div><div className="flex flex-wrap items-center gap-2"><h3 className="font-serif text-lg font-semibold">{event.title}</h3><Tag tone={event.status === "published" ? "primary" : "muted"}>{event.status}</Tag></div><p className="text-sm text-muted-foreground">{new Date(event.startsAt).toLocaleString("ru-RU")} · {event.audienceMode === "all_university" ? "весь вуз" : event.audienceMode === "unaffiliated" ? "без привязки" : "выбранный охват"}</p><p className="mt-1 text-xs text-muted-foreground">{event.agenda.length} пунктов плана</p></div>{canEdit && event.status === "draft" && <Button variant="outline" onClick={() => void publish(event)} disabled={busy} className="gap-1"><Check className="h-4 w-4" /> Опубликовать</Button>}{!canEdit && <span className="inline-flex items-center gap-1 text-sm text-muted-foreground"><Eye className="h-4 w-4" /> Только просмотр</span>}</div>)}</div>}</CardContent>
      </Card>
    </div>
  );
}
