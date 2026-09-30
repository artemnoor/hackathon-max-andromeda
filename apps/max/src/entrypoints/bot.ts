import 'dotenv/config';

import { createMaxBot } from '../max/platform/bot.js';
import { loadConfig } from '../shared/config.js';
import { errorToLogFields } from '../shared/errors.js';
import { createLogger } from '../shared/logger.js';
import { closeRedisClient, connectRedisClient, createRedisClient } from '../shared/redis/client.js';
import { RedisMaxTransportState } from '../shared/redis/transport-state.js';

const main = async (): Promise<void> => {
  const config = loadConfig();
  const logger = createLogger({ level: config.logLevel });
  let redis: ReturnType<typeof createRedisClient> | undefined;
  let runtime: ReturnType<typeof createMaxBot> | undefined;
  let shutdownTask: Promise<void> | undefined;

  const shutdown = (exitCode: number): Promise<void> => {
    const currentExitCode = typeof process.exitCode === 'number' ? process.exitCode : 0;
    process.exitCode = Math.max(currentExitCode, exitCode);
    shutdownTask ??= (async () => {
      await runtime?.stop().catch((error: unknown) => logger.warn({ event: 'max_bot_stop_failed', error: errorToLogFields(error) }));
      if (redis) await closeRedisClient(redis);
    })();
    return shutdownTask;
  };

  process.once('SIGINT', () => { void shutdown(0); });
  process.once('SIGTERM', () => { void shutdown(0); });

  try {
    if (config.redisUrl) {
      redis = createRedisClient(config, logger);
      await connectRedisClient(redis);
    }
    runtime = createMaxBot({
      config,
      logger,
      ...(redis ? { state: new RedisMaxTransportState(redis) } : {}),
      onFatal(error) {
        logger.fatal({ event: 'max_bot_fatal', error: errorToLogFields(error) });
        void shutdown(1);
      },
    });
    await runtime.start();
  } catch (error) {
    logger.fatal({ event: 'max_bot_start_failed', error: errorToLogFields(error) });
    await shutdown(1);
  }
};

await main();
