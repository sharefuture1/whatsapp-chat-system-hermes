import assert from 'node:assert/strict';
import test from 'node:test';

import { chunkSyncItems, normalizeChat, normalizeContact, occurrenceChunkIdentity } from '../src/sync-normalizer.js';

test('FR-CON-011: normalizers filter system JIDs and keep groups out of contacts', () => {
  assert.equal(normalizeContact({ id: 'status@broadcast', name: 'Status' }), null);
  assert.equal(normalizeContact({ id: 'x@g.us', name: 'Group' }), null);
  assert.deepEqual(normalizeContact({ id: '123@lid', name: 'Alice' }), {
    remote_jid: '123@lid', display_name: 'Alice', lid: '123@lid',
  });
  assert.deepEqual(normalizeContact({ id: '456@s.whatsapp.net', pushName: 'Bob', phoneNumber: '+456' }), {
    remote_jid: '456@s.whatsapp.net', display_name: 'Bob', phone_number: '+456',
  });
  const sparseContact = normalizeContact({ id: '789@lid' });
  assert.equal('display_name' in sparseContact, false);
  assert.equal('avatar_url' in sparseContact, false);
  assert.equal('phone_number' in sparseContact, false);
  assert.equal(normalizeChat({ id: 'newsletter@newsletter' }), null);
  assert.equal(normalizeChat({ id: 'group@g.us' }).conversation_type, 'group');
  assert.equal(normalizeChat({ id: '123@lid', unreadCount: 4 }).unread_count, 4);
  const sparseChat = normalizeChat({ id: '123@lid' });
  assert.equal('unread_count' in sparseChat, false);
  assert.equal('title' in sparseChat, false);
  assert.equal('last_message_at' in sparseChat, false);
  assert.equal('last_message_preview' in sparseChat, false);
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
