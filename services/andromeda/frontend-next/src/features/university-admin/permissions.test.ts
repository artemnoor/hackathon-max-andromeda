import { describe, expect, it } from "vitest";
import { canEditUniversity, canManageUniversityMembers, needsExplicitUniversityScope } from "./permissions";

describe("university console role boundary", () => {
  it("allows content mutations only to owner and editor", () => {
    expect(canEditUniversity("owner")).toBe(true);
    expect(canEditUniversity("editor")).toBe(true);
    expect(canEditUniversity("viewer")).toBe(false);
  });

  it("keeps membership management owner-only", () => {
    expect(canManageUniversityMembers("owner")).toBe(true);
    expect(canManageUniversityMembers("editor")).toBe(false);
    expect(canManageUniversityMembers("viewer")).toBe(false);
  });

  it("requires an explicit scope when several memberships exist", () => {
    expect(needsExplicitUniversityScope(2, "")).toBe(true);
    expect(needsExplicitUniversityScope(2, "membership:abc")).toBe(false);
    expect(needsExplicitUniversityScope(1, "")).toBe(false);
  });
});
