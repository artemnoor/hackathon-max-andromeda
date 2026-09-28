// Formatting helpers — decimals arrive as strings; dates as ISO with timezone.

export function formatDecimal(value?: string | number | null, fractionDigits = 1): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: fractionDigits,
  });
}

export function formatInt(value?: number | string | null): string {
  if (value === null || value === undefined) return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString("ru-RU");
}

export function formatPercent(value?: string | number | null, fractionDigits = 0): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return `${(n * 100).toLocaleString("ru-RU", {
    minimumFractionDigits: 0,
    maximumFractionDigits: fractionDigits,
  })}%`;
}

export function formatShare(value?: string | number | null): string {
  return formatPercent(value, 1);
}

export function formatMoney(amount?: string | null, currency = "RUB"): string {
  if (!amount) return "—";
  const n = Number(amount);
  if (Number.isNaN(n)) return amount;
  try {
    return n.toLocaleString("ru-RU", {
      style: "currency",
      currency,
      maximumFractionDigits: 0,
    });
  } catch {
    return `${formatInt(n)} ${currency}`;
  }
}

const MONTHS = [
  "января", "февраля", "марта", "апреля", "мая", "июня",
  "июля", "августа", "сентября", "октября", "ноября", "декабря",
];

export function formatDate(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return `${formatDate(iso)}, ${time}`;
}

export function relativeTime(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = Date.now();
  const diff = d.getTime() - now;
  const abs = Math.abs(diff);
  const day = 86400000;
  const days = Math.round(abs / day);
  const rtf = new Intl.RelativeTimeFormat("ru", { numeric: "auto" });
  if (abs < day) return rtf.format(Math.round(diff / 3600000), "hour");
  if (days < 30) return rtf.format(Math.sign(diff) * days, "day");
  return rtf.format(Math.sign(diff) * Math.round(days / 30), "month");
}

export function fitTone(score: number): "good" | "warn" | "bad" | "muted" {
  if (score >= 75) return "good";
  if (score >= 50) return "warn";
  if (score >= 25) return "bad";
  return "muted";
}
