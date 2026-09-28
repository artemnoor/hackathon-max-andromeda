import type { UniversityAdminRole } from "@/lib/types";

export function canEditUniversity(role: UniversityAdminRole): boolean {
  return role === "owner" || role === "editor";
}

export function canManageUniversityMembers(role: UniversityAdminRole): boolean {
  return role === "owner";
}

export function needsExplicitUniversityScope(membershipCount: number, selectedMembershipId: string): boolean {
  return membershipCount > 1 && selectedMembershipId.length === 0;
}
