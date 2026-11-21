import { test, expect, mockJson, fakeStatus } from './helpers.js'

const tile = (page, label) => page.locator('.tile').filter({ has: page.getByText(label, { exact: true }) })

test.describe('overview', () => {
  test('shows the figures the server reports', async ({ page, corpus }) => {
    const s = corpus.status
    await page.goto('/')
    await expect(page.getByText(`${s.files_found} files found, ${s.counts.documents} ingested`)).toBeVisible()
    await expect(page.locator('code')).toHaveText(s.data_dir)
    for (const [label, n] of [
      ['files', s.counts.documents],
      ['pages', s.counts.pages],
      ['duplicate pages', s.duplicate_pages],
      ['files with no type in the workbook', s.counts.undeclared_type],
      ['files the app could not type', s.counts.untyped],
      ['people, bodies and references', s.entities],
      ['unreadable files', s.counts.errors],
    ]) {
      await expect(tile(page, label).locator('.tile-n')).toHaveText(String(n))
    }
    await expect(page.locator('.tile')).toHaveCount(8)
  })

  test('tiles that are links open the matching document list', async ({ page, corpus }) => {
    await page.goto('/')
    await tile(page, 'files').click()
    await expect(page).toHaveURL(/\/documents$/)
    await expect(page.getByText(`${corpus.docs.length} documents`)).toBeVisible()

    await page.goto('/')
    await tile(page, 'duplicate pages').click()
    await expect(page).toHaveURL(/flag=duplicate-pages/)
    const withDup = corpus.docs.filter((d) => d.flags.includes('duplicate-pages')).length
    await expect(page.getByText(`${withDup} documents`)).toBeVisible()

    await page.goto('/')
    await tile(page, 'files the app could not type').click()
    await expect(page).toHaveURL(/doc_type=(\(none\)|%28none%29)/)
    await expect(page.getByText(`${corpus.status.counts.untyped} documents`)).toBeVisible()
  })

  test('the checklist lists every flag, largest first, and links to the files', async ({ page, corpus }) => {
    await page.goto('/')
    const items = page.locator('.flaglist li')
    const flags = Object.entries(corpus.status.flags)
    await expect(items).toHaveCount(flags.length)
    const counts = (await items.locator('strong').allTextContents()).map(Number)
    expect(counts).toEqual([...counts].sort((a, b) => b - a))
    expect(await items.allTextContents()).not.toContainEqual(expect.stringMatching(/^\d+ (pii|sensitive):/))

    const first = flags.sort((a, b) => b[1] - a[1])[0]
    await items.first().getByRole('link').click()
    await expect(page).toHaveURL(/\/documents\?flag=/)
    await expect(page.getByText(new RegExp(`^\\d+ documents$`))).toHaveText(new RegExp(`^(${first[1]}|\\d+) documents$`))
  })

  test('the metadata download is a CSV with one row per file', async ({ page, corpus }) => {
    await page.goto('/')
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('link', { name: 'Download metadata (CSV)' }).click(),
    ])
    expect(download.suggestedFilename()).toBe('agfilenet-metadata.csv')
    const stream = await download.createReadStream()
    let text = ''
    for await (const chunk of stream) text += chunk
    expect(text.split('\n')[0]).toContain('path,filename,page_count,matter,title,doc_type')
    for (const d of corpus.docs.slice(0, 5)) expect(text).toContain(d.sha256)
    expect(text.match(/\b[0-9a-f]{64}\b/g).length).toBe(corpus.docs.length)
  })

  test('ingesting new or changed files runs to completion and leaves the figures unchanged', async ({ page, corpus }) => {
    test.setTimeout(300_000)
    await page.goto('/')
    const button = page.getByRole('button', { name: 'Ingest new or changed files' })
    await button.click()
    await expect(page.locator('.job')).toContainText(/done: Ingested \d+ files, \d+ pages/, { timeout: 240_000 })
    await expect(button).toBeEnabled()
    await expect(page.locator('.job .bar-fill')).toHaveAttribute('style', /width: 100%/)
    await expect(tile(page, 'files').locator('.tile-n')).toHaveText(String(corpus.status.counts.documents))
    await expect(tile(page, 'pages').locator('.tile-n')).toHaveText(String(corpus.status.counts.pages))
    await expect(tile(page, 'people, bodies and references').locator('.tile-n')).toHaveText(String(corpus.status.entities))
  })

  test('the two ingest buttons ask the server for the right kind of run', async ({ page }) => {
    const bodies = []
    await mockJson(page, '**/api/status', fakeStatus())
    await page.route('**/api/ingest', (route) => {
      bodies.push(route.request().postDataJSON())
      return route.fulfill({ json: { job_id: 1 } })
    })
    page.on('dialog', (d) => d.accept()) // the confirmation before re-reading everything
    await page.goto('/')
    await page.getByRole('button', { name: 'Ingest new or changed files' }).click()
    await page.getByRole('button', { name: 'Re-read everything' }).click()
    await expect.poll(() => bodies).toEqual([{ force: false }, { force: true }])
  })

  test('before anything is ingested the button says Start ingest and the checklist is empty', async ({ page }) => {
    await mockJson(page, '**/api/status', fakeStatus({
      files_found: 5, flags: {}, entities: 0, duplicate_pages: 0,
      counts: { documents: 0, pages: 0, errors: 0, untyped: 0, undeclared_type: 0, edited: 0 },
    }))
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Start ingest' })).toBeEnabled()
    await expect(page.getByText('Nothing flagged yet.')).toBeVisible()
    await expect(page.locator('.job')).toHaveCount(0)
  })

  test('while a job runs the buttons are disabled and progress is shown', async ({ page }) => {
    await mockJson(page, '**/api/status', fakeStatus({
      job: { id: 1, status: 'running', total: 200, done: 50, message: 'Reading pages', started: 'x', finished: null },
    }))
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Ingest new or changed files' })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Re-read everything' })).toBeDisabled()
    await expect(page.locator('.job')).toContainText('running: Reading pages — page 50 of 200')
    await expect(page.locator('.job .bar-fill')).toHaveAttribute('style', /width: 25%/)
  })

  test('a queued job with no page count yet shows an empty bar', async ({ page }) => {
    await mockJson(page, '**/api/status', fakeStatus({
      job: { id: 1, status: 'queued', total: 0, done: 0, message: null, started: 'x', finished: null },
    }))
    await page.goto('/')
    await expect(page.getByRole('button', { name: 'Re-read everything' })).toBeDisabled()
    await expect(page.locator('.job .bar-fill')).toHaveAttribute('style', /width: 0%/)
    await expect(page.locator('.job')).not.toContainText('null')
  })

  test('a failed job is shown as an error and can be retried', async ({ page }) => {
    await mockJson(page, '**/api/status', fakeStatus({
      job: { id: 1, status: 'error', total: 10, done: 4, message: "RuntimeError('boom')", started: 'x', finished: 'y' },
    }))
    await page.goto('/')
    await expect(page.locator('.job .error')).toContainText("error: RuntimeError('boom')")
    await expect(page.getByRole('button', { name: 'Ingest new or changed files' })).toBeEnabled()
  })

  test('an interrupted job is reported and can be resumed', async ({ page }) => {
    await mockJson(page, '**/api/status', fakeStatus({
      job: { id: 1, status: 'interrupted', total: 10, done: 4, message: 'Interrupted - run ingest again to resume',
        started: 'x', finished: null },
    }))
    await page.goto('/')
    await expect(page.locator('.job')).toContainText('interrupted: Interrupted - run ingest again to resume')
    await expect(page.getByRole('button', { name: 'Ingest new or changed files' })).toBeEnabled()
  })

  test('the page refreshes itself every few seconds', async ({ page }) => {
    let n = 0
    await page.route('**/api/status', (route) => {
      n += 1
      return route.fulfill({ json: fakeStatus({ files_found: n > 2 ? 77 : 3 }) })
    })
    await page.goto('/')
    await expect(page.getByText('77 files found')).toBeVisible({ timeout: 15_000 })
  })

  test('says so when the server cannot be reached', async ({ page }) => {
    await page.route('**/api/status', (route) => route.abort())
    await page.goto('/')
    await expect(page.locator('.error')).toContainText('Could not reach the server')
  })

  test('shows the server message when starting an ingest fails', async ({ page }) => {
    await mockJson(page, '**/api/status', fakeStatus())
    await mockJson(page, '**/api/ingest', { detail: 'disk is full' }, 500)
    page.on('dialog', (d) => d.accept())
    await page.goto('/')
    await page.getByRole('button', { name: 'Re-read everything' }).click()
    await expect(page.locator('.error')).toContainText('disk is full')
  })

  test('recovers by itself once the server is reachable again', async ({ page }) => {
    let fail = true
    await page.route('**/api/status', (route) => (fail ? route.abort() : route.fulfill({ json: fakeStatus() })))
    await page.goto('/')
    await expect(page.locator('.error')).toBeVisible()
    fail = false
    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible({ timeout: 15_000 })
  })
})
