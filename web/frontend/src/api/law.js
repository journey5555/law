async function request(url) {
  const res = await fetch(url)
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || '요청 오류')
  return data
}

export const searchLaw  = (q, page = 1, display = 10) =>
  request(`/api/law/search?q=${encodeURIComponent(q)}&display=${display}&page=${page}`)

export const getLaw = (id) =>
  request(`/api/law/${encodeURIComponent(id)}`)

export const getArticle = (lawName, jo, joSub = 0) =>
  request(`/api/law/article?law_name=${encodeURIComponent(lawName)}&jo=${jo}&jo_sub=${joSub}`)

export const searchPrec = (q, page = 1, display = 10) =>
  request(`/api/prec/search?q=${encodeURIComponent(q)}&display=${display}&page=${page}`)

export const getPrec = (id) =>
  request(`/api/prec/${encodeURIComponent(id)}`)

export async function summarize(text) {
  const res = await fetch('/api/summarize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || '요약 오류')
  return data
}
