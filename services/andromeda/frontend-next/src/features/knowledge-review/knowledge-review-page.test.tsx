import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ReviewDetails } from "./knowledge-review-page";
import type { KnowledgeReviewPolicyPreview, KnowledgeReviewPreviewContext, KnowledgeReviewQueue } from "@/lib/api";

const policyItem = {
  target: {
    kind: "policy_rule",
    objectId: "policy-rule:fourth-exam",
    revision: 2,
    revisionHash: "a".repeat(64),
  },
  reviewState: "pending",
  createdAt: "2027-12-15T12:00:00Z",
  title: "admission-benefit:fourth-exam",
  assertionText: null,
  extractionMethod: null,
  extractor: null,
  confidence: null,
  claimedStage: null,
  changeEventKind: null,
  linkedClaimIds: [],
  relatedAssertions: [],
  policyLifecycle: "proposal",
  policyAuthority: "regulator_normative",
  policyScope: "federal",
  domainRuleId: "admission-benefit:fourth-exam",
  canonicalSummary: "Previous exact policy revision: 1.",
  effectiveFrom: "2028-09-01T00:00:00Z",
  evidence: [{
    sourceId: "source:ministry",
    sourceObservationId: "source-observation:" + "b".repeat(32),
    snapshotSha256: "c".repeat(64),
    sourceName: "Минобрнауки",
    reliabilityTier: "official_issuer",
    sourceUrl: "https://example.gov.ru/order.pdf",
    page: 4,
    inferred: false,
  }],
  diff: [],
  impactStatus: "unavailable",
  impactReason: "policy_review_preview_endpoint_not_composed",
  currentTraceId: null,
  candidateTraceId: null,
  actionHistory: [],
  conflicts: [],
  conflictsTruncated: false,
} as KnowledgeReviewQueue["items"][number];

describe("knowledge review details", () => {
  it("keeps source reliability and policy lifecycle separate and requires an exact preview", () => {
    const html = renderToStaticMarkup(
      <ReviewDetails
        item={policyItem}
        reason=""
        onReasonChange={() => undefined}
        relatedTargetKey=""
        onRelatedTargetChange={() => undefined}
        duplicateCandidates={[]}
        submitting={false}
        onDecide={() => undefined}
      />,
    );

    expect(html).toContain("Официальная публикация регулятора");
    expect(html).toContain("Предложение");
    expect(html).toContain("Гипотетическая проверка policy-кандидата");
    expect(html).not.toContain("Подтвердить утверждение источника");
    expect(html).toContain("Построить current vs candidate preview");
    expect(html).not.toContain("Подтвердить эту policy revision");
  });

  it("requires an audit reason before allowing a source assertion decision", () => {
    const claimItem = {
      ...policyItem,
      target: { ...policyItem.target, kind: "claim", objectId: "claim:" + "d".repeat(64) },
      reviewState: "needs_review",
      title: "admission.minimum_ege_score",
      policyLifecycle: null,
      policyScope: null,
      proposition: {
        predicate: "admission.minimum_ege_score",
        subject_kind: "university",
        subject_id: null,
        value: { kind: "decimal", value: "70" },
        unit: "points",
      },
      impactStatus: "not_required",
      impactReason: null,
    } as KnowledgeReviewQueue["items"][number];
    const html = renderToStaticMarkup(
      <ReviewDetails
        item={claimItem}
        reason=""
        onReasonChange={() => undefined}
        relatedTargetKey=""
        onRelatedTargetChange={() => undefined}
        duplicateCandidates={[]}
        submitting={false}
        onDecide={() => undefined}
      />,
    );

    expect(html).toContain("Причина решения");
    expect(html).toContain("disabled=\"\"");
    expect(html).toContain("Сохранить как новую review revision");
    expect(html).toContain("Проверить и разрешить identity");
  });

  it("shows exact traces and permits approval only for a complete resolved preview", () => {
    const preview = {
      approval_state: "pending",
      preview_id: "policy-review-preview:" + "e".repeat(64),
      approved_snapshot_hash: "f".repeat(64),
      current_trace: { status: "resolved" },
      candidate_trace: { status: "resolved" },
      effective_diff: { changes: [] },
      impact: {
        status: "complete",
        actionability: "informational",
        missing_input_codes: [],
        affected_objects: [],
        domain_results: [],
        evidence: [],
        dependency_cycles: [],
      },
    } as unknown as KnowledgeReviewPolicyPreview;
    const previewContext = {} as KnowledgeReviewPreviewContext;
    const html = renderToStaticMarkup(
      <ReviewDetails
        item={policyItem}
        reason="Reviewed exact evidence and scope."
        onReasonChange={() => undefined}
        relatedTargetKey=""
        onRelatedTargetChange={() => undefined}
        duplicateCandidates={[]}
        submitting={false}
        onDecide={() => undefined}
        policyPreview={preview}
        policyPreviewContext={previewContext}
      />,
    );

    expect(html).toContain("Current ResolutionTrace");
    expect(html).toContain("Candidate ResolutionTrace");
    expect(html).toContain("domain-owner results");
    expect(html).toMatch(/<button(?![^>]*\sdisabled="")[^>]*>Подтвердить эту policy revision<\/button>/);
  });
});
