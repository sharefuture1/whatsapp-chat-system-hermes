import assert from 'node:assert/strict';
import test from 'node:test';

import { chunkSyncItems, normalizeChat, normalizeContact, occurrenceChunkIdentity } from '../src/sync-normalizer.js';

test('FR-CON-011: normalizers filter system JIDs and keep groups out of contacts', () => {
  assert.equal(normalizeContact({ id: 'status@broadcast', name: 'Status' }), null);
  assert.equal(normalizeContact({ id: 'x@g.us', name: 'Group' }), null);
  assert.deepEqual(normalizeContact({ id: '123@lid', name: 'Alice' }), {
    remote_jid: '123@lid', display_name: 'Alice', phone_number: null, lid: '123@lid', avatar_url: null,
  });
  assert.equal(normalizeChat({ id: 'newsletter@newsletter' }), null);
  assert.equal(normalizeChat({ id: 'group@g.us' }).conversation_type, 'group');
  assert.equal(normalizeChat({ id: '123@lid', unreadCount: 4 }).unread_count, 4);
  assert.equal('unread_count' in normalizeChat({ id: '123@lid' }), false);
});

test('FR-CON-011: chunks are bounded and unique within and across occurrences', () => {
  assert.deepEqual(chunkSyncItems(Array.from({ length: 401 }, (_, id) => ({ id })), 200).map(x => x.length), [200, 200, 1]);
  const items = [{ remote_jid: 'b@lid' }, { remote_jid: 'a@lid' }];
  assert.equal(
    occurrenceChunkIdentity('occurrence-1', 'contacts.upsert', items, 0),
    occurrenceChunkIdentity('occurrence-1', 'contacts.upsert', items, 0),
  );
  assert.notEqual(
    occurrenceChunkIdentity('occurrence-1', 'contacts.upsert', items, 0),
    occurrenceChunkIdentity('occurrence-1', 'contacts.upsert', items, 1),
  );
  assert.notEqual(
    occurrenceChunkIdentity('occurrence-1', 'contacts.upsert', items, 0),
    occurrenceChunkIdentity('occurrence-2', 'contacts.upsert', items, 0),
  );
});
