import { test as base, expect } from '@playwright/test'

export { expect }

export const BASE = process.env.E2E_BASE_URL || 'http://127.0.0.1:8000'

// Tests never name a real file, person or reference: whatever they need is
// looked up from the running app, so the suite works on any ingested corpus.
export const test = base.extend({
  corpus: [
    async ({ playwright }, use) => {
      const api = await playwright.request.newContext({ baseURL: BASE })
      const get = async (path) => (await api.get(path)).json()
      const docs = await get('/api/documents')
      const details = []
      for (const d of docs) details.push(await get(`/api/documents/${d.id}`))
      await use({ status: await get('/api/status'), facets: await get('/api/facets'), docs, details })
      await api.dispose()
    },
    { scope: 'worker' },
  ],
})

export const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)

export const mockJson = (page, url, json, status = 200) =>
  page.route(url, (route) => route.fulfill({ status, json }))

export const fakeStatus = (over = {}) => ({
  data_dir: '/data',
  files_found: 3,
  counts: { documents: 3, pages: 12, errors: 0, untyped: 1, undeclared_type: 2, edited: 0 },
  flags: { bundle: 2, 'pii:passport': 1 },
  entities: 9,
  duplicate_pages: 4,
  job: null,
  ...over,
})

export const fakeDoc = (over = {}) => ({
  id: 999,
  filename: 'sample.pdf',
  path: 'Package/Folder/sample.pdf',
  package: 'Package',
  folder: 'Folder',
  size: 20480,
  content_type: 'application/pdf',
  page_count: 2,
  text_source: 'mixed',
  ocr_conf: 0.91,
  status: 'ok',
  error: null,
  title: 'Sample letter',
  doc_type: 'Letter',
  doc_type_conf: 0.5,
  doc_date: '2020-01-02',
  subject: 'A subject',
  matter: 'M-1',
  edited: false,
  decl_matter: null,
  decl_matter_title: null,
  decl_reference: null,
  decl_doc_type: null,
  decl_comments: null,
  sha256: 'ab'.repeat(32),
  flags: ['rotated-pages', 'made-up-flag'],
  parties: [['Alex Example', 'Plaintiff']],
  pages: [
    { page_no: 1, text: '', source: 'ocr', ocr_conf: 0.8, rotation: 90, page_type: 'Letter', is_start: true,
      dup_doc_id: null, dup_page_no: null, dup_filename: null },
    { page_no: 2, text: 'Second page text', source: 'text', ocr_conf: null, rotation: 0, page_type: null,
      is_start: false, dup_doc_id: 999, dup_page_no: 1, dup_filename: 'sample.pdf' },
  ],
  segments: [{ start_page: 1, end_page: 2, doc_type: 'Letter' }],
  entities: [],
  same_file: [{ id: 998, filename: 'copy-of-sample.pdf', path: 'Package/copy-of-sample.pdf' }],
  copied_into: [],
  related: [],
  ...over,
})

export const fakeHit = (over = {}) => ({
  id: 999,
  filename: 'sample.pdf',
  title: 'Sample letter',
  doc_type: 'Letter',
  doc_date: '2020-01-02',
  matter: 'M-1',
  page_count: 2,
  flags: ['pii:passport', 'bundle'],
  score: 0.9,
  probability: 0.9,
  share: 0.6,
  keyword_score: 4.2,
  semantic_score: 0.71,
  activation: 0.83,
  page: 2,
  snippet: 'before [[needle]] after',
  matched_text: true,
  why: [{ kind: 'term', label: 'needle', in_query: true, input: 0.4 }],
  ...over,
})

export const fakeSearch = (over = {}) => ({
  query: 'needle',
  mode: 'iac',
  results: [fakeHit()],
  p_none: 0.12,
  network: {
    units: 40, documents: 3, cycles: 57, settled: true, unknown_terms: [],
    active_units: [
      { kind: 'term', label: 'needle', activation: 0.8, in_query: true },
      { kind: 'doc', label: 'Sample letter', activation: -0.1, in_query: false },
    ],
    params: {},
  },
  calibration: { fitted: false, judgements: 3, needed: 20 },
  ...over,
})

/** Fail the test on any uncaught page error or console error. */
export function watchConsole(page) {
  const problems = []
  page.on('pageerror', (e) => problems.push(String(e)))
  page.on('console', (m) => m.type() === 'error' && problems.push(m.text()))
  return problems
}
