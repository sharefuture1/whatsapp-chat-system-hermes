import { api } from './api.js'

export async function fetchPersonaCatalog() {
  const body = await api.get('/v1/personas')
  return {
    items: Array.isArray(body?.items) ? body.items : [],
    available: Boolean(body?.items?.length) && body?.plugin_enabled !== false,
    plugin_enabled: body?.plugin_enabled !== false,
    contact_assignments: body?.contact_assignments || {},
  }
}

export async function assignPersona(contactId, personaId) {
  return api.put(`/v1/contacts/${encodeURIComponent(contactId)}/persona`, { persona_id: personaId })
}

export async function setPersonaPluginEnabled(personaId, enabled) {
  return api.put(`/v1/personas/${encodeURIComponent(personaId)}/enable`, { enabled: Boolean(enabled) })
}
