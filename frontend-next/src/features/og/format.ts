export function text(value: unknown, fallback = "нет данных"): string {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

export function integer(value: unknown): string {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("ru-RU").format(number) : "нет данных";
}

export function percent(value: unknown): string {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? `${Math.round(number * 100)}%` : "нет данных";
}

export function statusLabel(value: unknown): string {
  const labels: Record<string, string> = {
    realistic: "реалистично",
    borderline: "погранично",
    unlikely: "малореалистично",
    insufficient_data: "недостаточно данных",
  };
  return labels[String(value)] ?? "нет данных";
}
