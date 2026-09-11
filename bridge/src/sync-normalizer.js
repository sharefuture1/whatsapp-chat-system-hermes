import { createHash } from 'node:crypto';

function jidKind(jid) {
  if (typeof jid !== 'string') return null;
  if (jid.endsWith('@s.whatsapp.net') || jid.endsWith('@lid')) return 'dm';
  if (jid.endsWith('@g.us')) return 'group';
  return null;
}

function firstText(...values) {
  for (const value of values) {
    if (typeof value !== 'string') continue;
    const text = value.trim();
    if (text) return text;
  }
  return null;
}

export function normalizeContact(item = {}) {
  const jid = item.id ?? item.remote_jid;
  if (jidKind(jid) !== 'dm') return null;
  const displayName = firstText(
    item.name,
    item.notify,
    item.verifiedName,
    item.verifiedBizName,
    item.shortName,
    item.formattedName,
    item.pushName,
    item.displayName,
    item.display_name,
    item.push_name,
  );
  const explicitPhone = firstText(item.phone_number, item.phoneNumber, item.pn);
  const phoneNumber = explicitPhone ?? (jid.endsWith('@s.whatsapp.net') ? jid.split('@')[0] : null);
  const lid = firstText(item.lid) ?? (jid.endsWith('@lid') ? jid : null);
  const avatarUrl = firstText(item.imgUrl, item.avatarUrl, item.avatar_url);
  return {
    remote_jid: jid,
    ...(displayName ? { display_name: displayName } : {}),
    ...(phoneNumber ? { phone_number: phoneNumber } : {}),
    ...(lid ? { lid } : {}),
    ...(avatarUrl ? { avatar_url: avatarUrl } : {}),
  };
}

export function normalizeChat(item = {}) {
  const jid = item.id ?? item.remote_jid;
  const kind = jidKind(jid);
  if (!kind) return null;
  const timestamp = Number(item.conversationTimestamp ?? item.last_message_timestamp);
  const title = firstText(item.name, item.subject, item.title, item.notify, item.pushName);
  const preview = firstText(item.last_message_preview, item.lastMessagePreview);
  return {
    remote_jid: jid,
    conversation_type: kind,
    ...(title ? { title } : {}),
    ...(Number.isFinite(timestamp) && timestamp > 0
      ? { last_message_at: new Date(timestamp * 1000).toISOString() }
      : {}),
    ...(preview ? { last_message_preview: preview } : {}),
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
