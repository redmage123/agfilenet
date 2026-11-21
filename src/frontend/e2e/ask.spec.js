import { test, expect, mockJson, watchConsole } from './helpers.js'

const box = (page) => page.getByRole('searchbox')
const answer = (page) => page.locator('.answer')
const sources = (page) => page.locator('.sources > li')
const source = (over = {}) => ({
  id: 999, title: 'Sample letter', filename: 'sample.pdf', matter: 'M-1', page: 2, text: 'The needle was sold for ten pounds.',
  score: 0.9, ...over,
})
const asked = (over = {}) => ({
  id: 'abc', question: 'What was the needle sold for?', status: 'thinking', answer: null,
  sources: [source(), source({ id: 998, title: null, filename: 'other.pdf', matter: null, page: 1, text: 'Another passage.' })],
  ...over,
})

test.describe('asking the files a question', () => {
  test('is reached from the top bar and starts empty', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('navigation').getByRole('link', { name: 'Ask' }).click()
    await expect(page).toHaveURL(/\/ask$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Ask the files' })).toBeVisible()
    await expect(box(page)).toBeFocused()
    await expect(answer(page)).toHaveCount(0)
    await expect(page.getByRole('main')).toContainText('Nothing leaves this machine.')
  })

  test('shows the passages at once and the answer when it is ready, with a warning to check it', async ({ page }) => {
    const problems = watchConsole(page)
    let polls = 0
    await page.route('**/api/ask', (route) => {
      expect(route.request().postDataJSON()).toEqual({ question: 'What was the needle sold for?' })
      route.fulfill({ json: asked() })
    })
    await page.route('**/api/ask/abc', (route) =>
      route.fulfill({ json: ++polls < 2 ? { status: 'thinking', answer: null } : { status: 'done', answer: 'Ten pounds [1].' } }))
    await page.goto('/ask')
    await box(page).fill('  What was the needle sold for?  ')
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(page).toHaveURL(/[?&]q=What\+was\+the\+needle/)
    await expect(answer(page)).toContainText('writing an answer')
    await expect(sources(page)).toHaveCount(2)
    await expect(sources(page).first().getByRole('link')).toHaveAttribute('href', '/documents/999?page=2')
    await expect(sources(page).first()).toContainText('p. 2 · M-1 · sample.pdf')
    await expect(sources(page).first()).toContainText('The needle was sold for ten pounds.')
    await expect(sources(page).nth(1).getByRole('link')).toHaveText('other.pdf')
    await expect(page.locator('.answer-text')).toHaveText('Ten pounds [1].')
    await expect(answer(page).locator('.notice')).toContainText('check the answer against the passages below')
    await expect(answer(page)).not.toContainText('writing an answer')
    expect(polls).toBe(2)
    await expect(page).toHaveTitle(/What was the needle sold for\? – Ask/)
    expect(problems).toEqual([])
  })

  test('without the language model the passages are still shown', async ({ page }) => {
    await mockJson(page, '**/api/ask', asked({ status: 'unavailable' }))
    await page.goto('/ask?q=anything')
    await expect(answer(page)).toContainText('The language model is not installed on this server')
    await expect(sources(page)).toHaveCount(2)
    await expect(page.locator('.answer-text')).toHaveCount(0)
  })

  test('says so when nothing relevant is found, when the model fails, and when the request fails', async ({ page }) => {
    await mockJson(page, '**/api/ask', asked({ status: 'done', sources: [] }))
    await page.goto('/ask?q=anything')
    await expect(answer(page)).toContainText('No passage in the files looks relevant to this question.')
    await expect(page.getByRole('heading', { name: 'Passages the answer is drawn from' })).toHaveCount(0)

    await mockJson(page, '**/api/ask', asked())
    await mockJson(page, '**/api/ask/abc', { status: 'failed', answer: null })
    await page.reload()
    await expect(answer(page).locator('.error')).toContainText('could not write an answer')
    await expect(sources(page)).toHaveCount(2)

    await mockJson(page, '**/api/ask', { detail: 'ask a question' }, 422)
    await page.reload()
    await expect(page.locator('.error')).toHaveText('ask a question')
    await expect(answer(page)).toHaveCount(0)
  })

  test('an empty question asks nothing', async ({ page }) => {
    let calls = 0
    await page.route('**/api/ask', (route) => { calls += 1; route.fulfill({ json: asked() }) })
    await page.goto('/ask')
    await box(page).fill('   ')
    await box(page).press('Enter')
    await expect(page).toHaveURL(/\/ask$/)
    expect(calls).toBe(0)
  })

  test('a real question brings back passages from the files, and an answer or a reason there is none', async ({ page, request, corpus }) => {
    test.setTimeout(240_000)
    const doc = corpus.docs.find((d) => d.doc_type) || corpus.docs[0]
    const question = `What is the ${doc.doc_type || 'document'} about?`
    const first = await (await request.post('/api/ask', { data: { question } })).json()
    expect(first.question).toBe(question)
    expect(first.sources.length).toBeGreaterThan(0)
    expect(first.sources.length).toBeLessThanOrEqual(5)
    const ids = corpus.docs.map((d) => d.id)
    const perDoc = {}
    for (const s of first.sources) {
      expect(ids).toContain(s.id)
      expect(s.text.length).toBeGreaterThan(0)
      perDoc[s.id] = (perDoc[s.id] || 0) + 1
    }
    expect(Math.max(...Object.values(perDoc))).toBeLessThanOrEqual(2)
    expect(first.status).toBe(corpus.status.models.language ? 'thinking' : 'unavailable')
    expect((await request.get('/api/ask/no-such-question')).status()).toBe(404)
    expect((await request.post('/api/ask', { data: { question: ' ' } })).status()).toBe(422)

    await page.goto(`/ask?q=${encodeURIComponent(question)}`)
    await expect(sources(page).first()).toBeVisible({ timeout: 60_000 })
    if (corpus.status.models.language) {
      await expect(page.locator('.answer-text')).toBeVisible({ timeout: 200_000 })
      expect((await page.locator('.answer-text').textContent()).trim().length).toBeGreaterThan(0)
    } else {
      await expect(answer(page)).toContainText('not installed')
    }
  })
})
