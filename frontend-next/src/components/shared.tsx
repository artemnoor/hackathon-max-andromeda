"use client";

import { Loader2, AlertTriangle, Inbox, FileText, ExternalLink, Compass } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Provenance } from "@/lib/types";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

export function explainSourceGap(code: string): string {
  const labels: Record<string, string> = {
    curriculum_missing: "Учебный план не опубликован в доступном официальном источнике.",
    study_plan: "Учебный план не опубликован в доступном официальном источнике.",
    tuition_constraint_not_available_in_candidate_source: "Стоимость обучения не сопоставима по доступным официальным данным.",
    location_constraint_not_available_in_candidate_source: "Локация не сопоставима по доступным официальным данным.",
    catalog_empty: "В официальном каталоге сейчас не найдено программ.",
  };
  if (labels[code]) return labels[code];
  if (code.includes("tuition")) return "Стоимость обучения не опубликована или не распознана в официальном источнике.";
  if (code.includes("curriculum") || code.includes("work-plan") || code.includes("study-plan")) return "Содержание учебного плана недоступно в официальном источнике.";
  return "Официальный источник не содержит это поле в текущем срезе.";
}

export function Loading({ label = "Загружаем данные…" }: { label?: string }) {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-3 text-muted-foreground" role="status" aria-live="polite">
      <Loader2 className="h-7 w-7 animate-spin text-primary" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

export function ErrorState({
  title = "Не удалось загрузить",
  message,
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <Card className="border-destructive/30 bg-destructive/5" role="alert" aria-live="assertive">
      <CardContent className="flex flex-col items-start gap-3 p-6">
        <div className="flex items-center gap-2 text-destructive">
          <AlertTriangle className="h-5 w-5" />
          <h3 className="font-serif text-lg font-semibold">{title}</h3>
        </div>
        <p className="text-sm text-muted-foreground">
          {message ?? "Проверьте подключение к API и попробуйте снова."}
        </p>
        {onRetry && (
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Повторить
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export function EmptyState({
  title,
  message,
  action,
}: {
  title: string;
  message?: string;
  action?: React.ReactNode;
}) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
        <div className="grid h-12 w-12 place-items-center rounded-full bg-accent text-accent-foreground">
          <Inbox className="h-6 w-6" />
        </div>
        <h3 className="font-serif text-lg font-semibold">{title}</h3>
        {message && <p className="max-w-md text-sm text-muted-foreground">{message}</p>}
        {action}
      </CardContent>
    </Card>
  );
}

export function ProfileRequired({ onAction }: { onAction?: () => void }) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-3 p-10 text-center">
        <div className="grid h-12 w-12 place-items-center rounded-full bg-accent text-accent-foreground">
          <Compass className="h-6 w-6" />
        </div>
        <h3 className="font-serif text-lg font-semibold">Профиль пока не заполнен</h3>
        <p className="max-w-md text-sm text-muted-foreground">
          Профиль помогает уточнить Content Fit, но не нужен для каталога, сравнения или проверки поступления. Его можно заполнить в любой момент.
        </p>
        {onAction && (
          <Button onClick={onAction} className="bg-primary text-primary-foreground hover:bg-primary/90">
            Уточнить предпочтения
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-8 flex flex-col gap-4 border-b border-border/70 pb-6 md:flex-row md:items-end md:justify-between">
      <div className="space-y-2">
        {eyebrow && (
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-primary">{eyebrow}</p>
        )}
        <h1 className="font-serif text-3xl font-semibold leading-tight text-foreground md:text-4xl">
          {title}
        </h1>
        {description && (
          <p className="max-w-2xl text-sm text-muted-foreground md:text-base">{description}</p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function ScoreBadge({ value, className }: { value: number; className?: string }) {
  const tone =
    value >= 75 ? "bg-emerald-100 text-emerald-800"
    : value >= 50 ? "bg-amber-100 text-amber-800"
    : value >= 25 ? "bg-orange-100 text-orange-800"
    : "bg-stone-100 text-stone-600";
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-sm font-semibold tabular-nums", tone, className)}>
      {value}
    </span>
  );
}

export function Stat({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl border border-border/70 bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="mt-1 font-serif text-2xl font-semibold tabular-nums text-foreground">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export function ProvenanceChip({ prov }: { prov?: Provenance | null }) {
  if (!prov) return null;
  const sourceHref = safeExternalHref(prov.sourceUrl ?? prov.url);
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
      <FileText className="h-3.5 w-3.5" />
      <span className="font-medium">{prov.sourceName ?? prov.sourceKind ?? "Источник"}</span>
      {prov.capturedAt && <span>· снят {formatDate(prov.capturedAt)}</span>}
      {sourceHref && (
        <a
          href={sourceHref}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-primary hover:underline"
        >
          открыть <ExternalLink className="h-3 w-3" />
        </a>
      )}
    </div>
  );
}

export function safeExternalHref(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function Tag({ children, tone = "default" }: { children: React.ReactNode; tone?: "default" | "primary" | "muted" }) {
  const cls =
    tone === "primary" ? "border-primary/30 bg-primary/10 text-primary"
    : tone === "muted" ? "border-border bg-muted text-muted-foreground"
    : "border-border bg-card text-foreground";
  return <Badge variant="outline" className={cn("max-w-full whitespace-normal break-words font-medium", cls)}>{children}</Badge>;
}

export function SectionTitle({ children, hint }: { children: React.ReactNode; hint?: string }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-3">
      <h2 className="font-serif text-xl font-semibold text-foreground">{children}</h2>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}
