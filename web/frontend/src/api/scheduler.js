async function req(url, opts = {}) {
  const res = await fetch(url, opts)
  if (res.status === 204) return null
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || '요청 오류')
  return data
}

const json = (body) => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const getLaws    = ()     => req('/api/scheduler/laws')
export const addLaw     = (body) => req('/api/scheduler/laws', { ...json(body), method: 'POST' })
export const updateLaw  = (id, body) => req(`/api/scheduler/laws/${id}`, { ...json(body), method: 'PUT' })
export const deleteLaw  = (id)   => req(`/api/scheduler/laws/${id}`, { method: 'DELETE' })
export const runLaw     = (id)   => req(`/api/scheduler/laws/${id}/run`, { method: 'POST' })
export const getLogs    = (lawId) => req(lawId ? `/api/scheduler/logs?law_id=${lawId}` : '/api/scheduler/logs')
export const getPresets = ()     => req('/api/scheduler/presets')
