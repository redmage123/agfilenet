import { test, expect, mockJson } from './helpers.js'

const tab = (page, name) => page.getByRole('tab', { name: new RegExp(`^${name} \\(\\d+\\)$`) })
const rows = (page) => page.locator('.doc-table tbody tr')
const fakeDb = (over = {}) => ({
  file: { path: '/var/lib/agfilenet/agfilenet.fs', size: 3 * 1048576, revision: 7 },
  counts: { documents: 0, pages: 0, segments: 0, chunks: 0, index_terms: 0, entities: 0, mentions: 0, matters: 0, judgements: 0, jobs: 0 },
  documents: [], matters: [], entities: [], judgements: [], jobs: [],
  ...over,
})

test.describe('database page', () => {
  test('is reachable from the top bar and shows what the database holds', async ({ page, request, corpus }) => {
    const db = await (await request.get('/api/database')).json()
    await page.goto('/')
    await page.getByRole('navigation').getByRole('link', { name: 'Database' }).click()
    await expect(page).toHaveURL(/\/database$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Database' })).toBeVisible()
    await expect(page.getByText(db.file.path)).toBeVisible()
    const tiles = await page.locator('.tile-n').allTextContents()
    expect(tiles.map(Number)).toEqual(['documents', 'pages', 'segments', 'chunks', 'index_terms', 'entities', 'mentions',
      'matters', 'judgements', 'jobs'].map((k) => db.counts[k]))
    expect(db.counts.documents).toBe(corpus.docs.length)
    await expect(tab(page, 'Documents')).toHaveAttribute('aria-selected', 'true')
    await expect(rows(page)).toHaveCount(corpus.docs.length)
    await expect(page.getByText(`${corpus.docs.length} rows`)).toBeVisible()
  })

  test('the documents view lists every stored field of every file and links to the file', async ({ page, corpus }) => {
    await page.goto('/database')
    await expect(rows(page).first()).toBeVisible()
    const headings = await page.locator('.doc-table th').allTextContents()
    for (const h of ['ID', 'File', 'Path', 'Title', 'Type', 'Date', 'Subject', 'Matter', 'Parties', 'Checks',
      'Corrected by hand', 'Workbook matter', 'Workbook type', 'Pages', 'OCR confidence', 'SHA-256', 'Ingested']) {
      expect(headings).toContain(h)
    }
    const d = corpus.docs[0]
    const row = rows(page).filter({ hasText: d.sha256 })
    await expect(row).toHaveCount(1)
    await expect(row).toContainText(d.path)
    await row.getByRole('link', { name: d.filename }).click()
    await expect(page).toHaveURL(new RegExp(`/documents/${d.id}$`))
  })

  test('each view shows the rows the database returned', async ({ page, request }) => {
    const db = await (await request.get('/api/database')).json()
    await page.goto('/database')
    for (const [label, key, view] of [['Matters', 'matters', 'matters'], ['Names and references', 'entities', 'entities'],
      ['Search judgements', 'judgements', 'judgements'], ['Ingest runs', 'jobs', 'jobs']]) {
      await tab(page, label).click()
      await expect(page).toHaveURL(new RegExp(`view=${view}`))
      await expect(tab(page, label)).toHaveAttribute('aria-selected', 'true')
      await expect(tab(page, label)).toHaveText(`${label} (${db[key].length})`)
      if (db[key].length) await expect(rows(page)).toHaveCount(db[key].length)
      else await expect(page.getByText('Nothing stored yet.')).toBeVisible()
    }
    await page.reload()
    await expect(tab(page, 'Ingest runs')).toHaveAttribute('aria-selected', 'true')
  })

  test('the filter narrows the rows, survives a reload and is cleared by changing view', async ({ page, request }) => {
    const db = await (await request.get('/api/database')).json()
    const e = db.entities[0]
    const expected = db.entities.filter((x) => x.value.toLowerCase().includes(e.value.toLowerCase())).length
    await page.goto('/database?view=entities')
    await page.getByRole('searchbox').fill(e.value.toUpperCase())
    await expect(page.getByText(new RegExp(`^${expected} of ${db.entities.length} rows$`))).toBeVisible()
    await page.reload()
    await expect(page.getByRole('searchbox')).toHaveValue(e.value.toUpperCase())
    await page.getByRole('searchbox').fill('zzzqqqx-no-such-row')
    await expect(page.getByText('No rows match.')).toBeVisible()
    await tab(page, 'Matters').click()
    await expect(page.getByRole('searchbox')).toHaveValue('')
  })

  test('a name links to a search for it and a matter to its files', async ({ page, request }) => {
    const db = await (await request.get('/api/database')).json()
    await page.goto('/database?view=entities')
    await rows(page).first().getByRole('link').click()
    await expect(page).toHaveURL(/\/search\?q=/)
    await expect(page.getByRole('searchbox')).toHaveValue(db.entities[0].value)
    test.skip(!db.matters.length, 'no matters in this corpus')
    await page.goto('/database?view=matters')
    await rows(page).first().getByRole('link').click()
    await expect(page).toHaveURL(/\/documents\?matter=/)
  })

  test('an unknown view in the address falls back to documents', async ({ page }) => {
    await page.goto('/database?view=nonsense')
    await expect(tab(page, 'Documents')).toHaveAttribute('aria-selected', 'true')
  })

  test('display rules: empty database, missing values, judgement and job wording', async ({ page }) => {
    await mockJson(page, '**/api/database', fakeDb())
    await page.goto('/database')
    await expect(page.getByText('Nothing stored yet.')).toBeVisible()
    await expect(page.getByText('3.0 MB')).toBeVisible()
    await mockJson(page, '**/api/database', fakeDb({
      judgements: [
        { query: 'needle', doc_id: 999, document: 'Sample letter', relevant: true, activation: 0.834, created: '2026-01-01T00:00:00+00:00' },
        { query: 'thread', doc_id: 999, document: 'Sample letter', relevant: false, activation: null, created: '2026-01-02T00:00:00+00:00' },
      ],
      jobs: [{ id: 2, status: 'error', total: 10, done: 4, message: 'boom', started: '2026-01-01T00:00:00+00:00', finished: null }],
    }))
    await page.goto('/database?view=judgements')
    await expect(rows(page).nth(0)).toContainText('match')
    await expect(rows(page).nth(0)).toContainText('0.83')
    await expect(rows(page).nth(1)).toContainText('not a match')
    await expect(rows(page).nth(1).locator('td').nth(3)).toHaveText('—')
    await tab(page, 'Ingest runs').click()
    await expect(rows(page).first()).toContainText('4 of 10')
    await expect(rows(page).first().locator('td').last()).toHaveText('—')
  })

  test('shows an error when the database cannot be read', async ({ page }) => {
    await mockJson(page, '**/api/database', { detail: 'database is locked' }, 500)
    await page.goto('/database')
    await expect(page.locator('.error')).toHaveText('database is locked')
  })

  test('the metadata-found page lists each kind of metadata and just the values found', async ({ page, request }) => {
    const db = await (await request.get('/api/database')).json()
    await page.goto('/database')
    await page.getByRole('link', { name: 'See just the metadata items found in the documents.' }).click()
    await expect(page).toHaveURL(/\/database\/found$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Metadata found in the documents' })).toBeVisible()
    const names = ['Titles', 'Document types', 'Dates', 'Subjects', 'Matters', 'Parties', 'People', 'Organisations',
      'Places', 'Court and case numbers', 'File references', 'Registry volumes', 'Topics', 'Checks raised']
    expect(await page.locator('section.card').first().locator('li a').allTextContents()).toEqual(names)
    for (const [name, values] of [
      ['People', db.entities.filter((e) => e.kind === 'person').map((e) => e.value)],
      ['Organisations', db.entities.filter((e) => e.kind === 'org').map((e) => e.value)],
      ['Places', db.entities.filter((e) => e.kind === 'place').map((e) => e.value)],
      ['Topics', db.documents.map((d) => d.topic)],
      ['Document types', db.documents.map((d) => d.doc_type)],
      ['Titles', db.documents.map((d) => d.title)],
    ]) {
      const want = [...new Set(values.filter(Boolean))]
      const section = page.locator('section.card').filter({ has: page.getByRole('heading', { level: 2, name: new RegExp(`^${name} \\d+$`) }) })
      await expect(section.getByRole('heading', { level: 2 })).toHaveText(`${name} ${want.length}`)
      const shown = await section.locator('li').allTextContents()
      expect([...shown].sort()).toEqual([...want].sort())
    }
    await page.getByRole('main').getByRole('link', { name: 'Database' }).first().click()
    await expect(page).toHaveURL(/\/database$/)
  })

  test('the metadata-found page copes with an empty database and a failed load', async ({ page }) => {
    await mockJson(page, '**/api/database', fakeDb())
    await page.goto('/database/found')
    await expect(page.getByText('None found.')).toHaveCount(14)
    await mockJson(page, '**/api/database', { detail: 'database is locked' }, 500)
    await page.reload()
    await expect(page.locator('.error')).toHaveText('database is locked')
  })
})
