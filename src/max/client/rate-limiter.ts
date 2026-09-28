import { AppError, ConfigError, ERROR_CODES } from '../../shared/errors.js';
import type { MaxTransportState } from '../../shared/transport-state.js';

export type MaxOutboundRateLimiterOptions = Readonly<{
  state?: MaxTransportState;
  maxRequests?: number;
  windowSeconds?: number;
  now?: () => number;
  allowMemory?: boolean;
}>;

export class MaxOutboundRateLimiter {
  private readonly maxRequests: number;
  private readonly windowSeconds: number;
  private readonly now: () => number;
  private localWindow = { startedAt: 0, count: 0 };

  constructor(private readonly options: MaxOutboundRateLimiterOptions = {}) {
    this.maxRequests = options.maxRequests ?? 25;
    this.windowSeconds = options.windowSeconds ?? 1;
    this.now = options.now ?? Date.now;
    if (!Number.isSafeInteger(this.maxRequests) || this.maxRequests < 1 || this.maxRequests > 25
      || !Number.isSafeInteger(this.windowSeconds) || this.windowSeconds !== 1) {
      throw new ConfigError('MAX_API_RATE_LIMIT', 'runtime', 'must use an integer ceiling up to 25 requests per one-second window');
    }
    if (!options.state && options.allowMemory !== true) {
      throw new ConfigError('REDIS_URL', 'runtime', 'distributed MAX API rate limiting requires shared transport state');
    }
  }

  async acquire(signal?: AbortSignal): Promise<void> {
    if (signal?.aborted) throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_api_rate_limit' });
    if (this.options.state) {
      const count = await this.options.state.incrementWindow('max-api:bot', this.windowSeconds);
      if (signal?.aborted) throw new AppError(ERROR_CODES.DEPENDENCY_UNAVAILABLE, 503, undefined, { operation: 'max_api_rate_limit' });
      if (count > this.maxRequests) throw new AppError(ERROR_CODES.RATE_LIMITED, 429);
      return;
    }

    const now = this.now();
    if (now - this.localWindow.startedAt >= this.windowSeconds * 1000 || now < this.localWindow.startedAt) {
      this.localWindow = { startedAt: now, count: 0 };
    }
    this.localWindow.count += 1;
    if (this.localWindow.count > this.maxRequests) throw new AppError(ERROR_CODES.RATE_LIMITED, 429);
  }
}
