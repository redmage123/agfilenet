import { test, expect, mockJson, fakeDoc, PNG, BASE } from './helpers.js'

const card = (page, title) => page.locator('section.card').filter({ has: page.getByRole('heading', { name: title }) })
const field = (page, label) => page.getByLabel(label, { exact: true })

async function mockDoc(page, doc) {
  await mockJson(page, `**/api/documents/${doc.id}`, doc)
  await page.route(`**/api/documents/${doc.id}/pages/*/image`, (route) => route.fulfill({ body: PNG, contentType: 'image/png' }))
}

test.describe('document page', () => {
  test('shows heading, breadcrumb, flags and the five editable fields', async ({ page, corpus }) => {
    const d = corpus.details.find((x) => x.flags.length > 1) || corpus.details[0]
    await page.goto(`/documents/${d.id}`)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(d.title || d.filename)
    await expect(page.locator('.crumbs')).toContainText(d.filename)
    await expect(page.locator('main > p .flag')).toHaveCount(d.flags.length)
    for (const [label, key] of [['Title', 'title'], ['Type', 'doc_type'], ['Date (YYYY-MM-DD)', 'doc_date'], ['Subject', 'subject'], ['Matter', 'matter']]) {
      await expect(field(page, label)).toHaveValue(d[key] || '')
    }
    await expect(page.getByRole('button', { name: 'Save corrections' })).toBeDisabled()
    await page.locator('.crumbs').getByRole('link', { name: 'Documents' }).click()
    await expect(page).toHaveURL(/\/documents$/)
  })

  test('shows parties, type confidence, where the text came from and the file facts', async ({ page, corpus }) => {
    const d = corpus.details.find((x) => x.parties.length && x.doc_type && x.text_source === 'ocr')
    test.skip(!d, 'no OCR file with parties')
    await page.goto(`/documents/${d.id}`)
    const meta = card(page, 'Metadata')
    await expect(meta).toContainText(`Parties: ${d.parties.map(([n, r]) => `${n} (${r})`).join('; ')}`)
    await expect(meta).toContainText(`${Math.round(d.doc_type_conf * 100)}% of typed pages agree`)
    await expect(meta).toContainText(`OCR (mean confidence ${Math.round(d.ocr_conf * 100)}%)`)
    await expect(meta).toContainText(`${d.page_count} pages, ${(d.size / 1024).toFixed(0)} KB`)
    await expect(meta.getByRole('link', { name: d.path })).toHaveAttribute('target', '_blank')
  })

  for (const [source, words] of [['text', 'PDF text layer'], ['mixed', 'text layer and OCR']]) {
    test(`a file whose text came from "${source}" says "${words}"`, async ({ page, corpus }) => {
      const d = corpus.details.find((x) => x.text_source === source)
      test.skip(!d, `no ${source} file in the corpus`)
      await page.goto(`/documents/${d.id}`)
      await expect(card(page, 'Metadata')).toContainText(words)
    })
  }

  test('the file link serves the original document', async ({ page, corpus, request }) => {
    const d = corpus.details[0]
    await page.goto(`/documents/${d.id}`)
    const href = await card(page, 'Metadata').getByRole('link', { name: d.path }).getAttribute('href')
    const res = await request.get(href)
    expect(res.status()).toBe(200)
    expect(res.headers()['content-type']).toContain(d.content_type)
    expect(res.headers()['content-disposition']).toContain('inline')
    expect((await res.body()).length).toBe(d.size)
  })

  test('shows what the workbook declared', async ({ page, corpus }) => {
    const d = corpus.details.find((x) => x.decl_matter && x.decl_doc_type && x.decl_comments) || corpus.details.find((x) => x.decl_matter)
    const blank = corpus.details.find((x) => x.decl_matter && !x.decl_doc_type)
    test.skip(!d, 'no file listed in a workbook')
    await page.goto(`/documents/${d.id}`)
    const box = card(page, 'Declared in the workbook')
    await expect(box).toContainText(d.decl_matter)
    if (d.decl_matter_title) await expect(box).toContainText(d.decl_matter_title)
    if (d.decl_doc_type) await expect(box).toContainText(d.decl_doc_type)
    if (blank) {
      await page.goto(`/documents/${blank.id}`)
      await expect(card(page, 'Declared in the workbook')).toContainText('— (none given)')
    }
  })

  test('editing a field enables Save; saving stores the correction and marks the file', async ({ page, corpus, request }) => {
    const d = corpus.details.find((x) => !x.edited && x.subject) || corpus.details[0]
    const original = d.subject || ''
    await page.goto(`/documents/${d.id}`)
    const save = page.getByRole('button', { name: 'Save corrections' })
    await field(page, 'Subject').fill('E2E corrected subject')
    await expect(save).toBeEnabled()
    await field(page, 'Subject').fill(original)
    await expect(save).toBeDisabled()

    await field(page, 'Subject').fill('E2E corrected subject')
    await field(page, 'Date (YYYY-MM-DD)').fill('1999-12-31')
    await save.click()
    await expect(card(page, 'Metadata').locator('.tag')).toHaveText('corrected by hand')
    await expect(save).toBeDisabled()
    await page.reload()
    await expect(field(page, 'Subject')).toHaveValue('E2E corrected subject')
    await expect(field(page, 'Date (YYYY-MM-DD)')).toHaveValue('1999-12-31')
    const stored = await (await request.get(`/api/documents/${d.id}`)).json()
    expect(stored).toMatchObject({ subject: 'E2E corrected subject', doc_date: '1999-12-31', edited: true, title: d.title })

    await page.goto('/')
    await expect(page.locator('.tile').filter({ hasText: 'manually corrected' }).locator('.tile-n')).not.toHaveText('0')

    // put the values back so later tests see the corpus as it was
    await request.patch(`/api/documents/${d.id}`, { data: { subject: original, doc_date: d.doc_date || '' } })
  })

  test('changing the title updates the heading, and Enter in a field saves', async ({ page, corpus, request }) => {
    const d = corpus.details.find((x) => x.title) || corpus.details[0]
    await page.goto(`/documents/${d.id}`)
    await field(page, 'Title').fill('E2E new title')
    await field(page, 'Title').press('Enter')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('E2E new title')
    await field(page, 'Title').fill('')
    await page.getByRole('button', { name: 'Save corrections' }).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(d.filename)
    await request.patch(`/api/documents/${d.id}`, { data: { title: d.title } })
  })

  test('a date that is not a real date is refused', async ({ page, corpus, request }) => {
    const d = corpus.details[2]
    await page.goto(`/documents/${d.id}`)
    await field(page, 'Date (YYYY-MM-DD)').fill('next tuesday')
    await page.getByRole('button', { name: 'Save corrections' }).click()
    await page.waitForTimeout(1500)
    const stored = await (await request.get(`/api/documents/${d.id}`)).json()
    await request.patch(`/api/documents/${d.id}`, { data: { doc_date: d.doc_date || '' } })
    expect(stored.doc_date).not.toBe('next tuesday')
  })

  test('a failed save keeps what was typed and explains the problem', async ({ page, corpus }) => {
    const d = corpus.details[0]
    await page.route(`**/api/documents/${d.id}`, (route) =>
      route.request().method() === 'PATCH'
        ? route.fulfill({ status: 409, json: { detail: 'an ingest is running; try again when it has finished' } })
        : route.continue())
    await page.goto(`/documents/${d.id}`)
    await field(page, 'Subject').fill('typed but not saved')
    await page.getByRole('button', { name: 'Save corrections' }).click()
    await expect(page.getByText('an ingest is running; try again when it has finished')).toBeVisible()
    await expect(field(page, 'Subject')).toHaveValue('typed but not saved')
  })

  test('the button shows Saving… while the save is in flight', async ({ page, corpus }) => {
    const d = corpus.details[0]
    await page.route(`**/api/documents/${d.id}`, async (route) => {
      if (route.request().method() !== 'PATCH') return route.continue()
      await new Promise((r) => setTimeout(r, 1200))
      return route.fulfill({ json: { ...d, subject: 'slow' } })
    })
    await page.goto(`/documents/${d.id}`)
    await field(page, 'Subject').fill('slow')
    await page.getByRole('button', { name: 'Save corrections' }).click()
    await expect(page.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Save corrections' })).toBeDisabled()
  })

  test('pager moves through the pages, stops at both ends and keeps the page in the address', async ({ page, corpus }) => {
    const d = corpus.details.find((x) => x.pages.length >= 3)
    await page.goto(`/documents/${d.id}`)
    const prev = page.getByRole('button', { name: '‹ Previous' })
    const next = page.getByRole('button', { name: 'Next ›' })
    await expect(page.locator('.pager')).toContainText(`Page 1 of ${d.pages.length}`)
    await expect(prev).toBeDisabled()
    await next.click()
    await expect(page).toHaveURL(/[?&]page=2/)
    await expect(page.locator('.pager')).toContainText(`Page 2 of ${d.pages.length}`)
    await expect(page.locator('.page-view img')).toHaveAttribute('src', `/api/documents/${d.id}/pages/2/image`)
    await prev.click()
    await expect(page.locator('.pager')).toContainText('Page 1 of')
    await page.goto(`/documents/${d.id}?page=${d.pages.length}`)
    await expect(page.locator('.pager')).toContainText(`Page ${d.pages.length} of ${d.pages.length}`)
    await expect(next).toBeDisabled()
    await expect(prev).toBeEnabled()
  })

  for (const bad of ['9999', '0', '-3', 'abc']) {
    test(`a page number of "${bad}" in the address still shows a page`, async ({ page, corpus }) => {
      const d = corpus.details.find((x) => x.pages.length >= 3)
      await page.goto(`/documents/${d.id}?page=${bad}`)
      await expect(page.locator('.pager')).toContainText(/Page \d+ of \d+/)
      await expect(page.locator('.page-view img')).toBeVisible()
    })
  }

  test('the page image loads, and the extracted text sits beside it until hidden', async ({ page, corpus }) => {
    const d = corpus.details.find((x) => x.pages[0].text && x.pages[0].source === 'ocr')
    await page.goto(`/documents/${d.id}`)
    const img = page.locator('.page-view img')
    await expect(img).toHaveAttribute('alt', 'Page 1')
    await expect.poll(() => img.evaluate((el) => el.complete && el.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(100)
    await expect(page.locator('.page-view pre')).toHaveText(d.pages[0].text)
    await expect(page.locator('.toggle')).toContainText(`OCR confidence ${Math.round(d.pages[0].ocr_conf * 100)}%`)
    await page.getByLabel(/Show\s+extracted text/).uncheck()
    await expect(page.locator('.page-view pre')).toHaveCount(0)
    await expect(page.locator('.page-view')).not.toHaveClass(/split/)
    await page.getByLabel(/Show\s+extracted text/).check()
    await expect(page.locator('.page-view pre')).toBeVisible()
  })

  test('page type and rotation are tagged', async ({ page, corpus }) => {
    const typed = corpus.details.find((x) => x.pages[0].page_type)
    await page.goto(`/documents/${typed.id}`)
    await expect(page.locator('.pager .tag').first()).toHaveText(typed.pages[0].page_type)
    const rotated = corpus.details.find((x) => x.pages.some((p) => p.rotation))
    test.skip(!rotated, 'no rotated page in the corpus')
    const p = rotated.pages.find((x) => x.rotation)
    await page.goto(`/documents/${rotated.id}?page=${p.page_no}`)
    await expect(page.locator('.pager')).toContainText(`was rotated ${p.rotation}°`)
  })

  test('a file holding several documents lists them and jumps to each', async ({ page, corpus }) => {
    const d = corpus.details.find((x) => x.segments.length > 1)
    test.skip(!d, 'no bundle in the corpus')
    await page.goto(`/documents/${d.id}`)
    const box = card(page, 'Documents inside this file')
    await expect(box.locator('li')).toHaveCount(d.segments.length)
    const last = d.segments.at(-1)
    await box.locator('li').last().getByRole('button').click()
    await expect(page.locator('.pager')).toContainText(`Page ${last.start_page} of`)
    const single = corpus.details.find((x) => x.segments.length <= 1)
    await page.goto(`/documents/${single.id}`)
    await expect(page.getByRole('heading', { name: 'Documents inside this file' })).toHaveCount(0)
  })

  test('a repeated page says where the same content is and links there', async ({ page, corpus }) => {
    const d = corpus.details.find((x) => x.pages.some((p) => p.dup_doc_id && p.dup_doc_id !== x.id))
    test.skip(!d, 'no page copied from another file')
    const p = d.pages.find((x) => x.dup_doc_id && x.dup_doc_id !== d.id)
    await page.goto(`/documents/${d.id}?page=${p.page_no}`)
    await expect(page.locator('.notice')).toContainText(`Same content as page ${p.dup_page_no} of`)
    await page.locator('.notice').getByRole('link', { name: p.dup_filename }).click()
    await expect(page).toHaveURL(new RegExp(`/documents/${p.dup_doc_id}\\?page=${p.dup_page_no}`))
    await expect(page.locator('.pager')).toContainText(`Page ${p.dup_page_no} of`)

    const source = corpus.details.find((x) => x.id === p.dup_doc_id)
    const box = card(page, 'Duplicates')
    await expect(box.locator('li')).toHaveCount(source.same_file.length + source.copied_into.length)
    const copy = source.copied_into[0]
    await expect(box).toContainText(`${copy.pages} page${copy.pages > 1 ? 's' : ''} repeated in`)
    await box.getByRole('link').first().click()
    await expect(page).toHaveURL(new RegExp(`/documents/${source.same_file[0]?.id ?? copy.id}$`))
  })

  test('names and references found in the text are grouped and open a search', async ({ page, corpus }) => {
    const d = corpus.details.find((x) => x.entities.some((e) => e.docs > 1) && new Set(x.entities.map((e) => e.kind)).size > 1)
    await page.goto(`/documents/${d.id}`)
    const box = card(page, 'Found in the text')
    await expect(box.locator('.chip')).toHaveCount(d.entities.length)
    await expect(box.locator('h3')).toHaveCount(new Set(d.entities.map((e) => e.kind)).size)
    const shared = d.entities.find((e) => e.docs > 1)
    const chip = box.locator('.chip').filter({ hasText: shared.value }).filter({ hasText: `${shared.docs} files` }).first()
    await chip.click()
    await expect(page).toHaveURL(/\/search\?q=/)
    await expect(page.getByRole('searchbox')).toHaveValue(shared.value)
    await expect(page.locator('.result').first()).toBeVisible({ timeout: 30_000 })
  })

  test('related documents explain what they share and can be opened', async ({ page, corpus }) => {
    const d = corpus.details.find((x) => x.related.length)
    test.skip(!d, 'no related documents')
    await page.goto(`/documents/${d.id}`)
    const box = card(page, 'Related documents')
    await expect(box.locator('li')).toHaveCount(d.related.length)
    await expect(box.locator('li').first()).toContainText(`shares ${d.related[0].shared.join(', ')}`)
    await box.getByRole('link').first().click()
    await expect(page).toHaveURL(new RegExp(`/documents/${d.related[0].id}$`))
    const other = corpus.details.find((x) => x.id === d.related[0].id)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(other.title || other.filename)
    await expect(page.getByLabel('Title', { exact: true })).toHaveValue(other.title || '')
  })

  test('branches the real files may not exercise: no workbook entry, identical copy, repeat within the file, blank page', async ({ page }) => {
    const doc = fakeDoc()
    await mockDoc(page, doc)
    await page.goto('/documents/999')
    await expect(card(page, 'Declared in the workbook')).toContainText('This file is not listed in a migration workbook.')
    await expect(card(page, 'Duplicates')).toContainText('Identical file: copy-of-sample.pdf')
    await expect(card(page, 'Metadata')).toContainText('text layer and OCR (mean confidence 91%)')
    await expect(page.locator('.flag').filter({ hasText: 'made-up-flag' })).toBeVisible()
    await expect(page.locator('.page-view pre')).toHaveText('(no text found on this page)')
    await expect(page.locator('.pager')).toContainText('was rotated 90°')
    await expect(page.locator('.toggle')).toContainText('OCR confidence 80%')
    await expect(page.getByRole('heading', { name: 'Documents inside this file' })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Found in the text' })).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'Related documents' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Next ›' }).click()
    await expect(page.locator('.notice')).toHaveText('Same content as page 1 of this file.')
    await expect(page.locator('.toggle')).not.toContainText('OCR confidence')
    await expect(page.locator('.pager .tag')).toHaveCount(0)
  })

  test('shows the summary, the topic and the type of similar files, which one click puts in the form', async ({ page }) => {
    await mockDoc(page, fakeDoc({
      summary: 'The first representative sentence. The second one.', topic: 'needle, thread', suggested_type: 'Memorandum',
      suggested_conf: 0.82,
      entities: [{ kind: 'person', value: 'Alex Example', count: 3, first_page: 1, docs: 2, aliases: ['A. Example', 'Alex Exampel'] },
                 { kind: 'place', value: 'Sampletown', count: 1, first_page: 2, docs: 1, aliases: [] }],
    }))
    await page.goto('/documents/999')
    await expect(card(page, 'Summary')).toContainText('The first representative sentence. The second one.')
    await expect(card(page, 'Metadata').getByRole('link', { name: 'needle, thread' })).toHaveAttribute('href', '/documents?topic=needle%2C%20thread')
    await expect(page.locator('.suggestion')).toContainText('The files most like this one are of type Memorandum (82% agreement).')
    await expect(page.getByRole('button', { name: 'Save corrections' })).toBeDisabled()
    await page.getByRole('button', { name: 'Use this type' }).click()
    await expect(page.getByLabel('Type', { exact: true })).toHaveValue('Memorandum')
    await expect(page.getByRole('button', { name: 'Save corrections' })).toBeEnabled()   // nothing is saved until asked
    await expect(page.getByRole('button', { name: 'Use this type' })).toHaveCount(0)
    const found = card(page, 'Found in the text')
    await expect(found.getByRole('heading', { name: 'Places' })).toBeVisible()
    await expect(found.locator('.chip').first()).toContainText('+2 spellings')
    await expect(found.locator('.chip').first()).toHaveAttribute('title', 'Also written: A. Example; Alex Exampel')
    await expect(found.locator('.chip').nth(1)).not.toContainText('spelling')
  })

  test('no summary, topic or suggestion: none of them is shown, and a corrected file gets no suggestion', async ({ page }) => {
    await mockDoc(page, fakeDoc())
    await page.goto('/documents/999')
    await expect(page.getByRole('heading', { name: 'Summary' })).toHaveCount(0)
    await expect(page.locator('.suggestion')).toHaveCount(0)
    await expect(card(page, 'Metadata')).not.toContainText('Topic')
    await mockDoc(page, fakeDoc({ edited: true, suggested_type: 'Memorandum', suggested_conf: 0.9 }))
    await page.reload()
    await expect(card(page, 'Metadata')).toContainText('corrected by hand')
    await expect(page.locator('.suggestion')).toHaveCount(0)
  })

  test('an untyped, untitled file with no parties still renders', async ({ page }) => {
    await mockDoc(page, fakeDoc({ title: null, doc_type: null, parties: [], same_file: [], text_source: 'text', ocr_conf: null, flags: [] }))
    await page.goto('/documents/999')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('sample.pdf')
    await expect(card(page, 'Metadata')).toContainText('not identified')
    await expect(card(page, 'Metadata')).toContainText('PDF text layer')
    await expect(card(page, 'Metadata')).not.toContainText('Parties:')
    await expect(card(page, 'Metadata')).not.toContainText('mean confidence')
    await expect(page.getByRole('heading', { name: 'Duplicates' })).toHaveCount(0)
  })

  test('a file that could not be read says why', async ({ page }) => {
    await mockDoc(page, fakeDoc({ pages: [], page_count: 0, status: 'error', error: 'broken PDF', segments: [] }))
    await page.goto('/documents/999')
    await expect(page.getByText('This file has no readable pages: broken PDF')).toBeVisible()
    await mockDoc(page, fakeDoc({ pages: [], page_count: 0, error: null, segments: [] }))
    await page.reload()
    await expect(page.getByText('This file has no readable pages.')).toBeVisible()
  })

  test('a document that does not exist is reported, with a way back', async ({ page }) => {
    await page.goto('/documents/99999999')
    await expect(page.locator('.error')).toHaveText('document not found')
    await expect(page.getByRole('main').getByRole('link', { name: /documents/i })).toBeVisible()
  })

  test('a document address that is not a number is reported', async ({ page }) => {
    await page.goto('/documents/not-a-number')
    await expect(page.locator('.error')).toBeVisible()
    await expect(page.locator('.error')).not.toContainText('[object Object]')
  })

  test('a page image that fails to load does not leave a bare broken image', async ({ page, corpus }) => {
    const d = corpus.details[0]
    await page.route('**/pages/*/image', (route) => route.fulfill({ status: 404, json: { detail: 'source file is missing' } }))
    await page.goto(`/documents/${d.id}`)
    await expect(page.locator('.detail-pages')).toContainText(/could not|missing|unavailable/i)
  })
})

test('page images are cached by the browser and refuse pages outside the file', async ({ request, corpus }) => {
  const d = corpus.details[0]
  const ok = await request.get(`${BASE}/api/documents/${d.id}/pages/1/image`)
  expect(ok.status()).toBe(200)
  expect(ok.headers()['content-type']).toBe('image/png')
  expect(ok.headers()['cache-control']).toContain('max-age')
  for (const n of [0, d.page_count + 1]) {
    expect((await request.get(`${BASE}/api/documents/${d.id}/pages/${n}/image`)).status()).toBe(404)
  }
})
