import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { CompareSummary } from "./compare-summary";
import type { ComparisonSummaryResponse } from "@/lib/types";

const summary = {
  programs: [
    {
      program: { id: "program:09.03.01-02", directionId: "direction:09.03.01", code: "09.03.01-02", name: "Информатика", educationYear: 2026, studyPlanUrl: "https://bmstu.ru/plan-a.pdf", sourceUrl: "https://bmstu.ru/a", provenance: [], sourceGaps: [] },
      totals: { hours: 3200, credits: "240.00" },
      areaBreakdown: [],
      sourceGaps: [],
    },
    {
      program: { id: "program:09.03.01-12", directionId: "direction:09.03.01", code: "09.03.01-12", name: "Системы", educationYear: 2026, studyPlanUrl: "https://bmstu.ru/plan-b.pdf", sourceUrl: "https://bmstu.ru/b", provenance: [], sourceGaps: [] },
      totals: null,
      areaBreakdown: [],
      sourceGaps: [{ code: "curriculum_missing", message: "Учебный план недоступен", explanation: "Учебный план недоступен", impact: "Часы нельзя сопоставить", canContinue: true, suggestedAction: "Проверить позже", programIds: ["program:09.03.01-12"] }],
    },
    {
      program: { id: "program:09.03.01-13", directionId: "direction:09.03.01", code: "09.03.01-13", name: "Данные", educationYear: 2026, studyPlanUrl: "https://bmstu.ru/plan-c.pdf", sourceUrl: "https://bmstu.ru/c", provenance: [], sourceGaps: [] },
      totals: { hours: 3000, credits: "240.00" },
      areaBreakdown: [],
      sourceGaps: [],
    },
  ],
  scope: "all",
  semester: null,
  keyDifferences: [{
    programAId: "program:09.03.01-02",
    programBId: "program:09.03.01-13",
    dimension: "area",
    label: "Компьютерные науки",
    direction: "more_in_a",
    valueA: "0.40",
    valueB: "0.20",
    evidence: [{ kind: "area", key: "computer_science_data" }],
  }],
  tradeoffs: [{
    programId: "program:09.03.01-02",
    pairedProgramId: "program:09.03.01-13",
    advantage: "Больше: Компьютерные науки",
    consideration: "Вторая программа даёт меньший объём",
    evidence: [{ kind: "area", key: "computer_science_data" }],
  }],
  sourceGaps: [{ code: "curriculum_missing", message: "Учебный план недоступен", explanation: "Учебный план недоступен", impact: "Часы нельзя сопоставить", canContinue: true, suggestedAction: "Проверить позже", programIds: ["program:09.03.01-12"] }],
} satisfies ComparisonSummaryResponse;

describe("summary-first comparison", () => {
  it("renders neutral summary and three programs before any raw evidence surface", () => {
    const html = renderToStaticMarkup(<CompareSummary data={summary} navigate={() => undefined} />);
    expect(html.indexOf("Короткий вывод")).toBeGreaterThanOrEqual(0);
    expect(html.indexOf("Ключевые различия")).toBeGreaterThan(html.indexOf("Короткий вывод"));
    expect(html.indexOf("Trade-offs")).toBeGreaterThan(html.indexOf("Ключевые различия"));
    expect(html).toContain("09.03.01-13");
    expect(html).toContain("Учебный план недоступен");
    expect(html).not.toContain("winner");
    expect(html).not.toContain("overallScore");
  });
});
