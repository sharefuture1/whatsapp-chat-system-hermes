import { createHash } from 'node:crypto';

function jidKind(jid) {
  if (typeof jid !== 'string') return null;
  if (jid.endsWith('@s.whatsapp.net') || jid.endsWith('@lid')) return 'dm';
  if (jid.endsWith('@g.us')) return 'group';
  return null;
}

export function normalizeContact(item = {}) {
  const jid = item.id ?? item.remote_jid;
  if (jidKind(jid) !== 'dm') return null;
  return {
    remote_jid: jid,
    display_name: item.name ?? item.notify ?? item.verifiedName ?? item.display_name ?? item.push_name ?? null,
    phone_number: item.phone_number ?? (jid.endsWith('@s.whatsapp.net') ? jid.split('@')[0] : null),
    lid: item.lid ?? (jid.endsWith('@lid') ? jid : null),
    avatar_url: item.imgUrl ?? item.avatar_url ?? null,
  };
}

export function normalizeChat(item = {}) {
  const jid = item.id ?? item.remote_jid;
  const kind = jidKind(jid);
  if (!kind) return null;
  const timestamp = Number(item.conversationTimestamp ?? item.last_message_timestamp);
  return {
    remote_jid: jid,
    conversation_type: kind,
    title: item.name ?? item.subject ?? item.title ?? null,
    last_message_at: Number.isFinite(timestamp) && timestamp > 0 ? new Date(timestamp * 1000).toISOString() : null,
    last_message_preview: item.last_message_preview ?? null,
    ...(item.unreadCount !== undefined || item.unread_count !== undefined
      ? { unread_count: Math.max(0, Number(item.unreadCount ?? item.unread_count) || 0) }
      : {}),
  };
}

export function chunkSyncItems(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) chunks.push(items.slice(index, index + size));
  return chunks;
}

export function occurrenceChunkIdentity(occurrenceId, kind, items, chunkIndex) {
  const canonical = (value) => {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === 'object') return Object.fromEntries(
      Object.keys(value).sort().map(key => [key, canonical(value[key])]),
    );
    return value;
  };
  const payload = items.map(canonical)
    .sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  return `sync:${occurrenceId}:${kind}:${chunkIndex}:${createHash('sha256').update(JSON.stringify(payload)).digest('hex')}`;
}
