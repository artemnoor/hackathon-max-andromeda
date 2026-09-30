import 'dotenv/config';

import { loadConfig } from '../shared/config.js';
import { errorToLogFields } from '../shared/errors.js';
import { createLogger } from '../shared/logger.js';
import { buildMiniAppHandler } from '../web/app.js';
import { createMiniAppServer } from '../web/server.js';

const main = async (): Promise<void> => {
  const config = loadConfig();
  const logger = createLogger({ level: config.logLevel });
  const server = createMiniAppServer(
    buildMiniAppHandler({
      config,
      logger,
      publicApiBaseUrl: config.andromedaApiBaseUrl,
      publicApiTimeoutMs: config.andromedaApiTimeoutMs,
    }),
    config.miniAppPort,
    '127.0.0.1',
  );
  let stopping = false;

  const shutdown = async (): Promise<void> => {
    if (stopping) return;
    stopping = true;
    await server.stop();
    logger.info({ event: 'max_miniapp_stopped' });
  };

  process.once('SIGINT', () => { void shutdown(); });
  process.once('SIGTERM', () => { void shutdown(); });

  try {
    await server.start();
    logger.info({ event: 'max_miniapp_started', port: config.miniAppPort });
  } catch (error) {
    logger.fatal({ event: 'max_miniapp_start_failed', error: errorToLogFields(error) });
    process.exitCode = 1;
    await shutdown();
  }
};

await main();
