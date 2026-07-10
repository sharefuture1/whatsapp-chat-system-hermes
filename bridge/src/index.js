import { readdir } from 'node:fs/promises';

import { AccountManager } from './account-manager.js';
import { createBaileysSocket } from './baileys-adapter.js';
import { loadConfig } from './config.js';
import { createBridgeServer, listenBridgeServer } from './server.js';
import { EventSink } from './events/event-sink.js';
import { FileSpool } from './events/file-spool.js';

const SAFE_ACCOUNT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

async function startSpoolReplay(config) {
  const entries = await readdir(config.spoolRoot, { withFileTypes: true });
  const sinks = new Map();
  try {
    for (const entry of entries) {
      if (!entry.isDirectory() || !SAFE_ACCOUNT_ID.test(entry.name)) continue;
      const sink = new EventSink({
        spool: new FileSpool({ root: config.spoolRoot, accountId: entry.name }),
        token: config.eventToken,
        url: config.eventUrl,
      });
      await sink.start();
      sinks.set(entry.name, sink);
    }
    return sinks;
  } catch (error) {
    await Promise.allSettled([...sinks.values()].map((sink) => sink.stop()));
    throw error;
  }
}

function closeServer(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

export function installGracefulShutdown({ processRef = process, server, manager }) {
  let resolveDone;
  const done = new Promise((resolve) => { resolveDone = resolve; });
  let shutdownPromise = null;
  const shutdown = () => {
    if (shutdownPromise) return shutdownPromise;
    shutdownPromise = (async () => {
      try {
        await closeServer(server);
        await manager.closeAll();
        processRef.exitCode = 0;
      } catch (error) {
        console.error(`Bridge shutdown failed: ${error.message}`);
        processRef.exitCode = 1;
      } finally {
        resolveDone();
      }
    })();
    return shutdownPromise;
  };
  processRef.once('SIGTERM', shutdown);
  processRef.once('SIGINT', shutdown);
  return { shutdown, done };
}

export async function startBridge(env = process.env) {
  const config = loadConfig(env);
  await config.prepareRuntime();
  const replaySinks = await startSpoolReplay(config);
  const manager = new AccountManager({
    sessionRoot: config.sessionRoot,
    spoolRoot: config.spoolRoot,
    mediaRoot: config.mediaRoot,
    socketFactory: createBaileysSocket,
    qrTtlMs: config.qrTtlMs,
    eventSinkFactory: ({ accountId }) => {
      const existing = replaySinks.get(accountId);
      if (existing) return existing;
      const sink = new EventSink({
        spool: new FileSpool({ root: config.spoolRoot, accountId }),
        token: config.eventToken,
        url: config.eventUrl,
      });
      replaySinks.set(accountId, sink);
      return sink;
    },
  });
  await manager.initialize();
  const server = createBridgeServer({
    manager,
    internalToken: config.internalToken,
    readyCheck: () => manager.isReady(),
  });
  await listenBridgeServer(server, { host: config.host, port: config.port });
  const shutdownTarget = {
    async closeAll() {
      await manager.closeAll();
      await Promise.allSettled([...replaySinks.values()].map((sink) => sink.stop()));
    },
  };
  const gracefulShutdown = installGracefulShutdown({ server, manager: shutdownTarget });
  return { server, manager, config, replaySinks, gracefulShutdown };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  startBridge().catch((error) => {
    console.error(`Bridge failed to start: ${error.message}`);
    process.exitCode = 1;
  });
}
