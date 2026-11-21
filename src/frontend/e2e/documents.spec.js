import { test, expect, mockJson, fakeDoc } from './helpers.js'

const rows = (page) => page.locator('.doc-table tbody tr')
// the label element also contains its options' text, so match on how it starts
const select = (page, label) => page.locator('.filters label').filter({ hasText: new RegExp(`^${label}`) }).locator('select')

test.describe('document list', () => {
  test('lists every file, sorted by package, folder and file name', async ({ page, corpus }) => {
    await page.goto('/documents')
    await expect(page.getByText(`${corpus.docs.length} documents`)).toBeVisible()
    await expect(rows(page)).toHaveCount(corpus.docs.length)
    const names = await rows(page).locator('td:first-child .sub').evaluateAll((els) => els.map((e) => e.firstChild.textContent.trim()))
    expect(names).toEqual(corpus.docs.map((d) => d.filename))
    await expect(page.getByRole('button', { name: 'Clear' })).toHaveCount(0)
  })

  test('each row shows title, type, date, matter and page count', async ({ page, corpus }) => {
    await page.goto('/documents')
    for (const d of [corpus.docs[0], corpus.docs.at(-1)]) {
      const row = rows(page).filter({ hasText: d.filename }).first()
      await expect(row.getByRole('link')).toHaveText(d.title || d.filename)
      await expect(row.locator('td').nth(1)).toContainText(d.doc_type || '—')
      await expect(row.locator('td').nth(2)).toHaveText(d.doc_date || '—')
      await expect(row.locator('td').nth(3)).toHaveText(d.matter || '')
      await expect(row.locator('td').nth(5)).toHaveText(String(d.page_count))
    }
  })

  test('shows the workbook type when it differs, and a dash where type or date is unknown', async ({ page, corpus }) => {
    await page.goto('/documents')
    const differs = corpus.docs.find((d) => d.decl_doc_type && d.decl_doc_type !== d.doc_type)
    const same = corpus.docs.find((d) => d.decl_doc_type && d.decl_doc_type === d.doc_type)
    const untyped = corpus.docs.find((d) => !d.doc_type)
    test.skip(!differs || !same || !untyped, 'corpus lacks one of the cases')
    await expect(rows(page).filter({ hasText: differs.filename }).first()).toContainText(`workbook: ${differs.decl_doc_type}`)
    await expect(rows(page).filter({ hasText: same.filename }).first()).not.toContainText('workbook:')
    await expect(rows(page).filter({ hasText: untyped.filename }).first().locator('td').nth(1)).toContainText('—')
  })

  test('flags are shown in plain words, with personal data marked out', async ({ page, corpus }) => {
    const doc = corpus.docs.find((d) => d.flags.some((f) => f.startsWith('pii')) && d.flags.includes('bundle'))
      || corpus.docs.find((d) => d.flags.some((f) => f.startsWith('pii')))
    test.skip(!doc, 'no file with personal data flags')
    await page.goto('/documents')
    const row = rows(page).filter({ hasText: doc.filename }).first()
    await expect(row.locator('.flag')).toHaveCount(doc.flags.length)
    await expect(row.locator('.flag-pii')).toHaveCount(doc.flags.filter((f) => /^(pii|sensitive)/.test(f)).length)
    await expect(row.locator('.flags')).not.toContainText('pii:')
  })

  for (const [name, label] of [['doc_type', 'Type'], ['matter', 'Matter'], ['topic', 'Topic'], ['flag', 'Check'], ['package', 'Package']]) {
    test(`the ${label} filter offers every value with its count and narrows the list`, async ({ page, corpus }) => {
      await page.goto('/documents')
      const facet = corpus.facets[name]
      const options = select(page, label).locator('option')
      await expect(options).toHaveCount(facet.length + (name === 'doc_type' ? 2 : 1))
      for (const f of facet.slice(0, 3)) {
        await select(page, label).selectOption(f.value)
        await expect(page).toHaveURL(new RegExp(`[?&]${name}=`))
        await expect(page.getByText(`${f.count} documents`)).toBeVisible()
        await expect(rows(page)).toHaveCount(f.count)
        await expect(select(page, label).locator('option:checked')).toContainText(`(${f.count})`)
      }
      await select(page, label).selectOption('')
      await expect(rows(page)).toHaveCount(corpus.docs.length)
      await expect(page).not.toHaveURL(new RegExp(`[?&]${name}=`))
    })
  }

  test('"(not identified)" lists the files the app could not type', async ({ page, corpus }) => {
    await page.goto('/documents')
    await select(page, 'Type').selectOption('(none)')
    await expect(rows(page)).toHaveCount(corpus.docs.filter((d) => !d.doc_type).length)
  })

  test('the Check filter uses plain-word labels', async ({ page }) => {
    await page.goto('/documents')
    await expect(select(page, 'Check').locator('option').nth(1)).toBeAttached()
    const labels = await select(page, 'Check').locator('option').allTextContents()
    expect(labels.length).toBeGreaterThan(1)
    expect(labels.filter((l) => /^(pii|sensitive):|^[a-z]+-[a-z]+/.test(l))).toEqual([])
  })

  test('the text box filters by title, file name or matter as you type, ignoring case', async ({ page, corpus }) => {
    await page.goto('/documents')
    const box = page.getByPlaceholder('Filter by title, file name or matter')
    const target = corpus.docs.find((d) => d.filename.length > 8)
    const needle = target.filename.slice(0, 8)
    const matches = (q) => corpus.docs.filter((d) => [d.title, d.filename, d.matter].some((v) => (v || '').toLowerCase().includes(q.toLowerCase())))
    await box.fill(needle.toUpperCase())
    await expect(rows(page)).toHaveCount(matches(needle).length)
    await expect(rows(page).filter({ hasText: target.filename }).first()).toBeVisible()
    await expect(page).toHaveURL(/[?&]q=/)
    await expect(box).toBeFocused()
  })

  test('the filter menus recount as the list narrows, and values with nothing behind them cannot be picked', async ({ page, corpus, request }) => {
    // a word from a title that leaves some document types with nothing
    const words = [...new Set(corpus.docs.flatMap((d) => (d.title || '').toLowerCase().match(/[a-z]{5,}/g) || []))]
    let needle, facets
    for (const word of words) {
      const f = await (await request.get('/api/facets', { params: { q: word } })).json()
      if (f.doc_type.some((t) => t.count === 0) && f.doc_type.some((t) => t.count > 0)) {
        needle = word
        facets = f
        break
      }
    }
    expect(needle, 'a title word that narrows the document types').toBeTruthy()
    await page.goto('/documents')
    await page.getByPlaceholder('Filter by title, file name or matter').fill(needle)
    const type = select(page, 'Type')
    const empty = facets.doc_type.find((t) => t.count === 0)
    const full = facets.doc_type.find((t) => t.count > 0)
    await expect(type.locator('option', { hasText: `${empty.value} (0)` }).first()).toHaveAttribute('disabled', '')
    for (const [name, label] of [['doc_type', 'Type'], ['matter', 'Matter'], ['package', 'Package']]) {
      const shown = (await select(page, label).locator('option').allTextContents()).filter((t) => /\(\d+\)$/.test(t))
      expect(shown).toEqual(facets[name].map((f) => `${f.value} (${f.count})`))
    }
    await type.selectOption(full.value)
    await expect(rows(page)).toHaveCount(full.count)
    // its own menu still shows the alternatives; the other menus now count within the chosen type
    await expect(type.locator('option:checked')).toHaveText(`${full.value} (${full.count})`)
    const within = await (await request.get('/api/facets', { params: { q: needle, doc_type: full.value } })).json()
    await expect(select(page, 'Matter').locator('option').nth(1)).toHaveText(`${within.matter[0].value} (${within.matter[0].count})`)
    expect(within.matter.reduce((n, m) => n + m.count, 0)).toBeLessThanOrEqual(full.count)
    await page.getByRole('button', { name: 'Clear' }).click()
    await expect(type.locator('option', { hasText: `${empty.value} (0)` })).toHaveCount(0)
    await expect(type.locator('option:disabled')).toHaveCount(0)
  })

  test('filters combine, survive a reload, and Clear removes them all', async ({ page, corpus }) => {
    const flag = corpus.facets.flag[0].value
    const pkg = corpus.facets.package[0].value
    const expected = corpus.docs.filter((d) => d.flags.includes(flag) && d.package === pkg).length
    await page.goto('/documents')
    await select(page, 'Check').selectOption(flag)
    await select(page, 'Package').selectOption(pkg)
    await expect(rows(page)).toHaveCount(expected)
    await page.reload()
    await expect(select(page, 'Check')).toHaveValue(flag)
    await expect(select(page, 'Package')).toHaveValue(pkg)
    await expect(rows(page)).toHaveCount(expected)
    await page.getByRole('button', { name: 'Clear' }).click()
    await expect(page).toHaveURL(/\/documents$/)
    await expect(rows(page)).toHaveCount(corpus.docs.length)
    await expect(select(page, 'Check')).toHaveValue('')
  })

  test('says so when nothing matches', async ({ page }) => {
    await page.goto('/documents?q=zzzz-no-such-file-qqqq')
    await expect(page.getByText('No documents match.')).toBeVisible()
    await expect(page.locator('.doc-table')).toHaveCount(0)
    await expect(page.getByPlaceholder('Filter by title, file name or matter')).toHaveValue('zzzz-no-such-file-qqqq')
  })

  test('a title opens the document', async ({ page, corpus }) => {
    const d = corpus.docs[1]
    await page.goto('/documents')
    await rows(page).filter({ hasText: d.filename }).first().getByRole('link').click()
    await expect(page).toHaveURL(new RegExp(`/documents/${d.id}$`))
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(d.title || d.filename)
  })

  test('a file with no title is listed under its file name', async ({ page }) => {
    await mockJson(page, '**/api/documents?*', [fakeDoc({ title: null, doc_type: null, doc_date: null, flags: [] })])
    await mockJson(page, '**/api/documents', [fakeDoc({ title: null, doc_type: null, doc_date: null, flags: [] })])
    await page.goto('/documents')
    await expect(rows(page).getByRole('link')).toHaveText('sample.pdf')
    await expect(rows(page).locator('.flags')).toHaveCount(0)
  })

  test('shows the server message when the list cannot be loaded', async ({ page }) => {
    await mockJson(page, '**/api/documents?*', { detail: 'database is busy' }, 503)
    await mockJson(page, '**/api/documents', { detail: 'database is busy' }, 503)
    await page.goto('/documents')
    await expect(page.locator('.error')).toHaveText('database is busy')
  })

  test('shows an error when the filter values cannot be loaded', async ({ page }) => {
    await page.route('**/api/facets*', (route) => route.fulfill({ status: 500, body: 'oops' }))
    await page.goto('/documents')
    await expect(page.locator('.error')).toBeVisible()
  })
})
