export const AREA_COLORS: Record<string, string> = {
  mathematics_statistics: "#c2410c",
  computer_science_data: "#0f766e",
  physics_astronomy: "#2563eb",
  chemistry_materials: "#a16207",
  biology_biotechnology: "#16a34a",
  earth_environment: "#0891b2",
  engineering_technology: "#7c3aed",
  architecture_construction: "#be185d",
  agriculture_veterinary: "#65a30d",
  medicine_health: "#dc2626",
  psychology_cognitive: "#db2777",
  society_social_sciences: "#0369a1",
  economics_finance: "#92400e",
  business_management: "#9333ea",
  law_policy_public_administration: "#b91c1c",
  languages_linguistics_literature: "#0e7490",
  history_philosophy_humanities: "#57534e",
  art_design_media: "#e11d48",
  education_pedagogy: "#4f46e5",
  sport_tourism_hospitality: "#ea580c",
  safety_defense_transport: "#334155",
  universal_interdisciplinary: "#64748b",
};

const FALLBACK_AREA_COLORS = ["#7c3aed", "#0f766e", "#c2410c", "#2563eb", "#be185d"];

export function areaColor(code: string): string {
  const explicitColor = AREA_COLORS[code];
  if (explicitColor) return explicitColor;
  let hash = 0;
  for (const character of code) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return FALLBACK_AREA_COLORS[hash % FALLBACK_AREA_COLORS.length] ?? "#64748b";
}
