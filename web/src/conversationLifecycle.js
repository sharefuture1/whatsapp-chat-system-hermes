function encoded(value) {
  return encodeURIComponent(String(value || ''))
}

export function contactSelectionPlan(contact = {}) {
  if (contact.source === 'legacy') {
    return {
      ensure: contact.conversation_deleted
        ? { method: 'POST', path: '/chat/restore', body: { user_id: contact.user_id } }
        : null,
      conversationKey: contact.conversation_key || `legacy:${contact.user_id}`,
    }
  }
  if (contact.source === 'standalone') {
    return {
      ensure: contact.conversation_id
        ? null
        : { method: 'POST', path: `/v1/contacts/${encoded(contact.contact_id)}/conversation`, body: {} },
      conversationKey: contact.conversation_id ? `standalone:${contact.conversation_id}` : '',
    }
  }
  return { ensure: null, conversationKey: contact.conversation_key || '' }
}

export function conversationDeletePlan(conversation = {}) {
  if (conversation.source === 'standalone' && conversation.conversation_id) {
    return {
      method: 'DELETE',
      path: `/v1/conversations/${encoded(conversation.conversation_id)}`,
      body: undefined,
      conversationKey: conversation.conversation_key,
      pinKey: conversation.user_id,
    }
  }
  return {
    method: 'POST',
    path: '/chat/delete',
    body: { user_id: conversation.user_id },
    conversationKey: conversation.conversation_key || `legacy:${conversation.user_id}`,
    pinKey: conversation.user_id,
  }
}
