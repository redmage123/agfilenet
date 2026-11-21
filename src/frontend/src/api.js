async function request(path, options) {
  const res = await fetch(path, options)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = (await res.json()).detail
      if (typeof body === 'string') detail = body
      else if (Array.isArray(body)) detail = body.map((d) => d.msg).join('; ') || detail
    } catch {
      // not JSON
    }
    throw new Error(detail)
  }
  return res.json()
}

const json = (method, body) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

const query = (params) => {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => v && q.set(k, v))
  return q.toString()
}

export const api = {
  status: () => request('/api/status'),
  ingest: (force) => request('/api/ingest', json('POST', { force })),
  facets: () => request('/api/facets'),
  documents: (filters) => request(`/api/documents?${query(filters)}`),
  document: (id) => request(`/api/documents/${id}`),
  saveDocument: (id, changes) => request(`/api/documents/${id}`, json('PATCH', changes)),
  search: (q, mode) => request(`/api/search?${query({ q, mode })}`),
  feedback: (body) => request('/api/feedback', json('POST', body)),
}

export const pageImage = (id, page) => `/api/documents/${id}/pages/${page}/image`
export const sourceFile = (id) => `/api/documents/${id}/file`
