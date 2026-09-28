import { createServer, type RequestListener, type Server } from 'node:http';

export type MiniAppServer = Readonly<{
  start(): Promise<void>;
  stop(): Promise<void>;
}>;

export const createMiniAppServer = (handler: RequestListener, port: number, host?: string): MiniAppServer => {
  const server: Server = createServer(handler);
  server.requestTimeout = 10_000;
  server.headersTimeout = 5_000;
  server.keepAliveTimeout = 5_000;
  server.maxHeadersCount = 64;
  let started = false;
  let stopping = false;

  return {
    async start(): Promise<void> {
      if (started) return;
      if (stopping) throw new Error('Mini App server is stopping.');
      await new Promise<void>((resolve, reject) => {
        const onError = (error: Error): void => reject(error);
        server.once('error', onError);
        server.listen(port, host, () => {
          server.off('error', onError);
          started = true;
          resolve();
        });
      });
    },
    async stop(): Promise<void> {
      if (stopping) return;
      stopping = true;
      if (!server.listening) return;
      await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
      started = false;
    },
  };
};
