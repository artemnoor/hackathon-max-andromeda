"use client";

import { getApiRequestUrl, sendDecisionAnalytics, type DecisionAnalyticsEventRequest } from "./api";
import type { components } from "./generated";

export type DecisionAnalyticsEventType = components["schemas"]["DecisionAnalyticsClientEventType"];
export type DecisionAnalyticsSource = components["schemas"]["DecisionAnalyticsSource"];
export type DecisionAnalyticsAction = components["schemas"]["DecisionAnalyticsAction"];
export type DecisionAnalyticsStatus = components["schemas"]["DecisionAnalyticsStatus"];
export type DecisionAnalyticsRole = components["schemas"]["ShortlistRole"];

/** Only fields permitted in a client-side decision event. */
export type DecisionAnalyticsPayload = {
  source?: DecisionAnalyticsSource;
  action?: DecisionAnalyticsAction;
  status?: DecisionAnalyticsStatus;
  programId?: string;
  programIds?: readonly string[];
  role?: DecisionAnalyticsRole;
  count?: number;
  questionId?: string;
  optionId?: string;
};

export type DecisionAnalyticsTransport = (event: DecisionAnalyticsEventRequest) => Promise<unknown> | unknown;

const CLIENT_EVENT_TYPES: readonly DecisionAnalyticsEventType[] = [
  "decision_session_started",
  "admission_fit_viewed",
  "comparison_started",
  "comparison_completed",
  "preference_question_answered",
  "system_suggestion_shown",
  "shortlist_returned_to",
];
const SOURCES: readonly DecisionAnalyticsSource[] = ["catalog", "program", "admission", "compare", "decision", "suggestion", "proftest", "system"];
const ACTIONS: readonly DecisionAnalyticsAction[] = ["view", "start", "complete", "consider", "add", "remove", "restore", "mark_primary", "mark_alternative", "set_constraints", "answer", "show", "accept", "reject", "return"];
const STATUSES: readonly DecisionAnalyticsStatus[] = ["realistic", "borderline", "unlikely", "insufficient_data", "available", "provided", "cleared", "started", "completed", "unknown"];
const ROLES: readonly DecisionAnalyticsRole[] = ["primary", "alternative"];
// University-scoped IDs are canonical; the legacy unscoped shape remains
// accepted for one compatibility cycle so old clients can still emit safe
// analytics while they are being upgraded.
const PROGRAM_ID_PATTERN = /^program:(?:[a-z0-9][a-z0-9-]{1,31}:)?[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}$/;
const TOKEN_PATTERN = /^[a-z0-9][a-z0-9._:-]{0,127}$/;
const DECISION_ID_PATTERN = /^decision:[0-9a-f]{32}$/;
const emittedKeys = new Set<string>();
let testTransport: DecisionAnalyticsTransport | null = null;

/** Replace the transport in unit/browser tests without touching product flow. */
export function setDecisionAnalyticsTransportForTests(transport: DecisionAnalyticsTransport | null): void {
  testTransport = transport;
}

/** Reset in-memory/session markers between isolated test cases. */
export function resetDecisionAnalyticsForTests(): void {
  emittedKeys.clear();
  testTransport = null;
  if (typeof window !== "undefined") {
    try {
      window.sessionStorage.clear();
    } catch {
      // Storage can be blocked by privacy settings; memory dedupe remains safe.
    }
  }
}

/** Send one allow-listed event without ever making UI behavior await telemetry. */
export function trackDecisionEvent(
  eventType: DecisionAnalyticsEventType,
  payload: DecisionAnalyticsPayload = {},
  options: { dedupeKey?: string } = {},
): void {
  if (!CLIENT_EVENT_TYPES.includes(eventType)) return;
  let safePayload: DecisionAnalyticsEventRequest["payload"] | null;
  try {
    safePayload = sanitizeDecisionAnalyticsPayload(payload);
  } catch {
    return;
  }
  if (safePayload === null) return;
  const key = options.dedupeKey;
  if (key !== undefined) {
    if (!TOKEN_PATTERN.test(key) && !key.startsWith("decision-session:")) return;
    if (emittedKeys.has(key)) return;
    emittedKeys.add(key);
  }
  const event: DecisionAnalyticsEventRequest = {
    eventId: createEventId(),
    eventType,
    payload: safePayload,
  };
  try {
    const result = testTransport ? testTransport(event) : dispatch(event);
    void Promise.resolve(result).catch(() => undefined);
  } catch {
    // Telemetry is best effort and must not reject a product interaction.
  }
}

/** Mark one decision context as opened during this browser session. */
export function trackDecisionSessionStarted(decisionId: string): void {
  if (!DECISION_ID_PATTERN.test(decisionId)) return;
  const marker = `andromeda:decision-session:${decisionId}`;
  if (typeof window !== "undefined") {
    try {
      if (window.sessionStorage.getItem(marker) === "1") return;
      window.sessionStorage.setItem(marker, "1");
    } catch {
      // Fall through to the in-memory key when storage is unavailable.
    }
  }
  trackDecisionEvent("decision_session_started", { source: "decision", action: "start" }, { dedupeKey: `decision-session:${decisionId}` });
}

/** Exposed for tests and for the intentional `Мой выбор` entry boundary. */
export function sanitizeDecisionAnalyticsPayload(payload: DecisionAnalyticsPayload): DecisionAnalyticsEventRequest["payload"] | null {
  const safe: NonNullable<DecisionAnalyticsEventRequest["payload"]> = {};
  if (payload.source !== undefined) {
    if (!SOURCES.includes(payload.source)) return null;
    safe.source = payload.source;
  }
  if (payload.action !== undefined) {
    if (!ACTIONS.includes(payload.action)) return null;
    safe.action = payload.action;
  }
  if (payload.status !== undefined) {
    if (!STATUSES.includes(payload.status)) return null;
    safe.status = payload.status;
  }
  if (payload.role !== undefined) {
    if (!ROLES.includes(payload.role)) return null;
    safe.role = payload.role;
  }
  if (payload.programId !== undefined) {
    if (typeof payload.programId !== "string" || !PROGRAM_ID_PATTERN.test(payload.programId)) return null;
    safe.programId = payload.programId;
  }
  if (payload.programIds !== undefined) {
    if (!Array.isArray(payload.programIds) || payload.programIds.length < 1 || payload.programIds.length > 3) return null;
    if (new Set(payload.programIds).size !== payload.programIds.length || payload.programIds.some((id) => typeof id !== "string" || !PROGRAM_ID_PATTERN.test(id))) return null;
    safe.programIds = [...payload.programIds];
  }
  if (payload.count !== undefined) {
    if (!Number.isInteger(payload.count) || payload.count < 0 || payload.count > 50) return null;
    safe.count = payload.count;
  }
  if (payload.questionId !== undefined) {
    if (typeof payload.questionId !== "string" || !TOKEN_PATTERN.test(payload.questionId)) return null;
    safe.questionId = payload.questionId;
  }
  if (payload.optionId !== undefined) {
    if (typeof payload.optionId !== "string" || !TOKEN_PATTERN.test(payload.optionId)) return null;
    safe.optionId = payload.optionId;
  }
  return safe;
}

function createEventId(): string {
  const uuid = globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`;
  const normalized = uuid.replaceAll("-", "").padEnd(32, "0").slice(0, 32);
  return `decision-event:${normalized}`;
}

function dispatch(event: DecisionAnalyticsEventRequest): Promise<unknown> | void {
  const configuredBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";
  if (configuredBase.startsWith("/") && typeof navigator !== "undefined" && typeof navigator.sendBeacon === "function") {
    const body = new Blob([JSON.stringify(event)], { type: "application/json" });
    if (navigator.sendBeacon(getApiRequestUrl("/decision/analytics"), body)) return;
  }
  return sendDecisionAnalytics(event);
}
