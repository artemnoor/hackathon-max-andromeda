export const ERROR_CODES = {
  CONFIG_INVALID: 'CONFIG_INVALID',
  AUTH_REQUIRED: 'AUTH_REQUIRED',
  AUTH_INVALID: 'AUTH_INVALID',
  AUTH_EXPIRED: 'AUTH_EXPIRED',
  FORBIDDEN: 'FORBIDDEN',
  VALIDATION_FAILED: 'VALIDATION_FAILED',
  RATE_LIMITED: 'RATE_LIMITED',
  DUPLICATE_EVENT: 'DUPLICATE_EVENT',
  DEPENDENCY_UNAVAILABLE: 'DEPENDENCY_UNAVAILABLE',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
} as const;

export type ErrorCode = typeof ERROR_CODES[keyof typeof ERROR_CODES];
export type ErrorDetails = Readonly<Record<string, boolean | number | string | null>>;

const PUBLIC_MESSAGES: Record<ErrorCode, string> = {
  CONFIG_INVALID: 'Сервис настроен некорректно.',
  AUTH_REQUIRED: 'Требуется авторизация.',
  AUTH_INVALID: 'Не удалось подтвердить авторизацию.',
  AUTH_EXPIRED: 'Срок действия авторизации истёк.',
  FORBIDDEN: 'Недостаточно прав для этой операции.',
  VALIDATION_FAILED: 'Проверьте данные запроса.',
  RATE_LIMITED: 'Слишком много запросов. Повторите позже.',
  DUPLICATE_EVENT: 'Событие уже обработано.',
  DEPENDENCY_UNAVAILABLE: 'Временная ошибка внешнего сервиса.',
  INTERNAL_ERROR: 'Внутренняя ошибка сервиса.',
};

export class AppError extends Error {
  readonly safeMessage: string;

  constructor(
    readonly code: ErrorCode,
    readonly status: number,
    safeMessage = PUBLIC_MESSAGES[code],
    readonly details?: ErrorDetails,
    options: { cause?: unknown } = {},
  ) {
    super(safeMessage, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = 'AppError';
    this.safeMessage = safeMessage;
  }

  toLogFields(): Record<string, unknown> {
    return {
      errorCode: this.code,
      status: this.status,
      ...(this.details ? { details: this.details } : {}),
    };
  }

  toPublicPayload(requestId?: string): Record<string, unknown> {
    return {
      error: { code: this.code, message: this.safeMessage },
      ...(requestId ? { requestId } : {}),
    };
  }
}

export class ConfigError extends AppError {
  constructor(readonly key: string, readonly environment: string, readonly reason: string) {
    super(ERROR_CODES.CONFIG_INVALID, 500, PUBLIC_MESSAGES.CONFIG_INVALID, { key, environment, reason });
    this.name = 'ConfigError';
  }
}

export const errorToLogFields = (error: unknown): Record<string, unknown> => {
  if (error instanceof AppError) return error.toLogFields();
  if (error instanceof Error) return { errorName: error.name };
  return { errorType: typeof error };
};

export const errorToPublicPayload = (error: unknown, requestId?: string): Record<string, unknown> => {
  if (error instanceof AppError) return error.toPublicPayload(requestId);
  return {
    error: { code: ERROR_CODES.INTERNAL_ERROR, message: PUBLIC_MESSAGES.INTERNAL_ERROR },
    ...(requestId ? { requestId } : {}),
  };
};