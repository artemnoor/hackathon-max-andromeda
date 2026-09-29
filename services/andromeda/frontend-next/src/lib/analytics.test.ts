import { afterEach, describe, expect, it, vi } from "vitest";
import {
  resetDecisionAnalyticsForTests,
  sanitizeDecisionAnalyticsPayload,
  setDecisionAnalyticsTransportForTests,
  trackDecisionEvent,
} from "./analytics";

const PROGRAM_A = "program:09.03.01-01";
const PROGRAM_B = "program:09.03.01-02";

describe("decision analytics", () => {
  afterEach(() => {
    resetDecisionAnalyticsForTests();
  });

  it("keeps only bounded allowlisted fields and drops sensitive extras", () => {
    const pollutedPayload = {
      source: "catalog" as const,
      action: "view" as const,
      programId: PROGRAM_A,
      count: 2,
      email: "private@example.test",
      score: 290,
      profile: { preferredSubjects: ["math"] },
    } as unknown as Parameters<typeof sanitizeDecisionAnalyticsPayload>[0];

    expect(sanitizeDecisionAnalyticsPayload(pollutedPayload)).toEqual({
      source: "catalog",
      action: "view",
      programId: PROGRAM_A,
      count: 2,
    });
    expect(sanitizeDecisionAnalyticsPayload({ programIds: [PROGRAM_A, PROGRAM_A] })).toBeNull();
    expect(sanitizeDecisionAnalyticsPayload({ programId: "program:private" })).toBeNull();
  });

  it("deduplicates lifecycle events without making callers await telemetry", () => {
    const transport = vi.fn().mockResolvedValue(undefined);
    setDecisionAnalyticsTransportForTests(transport);

    trackDecisionEvent(
      "comparison_started",
      { source: "compare", action: "start", programIds: [PROGRAM_A, PROGRAM_B] },
      { dedupeKey: "comparison-started" },
    );
    trackDecisionEvent(
      "comparison_started",
      { source: "compare", action: "start", programIds: [PROGRAM_A, PROGRAM_B] },
      { dedupeKey: "comparison-started" },
    );

    expect(transport).toHaveBeenCalledTimes(1);
    expect(transport.mock.calls[0][0]).toEqual(expect.objectContaining({
      eventType: "comparison_started",
      payload: { source: "compare", action: "start", programIds: [PROGRAM_A, PROGRAM_B] },
    }));
  });

  it("swallows transport failure so a feature action cannot be rejected", () => {
    setDecisionAnalyticsTransportForTests(() => {
      throw new Error("telemetry is down");
    });

    expect(() => trackDecisionEvent("shortlist_returned_to", { source: "decision", action: "return" })).not.toThrow();
  });
});
