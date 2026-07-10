import crypto from 'node:crypto';
import http from 'node:http';
import net from 'node:net';

import { BridgeDomainError } from './account-session.js';

const MAX_BODY_BYTES = 64 * 1024;
const REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function structuredError(code, message, retryable = false, requestId = null, details = {}) {
  return { error: { code, message, retryable, request_id: requestId, details } };
}

function sendJson(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(body),
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
  });
  response.end(body);
}

function isLoopbackAddress(value) {
  if (!value) return false;
  const address = value.startsWith('::ffff:') ? value.slice(7) : value;
  return address === '127.0.0.1' || address === '::1' || address === 'localhost';
}

function validHostHeader(hostHeader, localPort) {
  if (typeof hostHeader !== 'string' || hostHeader.length === 0) return false;
  let hostname;
  try {
    hostname = new URL(`http://${hostHeader}`).hostname.replace(/^\[|\]$/g, '').toLowerCase();
  } catch {
    return false;
  }
  if (!isLoopbackAddress(hostname)) return false;
  const parsedPort = new URL(`http://${hostHeader}`).port;
  return !parsedPort || Number(parsedPort) === localPort;
}

function tokenMatches(actual, expected) {
  if (typeof actual !== 'string') return false;
  const actualBuffer = Buffer.from(actual);
  const expectedBuffer = Buffer.from(expected);
  return actualBuffer.length === expectedBuffer.length
    && crypto.timingSafeEqual(actualBuffer, expectedBuffer);
}

async function readJson(request) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > MAX_BODY_BYTES) {
      throw new BridgeDomainError('body_too_large', 'Request body is too large', { status: 413 });
    }
    chunks.push(chunk);
  }
  if (chunks.length === 0) return {};
  try {
    const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('not object');
    return parsed;
  } catch {
    throw new BridgeDomainError('invalid_json', 'Request body must be a JSON object', { status: 400 });
  }
}

function requiredString(body, key) {
  const value = body[key];
  if (typeof value !== 'string' || !value.trim()) {
    throw new BridgeDomainError('invalid_body', `${key} must be a non-empty string`, { status: 400 });
  }
  return value.trim();
}

function pathAccountId(pathname, suffix) {
  const expression = new RegExp(`^/accounts/([^/]+)/${suffix}$`);
  const match = pathname.match(expression);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    throw new BridgeDomainError('invalid_account_id', 'Invalid account_id encoding', { status: 400 });
  }
}

function deleteAccountId(pathname) {
  const match = pathname.match(/^\/accounts\/([^/]+)$/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    throw new BridgeDomainError('invalid_account_id', 'Invalid account_id encoding', { status: 400 });
  }
}

export function createBridgeServer({
  manager,
  internalToken,
  readyCheck = () => true,
  requestIdFactory = () => crypto.randomUUID(),
}) {
  if (!manager) throw new TypeError('manager is required');
  if (typeof internalToken !== 'string' || !internalToken.trim()) {
    throw new Error('internal token is required');
  }

  const server = http.createServer(async (request, response) => {
    const incomingRequestId = request.headers['x-request-id'];
    const requestId = typeof incomingRequestId === 'string' && REQUEST_ID.test(incomingRequestId)
      ? incomingRequestId
      : requestIdFactory();
    response.setHeader('X-Request-ID', requestId);
    try {
      if (!isLoopbackAddress(request.socket.remoteAddress)) {
        return sendJson(response, 403, structuredError('loopback_required', 'Loopback access required', false, requestId));
      }
      if (!validHostHeader(request.headers.host, request.socket.localPort)) {
        return sendJson(response, 421, structuredError('invalid_host', 'Invalid Host header', false, requestId));
      }

      const url = new URL(request.url, 'http://localhost');
      if (request.method === 'GET' && url.pathname === '/health/live') {
        return sendJson(response, 200, { live: true });
      }
      if (request.method === 'GET' && url.pathname === '/health/ready') {
        const ready = await readyCheck();
        return ready
          ? sendJson(response, 200, { ready: true })
          : sendJson(response, 503, structuredError('not_ready', 'Bridge is not ready', true, requestId));
      }

      if (!tokenMatches(request.headers['x-internal-token'], internalToken)) {
        return sendJson(response, 401, structuredError('unauthorized', 'Invalid internal token', false, requestId));
      }

      if (request.method === 'POST' && url.pathname === '/accounts') {
        const body = await readJson(request);
        const session = await manager.createAccount({
          account_id: requiredString(body, 'account_id'),
          session_ref: requiredString(body, 'session_ref'),
        });
        await session.initialize();
        return sendJson(response, 200, session.status());
      }

      const connectId = pathAccountId(url.pathname, 'connect');
      if (request.method === 'POST' && connectId !== null) {
        const status = await manager.connect(connectId);
        return sendJson(response, 202, status);
      }
      const statusId = pathAccountId(url.pathname, 'status');
      if (request.method === 'GET' && statusId !== null) {
        return sendJson(response, 200, manager.status(statusId));
      }
      const qrId = pathAccountId(url.pathname, 'qr');
      if (request.method === 'GET' && qrId !== null) {
        return sendJson(response, 200, manager.qr(qrId));
      }
      const logoutId = pathAccountId(url.pathname, 'logout');
      if (request.method === 'POST' && logoutId !== null) {
        return sendJson(response, 200, await manager.logout(logoutId));
      }
      const stopId = pathAccountId(url.pathname, 'stop');
      if (request.method === 'POST' && stopId !== null) {
        return sendJson(response, 200, await manager.stop(stopId));
      }
      const sendId = pathAccountId(url.pathname, 'send');
      if (request.method === 'POST' && sendId !== null) {
        const body = await readJson(request);
        const chatId = requiredString(body, 'chat_id');
        const text = requiredString(body, 'text');
        const messageId = await manager.send(sendId, { chatId, text });
        return sendJson(response, 200, {
          success: true,
          account_id: sendId,
          chat_id: chatId,
          message_id: messageId,
        });
      }
      const typingId = pathAccountId(url.pathname, 'typing');
      if (request.method === 'POST' && typingId !== null) {
        const body = await readJson(request);
        const chatId = requiredString(body, 'chat_id');
        if (typeof body.typing !== 'boolean') {
          throw new BridgeDomainError('invalid_body', 'typing must be a boolean', { status: 400 });
        }
        await manager.typing(typingId, { chatId, typing: body.typing });
        return sendJson(response, 200, { success: true, account_id: typingId, chat_id: chatId });
      }
      const mediaId = pathAccountId(url.pathname, 'send-media');
      if (request.method === 'POST' && mediaId !== null) {
        const body = await readJson(request);
        requiredString(body, 'chat_id');
        requiredString(body, 'media_type');
        manager.resolveMedia(mediaId, requiredString(body, 'media_ref'));
        throw new BridgeDomainError(
          'not_implemented',
          'Media sending is not implemented in Task 5',
          { status: 501 },
        );
      }
      const accountId = deleteAccountId(url.pathname);
      if (request.method === 'DELETE' && accountId !== null) {
        const raw = url.searchParams.get('delete_session');
        if (raw !== 'true' && raw !== 'false') {
          throw new BridgeDomainError(
            'invalid_delete_session',
            'delete_session must be explicitly true or false',
            { status: 400 },
          );
        }
        return sendJson(response, 200, await manager.delete(accountId, { deleteSession: raw === 'true' }));
      }

      return sendJson(response, 404, structuredError('not_found', 'Endpoint not found', false, requestId));
    } catch (error) {
      if (error instanceof BridgeDomainError) {
        return sendJson(response, error.status, structuredError(error.code, error.message, error.retryable, requestId));
      }
      return sendJson(response, 500, structuredError('internal_error', 'Internal bridge error', true, requestId));
    }
  });
  server.requestTimeout = 30_000;
  server.headersTimeout = 15_000;
  server.keepAliveTimeout = 5_000;
  return server;
}

export async function listenBridgeServer(server, { host = '127.0.0.1', port = 3100 } = {}) {
  if (!isLoopbackAddress(host) || (net.isIP(host) === 0 && host !== 'localhost')) {
    throw new Error('Bridge listener host must be loopback');
  }
  await new Promise((resolve, reject) => {
    const onError = (error) => {
      server.off('listening', onListening);
      reject(error);
    };
    const onListening = () => {
      server.off('error', onError);
      resolve();
    };
    server.once('error', onError);
    server.once('listening', onListening);
    server.listen(port, host);
  });
  return server.address();
}
