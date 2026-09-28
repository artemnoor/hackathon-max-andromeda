"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, MapPin, CalendarDays, ExternalLink, Building2 } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { PageHeader, Loading, ErrorState, Tag, SectionTitle, ProvenanceChip } from "@/components/shared";
import { getEvent, getCampusPoint, getCampusPointEvents, getUniversityEvent } from "@/lib/api";
import { eventKindLabel, eventFormatLabel } from "@/lib/labels";
import { formatDateTime } from "@/lib/format";
import type { EventItem, CampusPoint, UniversityEvent } from "@/lib/types";
import type { Route } from "@/lib/router";
import { ProgramShortlistActions } from "@/features/decision/program-shortlist-actions";

export function EventPage({ id, origin = "source", universityId, navigate }: { id: string; origin?: "source" | "university"; universityId?: string; navigate: (route: Route) => void }) {
  const [event, setEvent] = useState<EventItem | null>(null);
  const [universityEvent, setUniversityEvent] = useState<UniversityEvent | null>(null);
  const [point, setPoint] = useState<CampusPoint | null>(null);
  const [pointEvents, setPointEvents] = useState<EventItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    const request = origin === "university" && universityId
      ? getUniversityEvent(universityId, id).then((ev) => { if (active) setUniversityEvent(ev); return null; })
      : getEvent(id).then(({ event: ev }) => { if (active) setEvent(ev); return ev; });
    request
      .then(async (ev) => {
        if (!ev) return;
        if (!active) return;
        setEvent(ev);
        if (ev.venue?.id) {
          const [p, pe] = await Promise.all([
            getCampusPoint(ev.venue.id),
            getCampusPointEvents(ev.venue.id),
          ]);
          if (!active) return;
          setPoint(p.point);
          setPointEvents(pe.items.filter((e) => e.id !== ev.id));
        }
      })
      .catch(() => active && setError("Событие не найдено."))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [id, origin, universityId]);

  if (loading) return <Loading label="Загружаем событие…" />;
  if (error || (!event && !universityEvent)) return <ErrorState title="Событие недоступно" message={error ?? undefined} />;
  if (universityEvent) return <UniversityEventDetail event={universityEvent} navigate={navigate} />;
  if (!event) return <ErrorState title="Событие недоступно" />;

  return (
    <div>
      <button onClick={() => navigate({ view: "events" })} className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground transition hover:text-primary">
        <ArrowLeft className="h-4 w-4" /> Назад к событиям
      </button>

      <PageHeader
        eyebrow={`${eventKindLabel(event.kind)} · ${eventFormatLabel(event.format)}`}
        title={event.title}
        description={event.description ?? undefined}
        actions={
          event.registrationUrl && (
            <Button asChild className="gap-1 bg-primary text-primary-foreground hover:bg-primary/90">
              <a href={event.registrationUrl} target="_blank" rel="noopener noreferrer">
                Зарегистрироваться <ExternalLink className="h-4 w-4" />
              </a>
            </Button>
          )
        }
      />

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardContent className="space-y-4 p-5">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-border/60 bg-card p-3">
                <p className="flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <CalendarDays className="h-3.5 w-3.5" /> Начало
                </p>
                <p className="mt-1 font-serif text-lg font-semibold">{formatDateTime(event.startsAt)}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-card p-3">
                <p className="flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  <CalendarDays className="h-3.5 w-3.5" /> Окончание
                </p>
                <p className="mt-1 font-serif text-lg font-semibold">{formatDateTime(event.endsAt)}</p>
              </div>
            </div>
            {event.programIds.length > 0 && (
              <div>
                <SectionTitle>Связанные программы</SectionTitle>
                <div className="flex flex-wrap gap-2">
                  {event.programIds.map((pid) => (
                    <div key={pid} className="rounded-lg border border-border/60 p-2">
                      <Button variant="outline" size="sm" onClick={() => navigate({ view: "program", id: pid })}>
                        {pid}
                      </Button>
                      <ProgramShortlistActions programId={pid} compact />
                    </div>
                  ))}
                </div>
              </div>
            )}
            {event.programIds.length === 0 && (
              <p data-testid="event-source-gap" className="text-sm text-muted-foreground">
                Официальный источник не указал связь этого события с образовательной программой.
              </p>
            )}
            <ProvenanceChip prov={event.provenance[0]} />
          </CardContent>
        </Card>

        <div className="space-y-4">
          {point ? (
            <Card>
              <CardHeader className="pb-3">
                <SectionTitle>Место проведения</SectionTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <p className="flex items-start gap-2 font-serif text-lg font-semibold">
                  <MapPin className="mt-1 h-4 w-4 text-primary" /> {point.name}
                </p>
                <p className="text-sm text-muted-foreground">{point.address}</p>
                <div className="flex flex-wrap gap-1.5 pt-1">
                  <Tag tone="muted"><Building2 className="mr-1 inline h-3 w-3" />{point.pointType}</Tag>
                  {point.latitude && point.longitude && (
                    <Tag tone="muted">{point.latitude.toFixed(4)}, {point.longitude.toFixed(4)}</Tag>
                  )}
                </div>
              </CardContent>
            </Card>
          ) : (
            <Card className="border-dashed">
              <CardContent className="p-5 text-sm text-muted-foreground">
                Онлайн-событие без физической площадки.
              </CardContent>
            </Card>
          )}

          {pointEvents.length > 0 && (
            <Card>
              <CardHeader className="pb-3"><SectionTitle hint={`${pointEvents.length}`}>Другие события здесь</SectionTitle></CardHeader>
              <CardContent className="space-y-2">
                {pointEvents.map((e) => (
                  <button key={e.id} onClick={() => navigate({ view: "event", id: e.id })} className="block w-full rounded-lg border border-border/60 bg-card p-3 text-left transition hover:border-primary/40">
                    <p className="text-sm font-medium">{e.title}</p>
                    <p className="text-xs text-muted-foreground">{formatDateTime(e.startsAt)}</p>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function UniversityEventDetail({ event, navigate }: { event: UniversityEvent; navigate: (route: Route) => void }) {
  return <div data-testid="university-event-detail">
    <button onClick={() => navigate({ view: "events", id: event.universityId })} className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground transition hover:text-primary"><ArrowLeft className="h-4 w-4" /> Назад к афише</button>
    <PageHeader eyebrow={`${event.kind === "open_day" ? "День открытых дверей" : event.kind} · От вуза`} title={event.title} description={event.description ?? undefined} actions={event.registrationUrl ? <Button asChild className="gap-1 bg-primary text-primary-foreground hover:bg-primary/90"><a href={event.registrationUrl} target="_blank" rel="noopener noreferrer">Зарегистрироваться <ExternalLink className="h-4 w-4" /></a></Button> : undefined} />
    <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
      <Card><CardContent className="space-y-5 p-5"><div className="grid grid-cols-2 gap-3"><div className="rounded-xl border border-border/60 p-3"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Начало</p><p className="mt-1 font-serif text-lg font-semibold">{formatDateTime(event.startsAt)}</p></div><div className="rounded-xl border border-border/60 p-3"><p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Окончание</p><p className="mt-1 font-serif text-lg font-semibold">{formatDateTime(event.endsAt)}</p></div></div><div><SectionTitle hint={`${event.agenda.length} пунктов`}>План мероприятия</SectionTitle>{event.agenda.length === 0 ? <p className="text-sm text-muted-foreground">План пока не опубликован.</p> : <ol className="space-y-3">{event.agenda.map((item) => <li key={item.itemId} className="rounded-lg border border-border/70 p-3"><div className="flex gap-3"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-primary/10 text-sm font-semibold text-primary">{item.position}</span><div><p className="font-medium">{item.title}</p>{item.description && <p className="mt-1 text-sm text-muted-foreground">{item.description}</p>}<p className="mt-1 text-xs text-muted-foreground">{item.startsAt ? formatDateTime(item.startsAt) : "Время уточняется"}{item.locationLabel ? ` · ${item.locationLabel}` : ""}{item.speakerLabel ? ` · ${item.speakerLabel}` : ""}</p></div></div></li>)}</ol>}</div></CardContent></Card>
      <div className="space-y-4"><Card><CardHeader className="pb-3"><SectionTitle>Для кого</SectionTitle></CardHeader><CardContent className="space-y-3"><Tag tone="primary">{event.audienceMode === "all_university" ? "Для всего вуза" : event.audienceMode === "unaffiliated" ? "Без привязки" : "Для выбранных направлений"}</Tag><div className="flex flex-wrap gap-1.5">{event.units.map((item) => <Tag key={`unit:${item.id}`} tone="muted">{item.label}</Tag>)}{event.programs.map((item) => <Tag key={`program:${item.id}`} tone="muted">{item.label}</Tag>)}{event.categories.map((item) => <Tag key={`category:${item.id}`} tone="muted">{item.label}</Tag>)}{event.units.length + event.programs.length + event.categories.length === 0 && <p className="text-sm text-muted-foreground">Без конкретной факультетской или программной связи.</p>}</div></CardContent></Card><Card className="border-dashed"><CardContent className="p-5 text-sm text-muted-foreground">Редакционное событие опубликовано непосредственно вузом. Это не источниковая запись и не содержит искусственной атрибуции.</CardContent></Card></div>
    </div>
  </div>;
}
