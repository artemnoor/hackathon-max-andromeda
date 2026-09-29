import { describe, expect, it } from "vitest";
import { applyDecisionMutation } from "./decision-context";
import { normalizeDecisionSuggestions, type DecisionContextData, type DecisionSuggestionsData } from "@/lib/types";

const explicitContext = (overrides: Partial<DecisionContextData["state"]["choice"]> = {}): DecisionContextData => ({
  decisionId: "decision:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  state: {
    version: 1,
    admissionConstraints: null,
    choice: {
      consideredProgramIds: [],
      shortlistEntries: [],
      excludedProgramIds: [],
      ...overrides,
    },
    explicitPriorities: [],
    revision: 4,
    createdAt: "2026-09-17T10:00:00Z",
    updatedAt: "2026-09-17T10:00:00Z",
  },
  preferences: null,
  profileRevision: null,
  missingData: ["admission_constraints"],
  metadata: {
    decisionId: "decision:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    revision: 4,
    status: "active",
    createdAt: "2026-09-17T10:00:00Z",
    updatedAt: "2026-09-17T10:00:00Z",
    profileRevision: null,
  },
});
describe("DecisionContext frontend state boundary", () => {
  it("takes explicit shortlist state only from the server mutation envelope", () => {
    const activeEntry = {
      programId: "program:01",
      role: "primary",
      state: "active",
      origin: "user",
      revision: 4,
      createdAt: "2026-09-17T10:00:00Z",
      updatedAt: "2026-09-17T10:00:00Z",
      removedAt: null,
    };
    const removedEntry = { ...activeEntry, programId: "program:02", state: "removed", removedAt: "2026-09-17T10:01:00Z" };
    const next = applyDecisionMutation({
      decisionId: "decision:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      context: explicitContext({ shortlistEntries: [activeEntry, removedEntry] }),
      changed: true,
    });

    expect(next.state.choice.shortlistEntries).toEqual([activeEntry, removedEntry]);
    expect(next.state.choice.shortlistEntries.find((entry) => entry.programId === "program:02")?.state).toBe("removed");
  });

  it("keeps unknown derived values as null while refreshing suggestions", () => {
    const data = {
      decisionId: "decision:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      contextRevision: 4,
      dataCompleteness: "partial",
      activeShortlist: [],
      primaryCandidates: [],
      alternativeCandidates: [],
      ineligibleCandidates: [{
        programId: "program:03",
        programCode: "03.00.00-01",
        programName: "Программа",
        partition: "insufficient_data",
        admissionStatus: null,
        admissionRisk: "unknown",
        admissionFit: null,
        contentFit: null,
        constraintOutcomes: [],
        reasons: {
          whyIncluded: [],
          whyMayNotFit: [],
          admissionRisk: ["Недостаточно данных"],
          contentDifferences: [],
          missingData: ["study_plan"],
        },
        sourceGaps: ["study_plan"],
        sourceHashes: [],
        provenance: [],
        sourceGapDetails: [],
      }],
      insufficientDataCandidates: [],
      suggestions: [],
      refinementQuestion: null,
      sourceGaps: ["study_plan"],
      missingData: ["preferences"],
    } satisfies DecisionSuggestionsData;

    const normalized = normalizeDecisionSuggestions(data);
    expect(normalized.ineligibleCandidates[0]?.contentFit).toBeNull();
    expect(normalized.ineligibleCandidates[0]?.admissionFit).toBeNull();
    expect(normalized.sourceGaps).toEqual(["study_plan"]);
  });
});
