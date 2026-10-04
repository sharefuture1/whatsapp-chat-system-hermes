import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { mkdtemp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';

import { FileSpool } from '../src/events/file-spool.js';
import { EventSink } from '../src/events/event-sink.js';
import { loadConfig } from '../src/config.js';

const TOKEN = 'internal-secret';
const SECRET = 'hmac-secret-for-shared-contract';

function event(eventId = 'evt-1') {
  return {
    event_id: eventId,
    event_type: 'account.connected',
    account_id: 'A',
    occurred_at: '2026-07-10T00:00:00.000Z',
    sequence: 1,
    payload: { state: 'online' },
  };
}

async function setup({ hmacSecret = '', fetchImpl } = {}) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'event-sink-signing-'));
  const sink = new EventSink({
    spool: new FileSpool({ root, accountId: 'A' }),
    token: TOKEN,
    hmacSecret,
    fetchImpl:
      fetchImpl ??
      (async () => ({ status: 200, json: async () => ({ accepted: true }) })),
    timeoutMs: 200,
    backoff: () => 0,
  });
  await sink.initialize();
  return sink;
}

async function flushAndCapture(sink) {
  const calls = [];
  // enqueue 本身就会驱动一次投递（见 event-sink.test.js 的既有约定），
  // 因此这里只替换 fetch 实现，不再额外调用 flushOnce，否则会投递两次。
  sink.fetchImpl = async (url, init) => {
    calls.push({ url, init });
    return { status: 200, json: async () => ({ accepted: true }) };
  };
  await sink.enqueue(event());
  assert.equal(calls.length, 1, '应当只发出一次请求');
  return calls[0];
}

test('未配置签名密钥时不发送签名头（向后兼容）', async () => {
  const sink = await setup();

  const { init } = await flushAndCapture(sink);

  assert.equal(init.headers['X-Internal-Token'], TOKEN);
  assert.equal(init.headers['X-Internal-Timestamp'], undefined);
  assert.equal(init.headers['X-Internal-Signature'], undefined);
  assert.equal(init.headers['X-Internal-Nonce'], undefined);
});

test('配置签名密钥后发送完整签名头', async () => {
  const sink = await setup({ hmacSecret: SECRET });

  const { init } = await flushAndCapture(sink);

  assert.equal(init.headers['X-Internal-Token'], TOKEN);
  assert.match(init.headers['X-Internal-Timestamp'], /^\d+$/);
  assert.match(init.headers['X-Internal-Signature'], /^[0-9a-f]{64}$/);
  assert.match(init.headers['X-Internal-Nonce'], /^[0-9a-f-]{36}$/);
});

test('签名覆盖实际发送的 body 字节', async () => {
  const sink = await setup({ hmacSecret: SECRET });

  const { init } = await flushAndCapture(sink);

  const timestamp = init.headers['X-Internal-Timestamp'];
  const expected = createHmac('sha256', SECRET)
    .update(`${timestamp}.`, 'utf8')
    .update(Buffer.from(init.body, 'utf8'))
    .digest('hex');

  assert.equal(init.headers['X-Internal-Signature'], expected);
});

test('签名口径与 Python 端黄金向量一致（含中文与 emoji）', () => {
  // 该签名由 Python 端 compute_signature 独立计算得出，
  // 此处作为跨语言契约的黄金向量固定下来：
  //   compute_signature('hmac-secret-for-e2e-test', '1789053718', body)
  // 一旦口径漂移（例如改变分隔符或编码），本测试会失败。
  const body = '{"event_id":"evt-1","text":"你好世界 emoji 🎉","n":42}';
  const timestamp = '1789053718';
  const golden = '68a079b16e6f844dae9bf64eb28228954215dc59a88ee21c7b500aaf652abaff';

  const actual = createHmac('sha256', 'hmac-secret-for-e2e-test')
    .update(`${timestamp}.`, 'utf8')
    .update(Buffer.from(body, 'utf8'))
    .digest('hex');

  assert.equal(actual, golden);
});

test('同一事件重试时 nonce 必须变化，避免被误判为重放', async () => {
  let attempt = 0;
  const nonces = [];
  const sink = await setup({ hmacSecret: SECRET });
  sink.fetchImpl = async (_url, init) => {
    nonces.push(init.headers['X-Internal-Nonce']);
    attempt += 1;
    // 前两次失败以触发重试
    return attempt < 3
      ? { status: 503, json: async () => ({ error: { retryable: true } }) }
      : { status: 200, json: async () => ({ accepted: true }) };
  };

  await sink.enqueue(event('evt-retry'));
  for (let index = 0; index < 6; index += 1) {
    await sink.flushOnce();
  }

  assert.ok(nonces.length >= 2, `期望发生重试，实际投递 ${nonces.length} 次`);
  assert.equal(new Set(nonces).size, nonces.length, '每次投递的 nonce 必须唯一');
});

test('时间戳取当前秒级 Unix 时间', async () => {
  const sink = await setup({ hmacSecret: SECRET });
  const before = Math.floor(Date.now() / 1000);

  const { init } = await flushAndCapture(sink);

  const after = Math.floor(Date.now() / 1000);
  const stamp = Number(init.headers['X-Internal-Timestamp']);
  assert.ok(stamp >= before && stamp <= after, `时间戳 ${stamp} 不在 [${before}, ${after}]`);
});

test('config 读取 WHATSAPP_BRIDGE_HMAC_SECRET', () => {
  const config = loadConfig({
    WHATSAPP_BRIDGE_INTERNAL_TOKEN: TOKEN,
    WHATSAPP_BRIDGE_HMAC_SECRET: SECRET,
  });
  assert.equal(config.hmacSecret, SECRET);
});

test('config 未设置签名密钥时为空串（保持向后兼容）', () => {
  const config = loadConfig({ WHATSAPP_BRIDGE_INTERNAL_TOKEN: TOKEN });
  assert.equal(config.hmacSecret, '');
});

test('config 拒绝签名密钥与内部 token 相同', () => {
  assert.throws(
    () =>
      loadConfig({
        WHATSAPP_BRIDGE_INTERNAL_TOKEN: TOKEN,
        WHATSAPP_BRIDGE_HMAC_SECRET: TOKEN,
      }),
    /must differ/,
  );
});
