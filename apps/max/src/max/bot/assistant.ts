import { AppError, ERROR_CODES } from '../../shared/errors.js';
import type { AppConfig } from '../../shared/config.js';
import type { MaxTransportState, UpdateReservation } from '../../shared/transport-state.js';
import type { AndromedaApiClient, AssistantQueryResponse, ProgramComparisonSummary } from '../client/andromeda-api.js';
import type { MaxUpdate } from './update.js';

export type AssistantInteractionResult = Readonly<{
  result: AssistantQueryResponse;
  restartedSession: boolean;
}>;

export type AssistantInteraction = Readonly<{
  query(update: MaxUpdate, text: string): Promise<AssistantInteractionResult>;
  resetConversation(update: MaxUpdate): Promise<void>;
}>;

export type AssistantApiPort = Pick<AndromedaApiClient, 'queryAssistant'>
  & Partial<Pick<AndromedaApiClient, 'compareSummary'>>;
export type AssistantStatePort = Pick<MaxTransportState,
  'reserveConversationTurn' | 'releaseConversationTurn' | 'getAndromedaMapping'
  | 'saveAndromedaMapping' | 'resetAndromedaQuerySession'>;

// A stale-session retry can make two sequential backend requests.
const CONVERSATION_LEASE_SECONDS = 90;
const PROFILE_COOKIE_PATTERN = /^[A-Za-z0-9_-]{32,256}$/u;
const COMPARISON_PROMPT = /сравн|compare|versus|чем[\s\S]{0,160}отлич|разниц[\s\S]{0,160}между|что\s+общего/iu;

const dependencyError = (operation: string): AppError =>
  new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation });

const requireLease = (reservation: UpdateReservation): string => {
  if (reservation.status === 'reserved') return reservation.leaseToken;
  throw dependencyError(reservation.status === 'busy' ? 'max_conversation_busy' : 'max_conversation_unexpected_state');
};

const comparisonValue = (value: string | null | undefined, dimension: string): string => {
  if (value == null || value === '') return 'нет подтверждённого значения';
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return dimension === 'area'
    ? `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(number * 100)}%`
    : new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(number);
};

const comparisonText = (summary: ProgramComparisonSummary): string => {
  const programLines = summary.programs.map(({ program, totals }) => {
    const workload = totals
      ? `Учебный план: ${new Intl.NumberFormat('ru-RU').format(totals.hours)} ч, ${totals.credits} ЗЕТ.`
      : 'Итоги учебного плана в источнике не рассчитаны.';
    return `${program.name} (${program.code}). ${workload}`;
  });
  const differences = summary.keyDifferences.slice(0, 6).map((item) =>
    `• ${item.label}: ${comparisonValue(item.valueA, item.dimension)} и ${comparisonValue(item.valueB, item.dimension)}.`,
  );
  const gaps = summary.sourceGaps.map((gap) => `• ${gap.message}`);
  return [
    'Сравнение по опубликованным учебным планам Andromeda.',
    ...programLines,
    ...(differences.length ? ['Ключевые различия:', ...differences] : []),
    ...(gaps.length ? ['Ограничения данных:', ...gaps] : []),
  ].join('\n\n');
};

const enrichProgramComparison = async (
  result: AssistantQueryResponse,
  text: string,
  compareSummary: AndromedaApiClient['compareSummary'] | undefined,
): Promise<AssistantQueryResponse> => {
  const programIds = result.query?.scope_ids;
  if (result.state !== 'complete'
    || !result.response
    || result.response.template === 'policy-resolution'
    || !COMPARISON_PROMPT.test(text)
    || !compareSummary
    || !Array.isArray(programIds)
    || programIds.length < 2 || programIds.length > 3
    || !programIds.every((id): id is string => typeof id === 'string' && id.startsWith('program:'))
    || new Set(programIds).size !== programIds.length) return result;

  try {
    const summary = await compareSummary(programIds);
    return {
      ...result,
      response: {
        ...result.response,
        response_type: 'text',
        response_mode: 'deterministic',
        template: 'program-comparison-summary',
        text: comparisonText(summary),
        data: { comparison: summary },
      },
    };
  } catch {
    // Keep the assistant's original result if the comparison endpoint is temporarily unavailable.
    return result;
  }
};

export const createAssistantInteraction = (dependencies: Readonly<{
  api: AssistantApiPort;
  state: AssistantStatePort;
  config: Pick<AppConfig, 'andromedaProfileTtlSeconds' | 'andromedaQuerySessionTtlSeconds'>;
  now?: () => number;
}>): AssistantInteraction => {
  const now = dependencies.now ?? Date.now;

  const saveResult = async (
    userKey: string,
    leaseToken: string,
    profileCookie: string,
    result: AssistantQueryResponse,
    timestamp: number,
  ): Promise<void> => {
    if (!PROFILE_COOKIE_PATTERN.test(profileCookie)) throw dependencyError('max_profile_cookie_missing');
    const saved = await dependencies.state.saveAndromedaMapping(userKey, leaseToken, {
      version: 1,
      profileCookie,
      sessionId: result.session_id,
      revision: result.revision,
      lastActivityAt: timestamp,
    }, dependencies.config.andromedaProfileTtlSeconds);
    if (!saved) throw dependencyError('max_conversation_lease_lost');
  };

  return Object.freeze({
    async query(
      update: MaxUpdate,
      text: string,
    ): Promise<AssistantInteractionResult> {
      if (!('userId' in update) || typeof update.userId !== 'number'
        || !Number.isSafeInteger(update.userId) || update.userId <= 0) {
        throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'user' });
      }
      const userKey = 'max-user:' + update.userId;
      const leaseToken = requireLease(await dependencies.state.reserveConversationTurn(userKey, CONVERSATION_LEASE_SECONDS));
      let operationError: unknown;
      let outcome: AssistantInteractionResult | undefined;
      try {
        const timestamp = now();
        if (!Number.isSafeInteger(timestamp) || timestamp < 0) throw dependencyError('max_clock_invalid');

        let mapping = await dependencies.state.getAndromedaMapping(userKey);
        if (mapping?.sessionId !== undefined
          && (timestamp < mapping.lastActivityAt
            || timestamp - mapping.lastActivityAt >= dependencies.config.andromedaQuerySessionTtlSeconds * 1_000)) {
          const reset = await dependencies.state.resetAndromedaQuerySession(
            userKey,
            leaseToken,
            mapping.profileCookie,
            timestamp,
            dependencies.config.andromedaProfileTtlSeconds,
          );
          if (!reset) throw dependencyError('max_conversation_lease_lost');
          mapping = { version: 1, profileCookie: mapping.profileCookie, lastActivityAt: timestamp };
        }

        let restartedSession = false;
        let response: Awaited<ReturnType<AssistantApiPort['queryAssistant']>>;
        try {
          response = await dependencies.api.queryAssistant({
            text,
            ...(mapping?.sessionId ? { sessionId: mapping.sessionId } : {}),
            ...(mapping?.revision === undefined ? {} : { expectedRevision: mapping.revision }),
          }, mapping?.profileCookie);
        } catch (error) {
          const recoverable = error instanceof AppError
            && (error.code === ERROR_CODES.SESSION_CONFLICT || error.code === ERROR_CODES.SESSION_EXPIRED);
          if (!recoverable || !mapping?.profileCookie) throw error;
          // Reset a missing or stale session once, then submit the triggering text once.
          const resetAt = now();
          const reset = await dependencies.state.resetAndromedaQuerySession(
            userKey,
            leaseToken,
            mapping.profileCookie,
            resetAt,
            dependencies.config.andromedaProfileTtlSeconds,
          );
          if (!reset) throw dependencyError('max_conversation_lease_lost');
          response = await dependencies.api.queryAssistant({ text }, mapping.profileCookie);
          restartedSession = true;
        }

        const timestampAfterRequest = now();
        if (!Number.isSafeInteger(timestampAfterRequest) || timestampAfterRequest < timestamp) {
          throw dependencyError('max_clock_invalid');
        }
        const result = await enrichProgramComparison(
          response.result,
          text,
          dependencies.api.compareSummary?.bind(dependencies.api),
        );
        const profileCookie = response.profileCookie ?? mapping?.profileCookie;
        if (!profileCookie) throw dependencyError('max_profile_cookie_missing');
        await saveResult(userKey, leaseToken, profileCookie, result, timestampAfterRequest);
        outcome = Object.freeze({ result, restartedSession });
      } catch (error) {
        operationError = error;
      }

      let released: boolean;
      try {
        released = await dependencies.state.releaseConversationTurn(userKey, leaseToken);
      } catch {
        throw dependencyError('max_conversation_release_failed');
      }
      if (!released) throw dependencyError('max_conversation_lease_lost');
      if (operationError !== undefined) throw operationError;
      if (!outcome) throw dependencyError('max_assistant_missing_result');
      return outcome;
    },

    async resetConversation(update: MaxUpdate): Promise<void> {
      if (!('userId' in update) || typeof update.userId !== 'number'
        || !Number.isSafeInteger(update.userId) || update.userId <= 0) {
        throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'user' });
      }
      const userKey = 'max-user:' + update.userId;
      const leaseToken = requireLease(await dependencies.state.reserveConversationTurn(userKey, CONVERSATION_LEASE_SECONDS));
      let operationError: unknown;
      try {
        const timestamp = now();
        if (!Number.isSafeInteger(timestamp) || timestamp < 0) throw dependencyError('max_clock_invalid');
        const mapping = await dependencies.state.getAndromedaMapping(userKey);
        if (mapping) {
          const reset = await dependencies.state.resetAndromedaQuerySession(
            userKey,
            leaseToken,
            mapping.profileCookie,
            timestamp,
            dependencies.config.andromedaProfileTtlSeconds,
          );
          if (!reset) throw dependencyError('max_conversation_lease_lost');
        }
      } catch (error) {
        operationError = error;
      }

      let released: boolean;
      try {
        released = await dependencies.state.releaseConversationTurn(userKey, leaseToken);
      } catch {
        throw dependencyError('max_conversation_release_failed');
      }
      if (!released) throw dependencyError('max_conversation_lease_lost');
      if (operationError !== undefined) throw operationError;
    },
  });
};
