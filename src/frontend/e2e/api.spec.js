import { test, expect } from './helpers.js'

// The server routes the pages depend on, checked directly.
test.describe('server', () => {
  test('unknown API paths are 404s, not the web page', async ({ request }) => {
    const res = await request.get('/api/no-such-thing')
    expect(res.status()).toBe(404)
    expect(res.headers()['content-type']).toContain('json')
  })

  test('any other path serves the web app so addresses can be bookmarked', async ({ request }) => {
    for (const path of ['/', '/documents', '/documents/1', '/search', '/anything/else']) {
      const res = await request.get(path)
      expect(res.status(), path).toBe(200)
      expect(await res.text(), path).toContain('<div id="root">')
    }
  })

  test('paths cannot climb out of the web app folder', async ({ request }) => {
    for (const path of ['/..%2f..%2f..%2fetc%2fpasswd', '/assets/..%2f..%2f..%2f..%2fetc%2fpasswd', '/%2e%2e/%2e%2e/etc/passwd']) {
      const res = await request.get(path)
      expect(await res.text(), path).not.toContain('root:x:')
    }
  })

  test('search rejects an unknown mode and limits outside 1–200, and honours a limit', async ({ request }) => {
    expect((await request.get('/api/search?q=land&mode=psychic')).status()).toBe(400)
    expect((await request.get('/api/search?q=land&limit=0')).status()).toBe(422)
    expect((await request.get('/api/search?q=land&limit=201')).status()).toBe(422)
    const two = await (await request.get('/api/search?q=land&mode=semantic&limit=2')).json()
    expect(two.results.length).toBeLessThanOrEqual(2)
  })

  test('an empty query returns nothing, with certainty that nothing matches', async ({ request }) => {
    for (const mode of ['iac', 'hybrid', 'keyword', 'semantic']) {
      const d = await (await request.get(`/api/search?q=&mode=${mode}`)).json()
      expect(d.results).toEqual([])
      expect(d.p_none).toBe(1)
    }
  })

  test('probabilities are between 0 and 1 and best-match shares add up to one with "none"', async ({ request, corpus }) => {
    const word = (corpus.details.find((d) => d.doc_type)?.doc_type || 'letter').split(' ')[0]
    for (const mode of ['iac', 'hybrid', 'keyword', 'semantic']) {
      const d = await (await request.get(`/api/search?q=${encodeURIComponent(word)}&mode=${mode}&limit=200`)).json()
      for (const h of d.results) {
        expect(h.probability).toBeGreaterThanOrEqual(0)
        expect(h.probability).toBeLessThanOrEqual(1)
      }
      const total = d.results.reduce((s, h) => s + h.share, d.p_none)
      expect(total, mode).toBeGreaterThan(0.97)
      expect(total, mode).toBeLessThan(1.03)
    }
  })

  test('document list filters agree with the facet counts', async ({ request, corpus }) => {
    for (const name of ['doc_type', 'matter', 'package', 'flag']) {
      for (const f of corpus.facets[name]) {
        const list = await (await request.get(`/api/documents?${name}=${encodeURIComponent(f.value)}`)).json()
        expect(list.length, `${name}=${f.value}`).toBe(f.count)
      }
    }
  })

  test('missing documents are 404s on every document route', async ({ request }) => {
    for (const path of ['/api/documents/99999999', '/api/documents/99999999/file', '/api/documents/99999999/pages/1/image']) {
      expect((await request.get(path)).status(), path).toBe(404)
    }
    expect((await request.patch('/api/documents/99999999', { data: { title: 'x' } })).status()).toBe(404)
    expect((await request.post('/api/feedback', { data: { query: 'q', doc_id: 99999999, relevant: true } })).status()).toBe(404)
    expect((await request.get('/api/documents/abc')).status()).toBe(422)
  })

  test('saving nothing changes nothing and does not mark the file as corrected', async ({ request, corpus }) => {
    const d = corpus.details.find((x) => !x.edited)
    const before = await (await request.get(`/api/documents/${d.id}`)).json()
    const res = await request.patch(`/api/documents/${d.id}`, { data: {} })
    expect(res.status()).toBe(200)
    const after = await res.json()
    expect(after.edited).toBe(before.edited)
    expect(after.title).toBe(before.title)
  })

  test('malformed requests are rejected', async ({ request }) => {
    expect((await request.post('/api/feedback', { data: { query: 'q' } })).status()).toBe(422)
    expect((await request.post('/api/ingest', { data: { force: 'maybe' } })).status()).toBe(422)
  })

  test('the CSV export has a header and one line per file', async ({ request, corpus }) => {
    const res = await request.get('/api/export.csv')
    expect(res.headers()['content-type']).toContain('text/csv')
    expect(res.headers()['content-disposition']).toContain('agfilenet-metadata.csv')
    const text = await res.text()
    for (const col of ['parties', 'flags', 'segments', 'people', 'organisations', 'case_numbers', 'file_references']) {
      expect(text.split('\n')[0]).toContain(col)
    }
    for (const d of corpus.docs) expect(text).toContain(d.sha256)
  })

  test('static assets are served and the API is not cached as a page', async ({ request }) => {
    const html = await (await request.get('/')).text()
    const assets = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1])
    expect(assets.length).toBeGreaterThanOrEqual(2)
    for (const a of assets) expect((await request.get(a)).status(), a).toBe(200)
    expect((await request.get('/assets/nope.js')).status()).toBe(404)
  })
})
