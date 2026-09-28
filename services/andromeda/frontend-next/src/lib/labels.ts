// Russian labels for API enums and taxonomy.

export const TAXONOMY_LABELS: Record<string, string> = {
  mathematics_statistics: "Математика и статистика",
  computer_science_data: "Компьютерные науки и данные",
  physics_astronomy: "Физика и астрономия",
  chemistry_materials: "Химия и материаловедение",
  biology_biotechnology: "Биология и биотехнологии",
  earth_environment: "Земля, экология и окружающая среда",
  engineering_technology: "Инженерия и технологии",
  architecture_construction: "Архитектура, строительство и урбанистика",
  agriculture_veterinary: "Сельское хозяйство и ветеринария",
  medicine_health: "Медицина и здоровье",
  psychology_cognitive: "Психология и когнитивные науки",
  society_social_sciences: "Общество и социальные науки",
  economics_finance: "Экономика и финансы",
  business_management: "Бизнес, управление и предпринимательство",
  law_policy_public_administration: "Право, политика и государственное управление",
  languages_linguistics_literature: "Языки, лингвистика и литература",
  history_philosophy_humanities: "История, философия и гуманитарные науки",
  art_design_media: "Искусство, дизайн, медиа и коммуникации",
  education_pedagogy: "Образование и педагогика",
  sport_tourism_hospitality: "Спорт, туризм и индустрия гостеприимства",
  safety_defense_transport: "Безопасность, оборона и транспортные системы",
  universal_interdisciplinary: "Универсальные и междисциплинарные дисциплины",
};

export function taxonomyLabel(code: string): string {
  return TAXONOMY_LABELS[code] ?? code;
}

export const COMPETITION_LABELS: Record<string, string> = {
  general: "Общий конкурс",
  special_quota: "Особая квота",
  separate_quota: "Отдельная квота",
  targeted: "Целевой набор",
  bvi: "Без вступительных испытаний",
  other: "Иной тип конкурса",
};

export function competitionLabel(v?: string | null): string {
  if (!v) return "—";
  return COMPETITION_LABELS[v] ?? v;
}

export const EVENT_KIND_LABELS: Record<string, string> = {
  additional_education: "Доп. образование",
  open_day: "День открытых дверей",
  lecture: "Лекция",
  competition: "Конкурс / олимпиада",
  career: "Карьера",
  other: "Другое",
};

export function eventKindLabel(v?: string | null): string {
  if (!v) return "—";
  return EVENT_KIND_LABELS[v] ?? v;
}

export const EVENT_FORMAT_LABELS: Record<string, string> = {
  offline: "Офлайн",
  online: "Онлайн",
  hybrid: "Гибрид",
};

export function eventFormatLabel(v?: string | null): string {
  if (!v) return "—";
  return EVENT_FORMAT_LABELS[v] ?? v;
}

export const STUDY_FORM_LABELS: Record<string, string> = {
  full_time: "Очная",
  part_time: "Очно-заочная",
  evening: "Вечерняя",
  online: "Онлайн",
  unknown: "Не указано",
};

export function studyFormLabel(v?: string | null): string {
  if (!v) return "—";
  return STUDY_FORM_LABELS[v] ?? v;
}

export const FUNDING_LABELS: Record<string, string> = {
  budget: "Бюджет",
  paid: "Платное",
  targeted: "Целевой набор",
  contract: "Договор",
  unknown: "Не указано",
};

export function fundingLabel(v?: string | null): string {
  if (!v) return "—";
  return FUNDING_LABELS[v] ?? v;
}

export const SCOPE_LABELS: Record<string, string> = {
  program: "Программа",
  direction: "Направление",
};

export function scopeLabel(v?: string | null): string {
  if (!v) return "—";
  return SCOPE_LABELS[v] ?? v;
}

export const ADMISSION_FIT_LABELS: Record<string, { label: string; tone: string }> = {
  realistic: { label: "Реалистично", tone: "good" },
  borderline: { label: "На грани", tone: "warn" },
  unlikely: { label: "Маловероятно", tone: "bad" },
  insufficient_data: { label: "Недостаточно данных", tone: "muted" },
};

export const ROUTE_STATUS_LABELS: Record<string, string> = {
  ready: "Материалы доступны",
  no_recommendations: "Материалы появятся позже",
  no_events: "Ближайших событий нет",
};

export const INGESTION_STATUS_LABELS: Record<string, string> = {
  running: "Выполняется",
  completed: "Завершён",
  failed: "Ошибка",
};

export const STEP_KIND_LABELS: Record<string, string> = {
  explore_program: "Изучить программу",
  compare_programs: "Сравнить программы",
  attend_event: "Посетить событие",
};

export const DIRECTION_LABELS: Record<string, string> = {
  "09.03.01": "Информатика и вычислительная техника",
  "09.03.04": "Программная инженерия",
  "01.03.02": "Прикладная математика и информатика",
  "15.03.04": "Автоматизация технологических процессов",
  "12.03.05": "Оптотехника",
  "11.03.03": "Конструирование и технология электронных средств",
  "38.03.01": "Экономика",
  "20.03.01": "Техносферная безопасность",
  "27.03.04": "Управление в технических системах",
  "10.05.05": "Безопасность информационных технологий",
};

export function directionLabel(code: string): string {
  return DIRECTION_LABELS[code] ?? code;
}
