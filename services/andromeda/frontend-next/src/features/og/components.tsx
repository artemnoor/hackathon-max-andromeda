import type { ReactNode } from "react";
import { areaColor } from "@/lib/area-colors";
import { PALETTES, type OgPalette, type OgTheme } from "./theme";
import { integer, percent, statusLabel, text } from "./format";

export function OgFrame({ theme, eyebrow, title, children, width = 1200 }: { theme: OgTheme; eyebrow: string; title: string; children: ReactNode; width?: number }) {
  const palette = PALETTES[theme];
  return (
    <div style={{ width, minHeight: 630, display: "flex", flexDirection: "column", padding: "56px 64px", background: palette.background, color: palette.foreground, fontFamily: "Noto Sans", gap: 26 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <div style={{ display: "flex", color: palette.secondary, fontSize: 22, fontWeight: 700, letterSpacing: 2 }}>{eyebrow.toUpperCase()}</div>
          <div style={{ display: "flex", fontSize: 48, lineHeight: 1.05, fontWeight: 700, maxWidth: 950 }}>{title}</div>
        </div>
        <div style={{ display: "flex", color: palette.primary, fontSize: 26, fontWeight: 700 }}>ANDROMEDA</div>
      </div>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 18 }}>{children}</div>
      <div style={{ borderTop: `1px solid ${palette.border}`, paddingTop: 14, color: palette.muted, fontSize: 17 }}>Данные из официальных источников · система поддержки выбора, не гарантия поступления</div>
    </div>
  );
}

export function ProgramCard({ program, palette, risk }: { program: Record<string, unknown>; palette: OgPalette; risk?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", padding: 28, border: `1px solid ${palette.border}`, borderRadius: 18, background: palette.card, gap: 11 }}>
      <div style={{ display: "flex", fontSize: 18, color: palette.muted }}>{text(program.code)} · {text(program.directionId ?? program.direction_id)}</div>
      <div style={{ display: "flex", fontSize: 30, fontWeight: 700 }}>{text(program.name)}</div>
      <div style={{ display: "flex", gap: 24, fontSize: 20 }}><span>{text(program.universityName, "Поддерживаемый университет")}</span><span style={{ color: palette.secondary }}>{risk ? statusLabel(risk) : "источник найден"}</span></div>
    </div>
  );
}

export function Legend({ rows, palette }: { rows: { label: string; color: string }[]; palette: OgPalette }) {
  return <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 20px", color: palette.muted, fontSize: 16 }}>{rows.map((row) => <div key={row.label} style={{ display: "flex", alignItems: "center", gap: 7 }}><span style={{ width: 12, height: 12, borderRadius: 6, background: row.color }} />{row.label}</div>)}</div>;
}

export function AreaBars({ breakdown, palette }: { breakdown: unknown; palette: OgPalette }) {
  const rows = Array.isArray(breakdown) ? breakdown.slice(0, 8) as Record<string, unknown>[] : [];
  return <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>{rows.map((row, index) => {
    const code = text(row.code ?? row.area, `area-${index}`);
    const share = Number(row.share ?? 0);
    const width = Number.isFinite(share) ? Math.max(3, Math.min(100, share * 100)) : 3;
    return <div key={code} style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 17 }}><div style={{ display: "flex", width: 205, overflow: "hidden", whiteSpace: "nowrap" }}>{text(row.name, code)}</div><div style={{ height: 16, width: 420, borderRadius: 8, background: palette.border, display: "flex" }}><div style={{ width: `${width}%`, borderRadius: 8, background: areaColor(code) }} /></div><div style={{ display: "flex", color: palette.muted }}>{percent(share)}</div></div>;
  })}</div>;
}

export function ComparisonMatrix({ summary, palette }: { summary: Record<string, unknown>; palette: OgPalette }) {
  const programs = Array.isArray(summary.programs) ? summary.programs as Record<string, unknown>[] : [];
  const headers = programs.map((item) => (item.program ?? {}) as Record<string, unknown>);
  const rows = [
    ["Код", ...headers.map((program) => text(program.code))],
    ["Часы", ...programs.map((item) => integer((item.totals as Record<string, unknown> | undefined)?.totalHours))],
    ["ЗЕТ", ...programs.map((item) => text((item.totals as Record<string, unknown> | undefined)?.totalCredits))],
  ];
  return <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>{<div style={{ display: "flex", gap: 12 }}>{headers.map((program) => <div key={text(program.id)} style={{ display: "flex", flex: 1, padding: 18, borderRadius: 14, background: palette.card, border: `1px solid ${palette.border}`, fontSize: 24, fontWeight: 700 }}>{text(program.name)}</div>)}</div>}<div style={{ display: "flex", flexDirection: "column", border: `1px solid ${palette.border}`, borderRadius: 14, overflow: "hidden" }}>{rows.map((row, index) => <div key={String(row[0])} style={{ display: "flex", padding: "15px 18px", gap: 12, background: index % 2 ? palette.card : "transparent", fontSize: 20 }}>{row.map((cell, cellIndex) => <div key={`${index}-${cellIndex}`} style={{ display: "flex", flex: cellIndex === 0 ? 0.7 : 1 }}>{text(cell)}</div>)}</div>)}</div></div>;
}

export function SmallList({ items, palette, empty = "нет данных" }: { items: unknown; palette: OgPalette; empty?: string }) {
  const values = Array.isArray(items) ? items.map((item) => text(item)).slice(0, 8) : [];
  return <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>{values.length ? values.map((item) => <div key={item} style={{ display: "flex", fontSize: 19, color: palette.foreground }}>• {item}</div>) : <div style={{ display: "flex", fontSize: 19, color: palette.muted }}>{empty}</div>}</div>;
}

export function AnalyticsMetricTable({ result, metric, palette }: { result: { rows?: unknown[] }; metric: string; palette: OgPalette }) {
  const rows = Array.isArray(result.rows) ? result.rows.slice(0, 3) as Record<string, unknown>[] : [];
  return <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>{rows.map((row) => {
    const values = row.metrics && typeof row.metrics === "object" ? row.metrics as Record<string, unknown> : {};
    const value = values[metric] && typeof values[metric] === "object" ? values[metric] as Record<string, unknown> : {};
    const raw = value.value;
    const display = raw === null || raw === undefined ? "нет данных" : value.unit === "share" ? `${Math.round(Number(raw) * 100)}%` : String(raw);
    return <div key={String(row.entity_id)} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: 22, borderRadius: 16, border: `1px solid ${palette.border}`, background: palette.card }}><div style={{ display: "flex", flexDirection: "column", gap: 6 }}><div style={{ display: "flex", fontSize: 20, fontWeight: 700 }}>{String(row.entity_id)}</div><div style={{ display: "flex", color: palette.muted, fontSize: 16 }}>basis: {String(value.basis ?? "unknown")} · coverage: {String(value.coverage ?? "unknown")}</div></div><div style={{ display: "flex", color: palette.primary, fontSize: 34, fontWeight: 700 }}>{display}</div></div>;
  })}</div>;
}
