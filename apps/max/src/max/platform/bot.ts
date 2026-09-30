import { createServer, type Server } from 'node:http';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { Bot, type ClientOptions } from '@maxhub/max-bot-api';
import type { AttachmentRequest, BotInfo, UpdateType } from '@maxhub/max-bot-api/types';

import type { AppConfig } from '../../shared/config.js';
import { AppError, ConfigError, ERROR_CODES, errorToLogFields } from '../../shared/errors.js';
import type { Logger } from '../../shared/logger.js';
import type { MaxTransportState } from '../../shared/transport-state.js';
import { MemoryMaxTransportState } from '../../shared/memory-transport-state.js';
import { isPublicHostname } from '../../shared/url-policy.js';
import { createMaxUpdateHandler, type MaxBotReply } from '../bot/handler.js';
import { normalizeMaxUpdate, type MaxUpdate } from '../bot/update.js';
import { createMaxApiFetch, MaxApiClient } from '../client/api-fetch.js';
import { MaxOutboundRateLimiter } from '../client/rate-limiter.js';
import { withWebhookGuard } from '../webhook/guard.js';
import { AndromedaApiClient } from '../client/andromeda-api.js';
import { createAssistantInteraction } from '../bot/assistant.js';
import type { MaxChatMessage, MaxMessageButton } from '../bot/response-renderer.js';

export const DEFAULT_ALLOWED_UPDATES = [
  'bot_started', 'message_created', 'message_callback',
  'bot_added', 'user_added', 'bot_stopped', 'bot_removed',
] as const satisfies readonly UpdateType[];

// Leave headroom under the MAX API client's five-second request deadline.
export const MAX_POLL_WAIT_SECONDS = 3;

export const NEUTRAL_BOT_COMMANDS = [
  { name: 'start', description: 'Открыть технический статус бота' },
  { name: 'help', description: 'Помощь по техническому статусу' },
] as const;

export type MaxPlatform = Pick<Bot, 'api'> & { botInfo?: BotInfo };
export type MaxSdkFactory = (token: string, options: ClientOptions) => MaxPlatform;
export type MaxBotDependencies = Readonly<{
  config: Pick<AppConfig,
    'maxBotToken' | 'maxApiBaseUrl' | 'transport' | 'isProtected' | 'nodeEnv'
    | 'webhookDomain' | 'webhookPort' | 'webhookPath' | 'webhookSecret'
    | 'redisUrl' | 'logLevel' | 'andromedaApiBaseUrl' | 'andromedaProfileCookieName'
    | 'andromedaApiTimeoutMs' | 'andromedaProfileTtlSeconds' | 'andromedaQuerySessionTtlSeconds'
    | 'miniAppPublicUrl'>;
  logger: Logger;
  state?: MaxTransportState;
  handleUpdate?: (update: MaxUpdate) => Promise<MaxBotReply | undefined>;
  createSdkBot?: MaxSdkFactory;
  fetcher?: typeof fetch;
  onFatal?: (error: unknown) => void;
}>;

export type MaxBotRuntime = Readonly<{
  start(): Promise<void>;
  stop(): Promise<void>;
}>;

export const assertNoConflictingWebhookSubscriptions = (
  subscriptions: readonly Readonly<{ url?: unknown }>[],
  targetUrl: string,
): void => {
  for (const subscription of subscriptions) {
    if (typeof subscription.url !== 'string' || subscription.url.length === 0) {
      throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { operation: 'webhook_subscription_invalid' });
    }
    if (subscription.url !== targetUrl) {
      throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { operation: 'webhook_subscription_conflict' });
    }
  }
};

const webhookUrl = (domain: string, path: string, protectedEnvironment: boolean): string => {
  if (protectedEnvironment && !isPublicHostname(domain)) {
    throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { field: 'MAX_WEBHOOK_DOMAIN' });
  }
  if (!/^\/[A-Za-z0-9][A-Za-z0-9/_-]{0,127}$/u.test(path) || path.includes('//') || path.includes('..')) {
    throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { field: 'MAX_WEBHOOK_PATH' });
  }
  return `https://${domain}${path}`;
};

const updateFromBody = (body: Buffer): Readonly<{ updateType: string; update: unknown }> => {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body.toString('utf8')) as unknown;
  } catch {
    throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'json' });
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'update' });
  }
  const updateType = (parsed as Record<string, unknown>)['update_type'];
  if (typeof updateType !== 'string') throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { field: 'update_type' });
  return { updateType, update: parsed };
};

const isRetryablePollingFailure = (error: unknown): boolean => {
  if (error instanceof AppError) return error.code === ERROR_CODES.DEPENDENCY_UNAVAILABLE || error.code === ERROR_CODES.RATE_LIMITED;
  if (error && typeof error === 'object') {
    const status = (error as { status?: unknown }).status;
    if (typeof status === 'number') return status === 429 || status >= 500;
    if (error instanceof Error && error.name === 'TypeError') return true;
  }
  return false;
};

const safeTextError = (error: unknown): AppError => error instanceof AppError
  ? error
  : new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_bot_update' }, { cause: error });

export const createMaxBot = (dependencies: MaxBotDependencies): MaxBotRuntime => {
  const logger = dependencies.logger.child({ component: 'max.bot' });
  const state = dependencies.state ?? (dependencies.config.isProtected
    ? (() => { throw new ConfigError('REDIS_URL', 'protected', 'Redis-backed transport state must be composed before Bot startup'); })()
    : new MemoryMaxTransportState());
  const andromedaClient = new AndromedaApiClient({
    baseUrl: dependencies.config.andromedaApiBaseUrl,
    environment: dependencies.config.nodeEnv,
    profileCookieName: dependencies.config.andromedaProfileCookieName,
    timeoutMs: dependencies.config.andromedaApiTimeoutMs,
    profileCookieSecure: dependencies.config.isProtected,
    logger: logger.child({ component: 'andromeda.api' }),
  });
  const assistant = createAssistantInteraction({
    api: andromedaClient,
    state,
    config: dependencies.config,
  });
  const handleUpdate = dependencies.handleUpdate ?? createMaxUpdateHandler({
    assistant,
    ...(dependencies.config.miniAppPublicUrl ? { miniAppPublicUrl: dependencies.config.miniAppPublicUrl } : {}),
    onReportFailure(error) {
      logger.warn({ event: 'max_report_generation_failed', errorType: error instanceof Error ? error.name : 'unknown' });
    },
  });
  const apiClient = new MaxApiClient({
    limiter: new MaxOutboundRateLimiter({ state }),
    logger: logger.child({ component: 'max.api' }),
  });
  const maxFetch = createMaxApiFetch(apiClient, dependencies.fetcher);
  const baseUrl = dependencies.config.maxApiBaseUrl.endsWith('/')
    ? dependencies.config.maxApiBaseUrl
    : `${dependencies.config.maxApiBaseUrl}/`;
  const sdkFactory = dependencies.createSdkBot ?? ((token, options) => new Bot(token, { clientOptions: options }));
  const platform = sdkFactory(dependencies.config.maxBotToken, { baseUrl, fetch: maxFetch });

  let server: Server | undefined;
  let pollingController: AbortController | undefined;
  let pollingTask: Promise<void> | undefined;
  let started = false;
  let stopping = false;

  const toAttachments = (buttons: readonly (readonly MaxMessageButton[])[]) => [{
    type: 'inline_keyboard' as const,
    payload: {
      buttons: buttons.map((row) => row.map((button) => button.linkUrl
        ? { type: 'link' as const, text: button.text, url: button.linkUrl }
        : button.webAppUrl
        ? {
          type: 'open_app' as const,
          text: button.text,
          // MAX expects the bot's public MAX link here; MINI_APP_PUBLIC_URL is
          // the hosted page origin and is only used by the Mini App server.
          web_app: platform.botInfo?.username
            ? `https://max.ru/${platform.botInfo.username.replace(/^@/u, '')}?startapp`
            : button.webAppUrl,
        }
        : button.callbackPayload
          ? { type: 'callback' as const, text: button.text, payload: button.callbackPayload }
          : { type: 'message' as const, text: button.text })),
    },
  }];
  const uploadReport = async (document: NonNullable<MaxChatMessage['document']>): Promise<AttachmentRequest> => {
    if (!/^[a-z0-9-]{1,80}\.pdf$/iu.test(document.filename)
      || document.content.byteLength < 8
      || document.content.byteLength > 4_000_000
      || document.content.subarray(0, 5).toString('ascii') !== '%PDF-') {
      throw new AppError(ERROR_CODES.VALIDATION_FAILED, 400, undefined, { operation: 'max_pdf_attachment_invalid' });
    }
    const directory = await mkdtemp(join(tmpdir(), 'andromeda-max-report-'));
    const path = join(directory, document.filename);
    try {
      await writeFile(path, document.content, { flag: 'wx', mode: 0o600 });
      const uploaded = await platform.api.uploadFile({ source: path, timeout: 20_000 });
      return uploaded.toJson();
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  };
  const sendChatMessage = async (update: MaxUpdate, message: MaxChatMessage): Promise<void> => {
    const attachments: AttachmentRequest[] = [];
    let text = message.text;
    if (message.document) {
      try {
        attachments.push(await uploadReport(message.document));
      } catch (error) {
        logger.warn({
          event: 'max_report_attachment_failed',
          errorType: error instanceof Error ? error.name : 'unknown',
        });
        text = 'Не удалось прикрепить PDF. Краткий ответ приведён выше; попробуйте повторить запрос позже.';
      }
    }
    if (message.buttons) attachments.push(...toAttachments(message.buttons));
    const send = async (attachments?: AttachmentRequest[]): Promise<void> => {
      const options = attachments?.length ? { attachments } : undefined;
      if (update.chatId !== undefined) {
        await platform.api.sendMessageToChat(update.chatId, text, options);
        return;
      }
      if ('userId' in update && update.userId !== undefined) {
        await platform.api.sendMessageToUser(update.userId, text, options);
        return;
      }
      throw new AppError(ERROR_CODES.INTERNAL_ERROR, 500, undefined, { operation: 'max_reply_target' });
    };
    try {
      await send(attachments);
      if (message.buttons?.some((row) => row.some((button) => button.linkUrl))) {
        logger.debug({ event: '[FIX] max_catalog_website_link_sent' });
      }
    } catch (error) {
      const status = error && typeof error === 'object' ? (error as { status?: unknown }).status : undefined;
      if (attachments.length === 0 || status !== 400) throw error;
      logger.warn({ event: 'max_message_attachments_rejected', status: 400 });
      // Keep the actual reply available if MAX rejects an optional keyboard or
      // document attachment. A failed attachment must not suppress /start.
      await send();
    }
  };
  const deliver = async (update: MaxUpdate, reply: MaxBotReply | undefined): Promise<void> => {
    if (!reply) return;
    if (reply.kind === 'callback') {
      await platform.api.answerOnCallback(reply.callbackId, { message: { text: reply.text } });
      for (const message of reply.messages ?? []) await sendChatMessage(update, message);
      return;
    }
    if (reply.kind === 'batch') {
      for (const message of reply.messages) await sendChatMessage(update, message);
      return;
    }
    await sendChatMessage(update, reply);
  };

  const processUpdate = async (context: Readonly<{ updateType: string; update: unknown }>): Promise<void> => {
    const normalized = normalizeMaxUpdate(context);
    if (!normalized) return;
    const reservation = await state.reserveUpdate(normalized.updateId, 30);
    if (reservation.status === 'processed') {
      logger.debug({ event: 'max_update_duplicate', updateKind: normalized.kind });
      return;
    }
    if (reservation.status === 'busy') {
      throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_update_in_progress' });
    }
    try {
      const reply = await handleUpdate(normalized);
      await deliver(normalized, reply);
      if (!await state.completeUpdate(normalized.updateId, reservation.leaseToken, 86_400)) {
        throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_update_lease_lost' });
      }
      logger.info({ event: 'max_update_processed', updateKind: normalized.kind });
    } catch (error) {
      await state.releaseUpdate(normalized.updateId, reservation.leaseToken).catch((releaseError: unknown) => {
        logger.warn({ event: 'max_update_lease_release_failed', error: errorToLogFields(releaseError) });
      });
      throw safeTextError(error);
    }
  };

  const closeServer = async (): Promise<void> => {
    const current = server;
    server = undefined;
    if (!current?.listening) return;
    await new Promise<void>((resolve, reject) => current.close((error) => error ? reject(error) : resolve()));
  };

  const runPolling = async (signal: AbortSignal): Promise<void> => {
    let marker: number | undefined;
    let backoffMs = 500;
    while (!signal.aborted) {
      try {
        const response = await platform.api.getUpdates([...DEFAULT_ALLOWED_UPDATES], {
          ...(marker === undefined ? {} : { marker }),
          timeout: MAX_POLL_WAIT_SECONDS,
          signal,
        });
        for (const update of response.updates) {
          try {
            await processUpdate({ updateType: update.update_type, update });
          } catch (error) {
            if (error instanceof AppError && error.code === ERROR_CODES.VALIDATION_FAILED) {
              logger.warn({ event: 'max_polling_update_rejected', updateKind: update.update_type });
              continue;
            }
            throw error;
          }
        }
        marker = response.marker;
        backoffMs = 500;
      } catch (error) {
        if (signal.aborted || (error instanceof Error && error.name === 'AbortError')) return;
        if (!isRetryablePollingFailure(error)) throw error;
        logger.warn({ event: 'max_polling_retry', backoffMs, error: errorToLogFields(error) });
        await new Promise<void>((resolve) => {
          const timeout = setTimeout(resolve, backoffMs);
          signal.addEventListener('abort', () => { clearTimeout(timeout); resolve(); }, { once: true });
        });
        backoffMs = Math.min(backoffMs * 2, 5_000);
      }
    }
  };

  const startPolling = async (): Promise<void> => {
    pollingController = new AbortController();
    pollingTask = runPolling(pollingController.signal).catch((error: unknown) => {
      if (!pollingController?.signal.aborted) {
        logger.error({ event: 'max_polling_stopped', error: errorToLogFields(error) });
        dependencies.onFatal?.(error);
      }
    });
  };

  const startWebhook = async (): Promise<void> => {
    const targetUrl = webhookUrl(dependencies.config.webhookDomain, dependencies.config.webhookPath, dependencies.config.isProtected);
    const callback = withWebhookGuard({
      path: dependencies.config.webhookPath,
      secret: dependencies.config.webhookSecret,
      logger,
      onBody: async (body) => processUpdate(updateFromBody(body)),
    });
    server = createServer(callback);
    server.requestTimeout = 30_000;
    server.headersTimeout = 10_000;
    server.keepAliveTimeout = 5_000;
    server.maxHeadersCount = 64;
    try {
      await new Promise<void>((resolve, reject) => {
        const current = server;
        current?.once('error', reject);
        current?.listen(dependencies.config.webhookPort, '127.0.0.1', () => {
          current.off('error', reject);
          resolve();
        });
      });
      const subscriptions = await platform.api.getSubscriptions();
      assertNoConflictingWebhookSubscriptions(subscriptions, targetUrl);
      if (!subscriptions.some((subscription) => subscription.url === targetUrl)) {
        await platform.api.subscribe(targetUrl, dependencies.config.webhookSecret, [...DEFAULT_ALLOWED_UPDATES]);
      }
    } catch (error) {
      await closeServer().catch(() => undefined);
      throw safeTextError(error);
    }
  };

  return {
    async start(): Promise<void> {
      if (started) return;
      if (stopping) throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { operation: 'max_bot_stopping' });
      if (!dependencies.config.maxBotToken) throw new AppError(ERROR_CODES.CONFIG_INVALID, 500, undefined, { field: 'MAX_BOT_TOKEN' });
      platform.botInfo = await platform.api.getMyInfo();
      await platform.api.setMyCommands(NEUTRAL_BOT_COMMANDS.map((command) => ({ ...command })));
      if (dependencies.config.transport === 'webhook') await startWebhook();
      else await startPolling();
      started = true;
      logger.info({ event: 'max_bot_started', transport: dependencies.config.transport });
    },
    async stop(): Promise<void> {
      if (stopping) return;
      stopping = true;
      pollingController?.abort();
      await pollingTask?.catch(() => undefined);
      await closeServer();
      started = false;
      logger.info({ event: 'max_bot_stopped' });
    },
  };
};
