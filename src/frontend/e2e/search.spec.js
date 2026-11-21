import { test, expect, mockJson, fakeSearch, fakeHit, fakeStatus } from './helpers.js'

const box = (page) => page.getByRole('searchbox')
const results = (page) => page.locator('.result')
const tab = (page, name) => page.getByRole('tab', { name, exact: true })

// A name that appears in several files makes a query with known right answers.
const sharedName = (corpus) => {
  const best = {}
  for (const d of corpus.details)
    for (const e of d.entities) if (e.kind === 'person' && e.docs >= 2) (best[e.value] ||= []).push(d.id)
  const [value, ids] = Object.entries(best).sort((a, b) => b[1].length - a[1].length)[0]
  return { value, ids }
}
const search = async (page, text) => {
  await box(page).fill(text)
  await page.getByRole('button', { name: 'Search', exact: true }).click()
}

test.describe('search', () => {
  test('starts empty, focused on the box, with the IAC mode chosen', async ({ page }) => {
    await page.goto('/search')
    await expect(box(page)).toBeFocused()
    await expect(box(page)).toHaveValue('')
    await expect(tab(page, 'IAC network')).toHaveAttribute('aria-selected', 'true')
    await expect(results(page)).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'About these probabilities' })).toHaveCount(0)
    await expect(page.getByRole('tab')).toHaveCount(4)
  })

  test('a name finds the files that mention it, with a probability for each', async ({ page, corpus }) => {
    const { value, ids } = sharedName(corpus)
    await page.goto('/search')
    await search(page, value)
    await expect(page).toHaveURL(/[?&]q=.+&mode=iac/)
    await expect(results(page).first()).toBeVisible({ timeout: 30_000 })
    const n = await results(page).count()
    await expect(page.getByText(new RegExp(`^${n} possible match(es)?\\.`))).toBeVisible()
    await expect(page.getByText(/Chance that none of these is what you want: (<1|>99|\d+)%/)).toBeVisible()

    const probs = (await page.locator('.prob-n').allTextContents()).map((t) => parseInt(t.replace(/[<>%]/g, ''), 10))
    expect(probs).toEqual([...probs].sort((a, b) => b - a))
    expect(probs.every((p) => p >= 0 && p <= 100)).toBe(true)
    await expect(results(page).first().locator('.prob')).toContainText('match')
    await expect(results(page).first().locator('.prob')).toContainText(/(<1|>99|\d+)% best/)

    const top = await results(page).first().locator('.result-title').getAttribute('href')
    expect(ids).toContain(Number(top.match(/documents\/(\d+)/)[1]))
    await expect(results(page).first().locator('mark').first()).toBeVisible()
    await expect(results(page).first().locator('.chip-query').first()).toBeVisible()
    await expect(results(page).first().locator('.scores')).toContainText(/activation -?\d\.\d\d/)
  })

  test('pressing Enter searches, and surrounding spaces are ignored', async ({ page, corpus }) => {
    const { value } = sharedName(corpus)
    await page.goto('/search')
    await box(page).fill(`   ${value}   `)
    await box(page).press('Enter')
    await expect(results(page).first()).toBeVisible({ timeout: 30_000 })
    await expect(box(page)).toHaveValue(value)
    expect(new URL(page.url()).searchParams.get('q')).toBe(value)
  })

  test('a result opens the document at the page that matched', async ({ page, corpus }) => {
    const { value } = sharedName(corpus)
    await page.goto(`/search?q=${encodeURIComponent(value)}&mode=keyword`)
    const first = results(page).first()
    await expect(first).toBeVisible({ timeout: 30_000 })
    const href = await first.locator('.result-title').getAttribute('href')
    const pageNo = href.match(/page=(\d+)/)[1]
    await expect(first.locator('.snippet')).toContainText(`p. ${pageNo}:`)
    await first.locator('.result-title').click()
    await expect(page.locator('.pager')).toContainText(`Page ${pageNo} of`)
    await page.goBack()
    await expect(box(page)).toHaveValue(value)
    await expect(results(page).first()).toBeVisible({ timeout: 30_000 })
  })

  for (const [mode, label, blurb, score, absent] of [
    ['hybrid', 'Hybrid', 'A match on either the words or the meaning counts.', /keyword \d|similarity \d/, 'activation'],
    ['keyword', 'Keyword', 'Exact words (BM25).', /keyword \d+\.\d/, 'similarity'],
    ['semantic', 'Semantic', 'Meaning of the query compared with each passage.', /similarity \d\.\d\d/, 'keyword'],
  ]) {
    test(`${label} mode searches again and shows its own scores and caveat`, async ({ page, corpus }) => {
      const { value } = sharedName(corpus)
      await page.goto(`/search?q=${encodeURIComponent(value)}`)
      await expect(results(page).first()).toBeVisible({ timeout: 30_000 })
      await tab(page, label).click()
      await expect(page).toHaveURL(new RegExp(`mode=${mode}`))
      await expect(tab(page, label)).toHaveAttribute('aria-selected', 'true')
      await expect(tab(page, 'IAC network')).toHaveAttribute('aria-selected', 'false')
      await expect(page.getByText(blurb)).toBeVisible()
      await expect(results(page).first().locator('.scores')).toContainText(score, { timeout: 30_000 })
      await expect(results(page).first().locator('.scores')).not.toContainText(absent)
      await expect(page.getByText('rule-of-thumb conversions of the raw score')).toBeVisible()
      await expect(page.locator('details')).toHaveCount(0)
      await expect(page.locator('.notice')).toHaveCount(0)
    })
  }

  test('choosing a mode before typing keeps the mode for the search that follows', async ({ page, corpus }) => {
    const { value } = sharedName(corpus)
    await page.goto('/search')
    await tab(page, 'Keyword').click()
    await expect(tab(page, 'Keyword')).toHaveAttribute('aria-selected', 'true')
    await search(page, value)
    await expect(page).toHaveURL(/mode=keyword/)
  })

  test('choosing a mode with text typed but not yet searched runs the search', async ({ page, corpus }) => {
    const { value } = sharedName(corpus)
    await page.goto('/search')
    await box(page).fill(value)
    await tab(page, 'Keyword').click()
    await expect(page).toHaveURL(/mode=keyword/)
    await expect(results(page).first()).toBeVisible({ timeout: 30_000 })
  })

  test('a quoted phrase in keyword mode only returns files containing it', async ({ page, corpus }) => {
    const { value, ids } = sharedName(corpus)
    await page.goto('/search')
    await tab(page, 'Keyword').click()
    await search(page, `"${value}"`)
    await expect(results(page).first()).toBeVisible({ timeout: 30_000 })
    const hrefs = await results(page).locator('.result-title').evaluateAll((els) => els.map((e) => e.getAttribute('href')))
    const containing = corpus.details
      .filter((d) => d.pages.some((p) => (p.text || '').toLowerCase().replace(/\s+/g, ' ').includes(value.toLowerCase())))
      .map((d) => d.id)
    for (const h of hrefs) expect([...ids, ...containing]).toContain(Number(h.match(/documents\/(\d+)/)[1]))
  })

  test('words that occur nowhere give no keyword matches and say so', async ({ page }) => {
    await page.goto('/search?q=zzzqqqx+vvvkkkw&mode=keyword')
    await expect(page.getByText('No possible matches.')).toBeVisible({ timeout: 30_000 })
    await expect(results(page)).toHaveCount(0)
    await expect(page.getByText(/Chance that none of these is what you want: >99%/)).toBeVisible()
  })

  test('the IAC network panel lists active units and names words it does not know', async ({ page, corpus }) => {
    const { value } = sharedName(corpus)
    await page.goto(`/search?q=${encodeURIComponent(value + ' zzzqqqx')}`)
    await expect(results(page).first()).toBeVisible({ timeout: 30_000 })
    const details = page.locator('details')
    await expect(details.locator('summary')).toHaveText(/Network state: \d+ units \(\d+ documents\), settled in \d+ cycles/)
    await expect(details.locator('table')).toBeHidden()
    await details.locator('summary').click()
    await expect(details.getByText('Words not found in any document: zzzqqqx')).toBeVisible()
    await expect(details.locator('tbody tr').first()).toBeVisible()
    await expect(details.locator('.tag', { hasText: 'from query' }).first()).toBeVisible()
    await expect(page.getByText(/not yet checked against real judgements \(\d+ of \d+ needed/)).toBeVisible()
  })

  test('describing what a file is about finds files that do not use those words', async ({ page }) => {
    await page.goto('/search')
    await tab(page, 'Semantic').click()
    await search(page, 'someone was hurt and wants compensation')
    await expect(results(page).first()).toBeVisible({ timeout: 30_000 })
    await expect(results(page).first().locator('.scores')).toContainText(/similarity/)
  })

  test('answering Yes or No records the judgement and counts towards calibration', async ({ page, corpus, request }) => {
    const { value } = sharedName(corpus)
    const before = (await (await request.get('/api/search?q=x')).json()).calibration.judgements
    await page.goto(`/search?q=${encodeURIComponent(value)}`)
    await expect(results(page).nth(1)).toBeVisible({ timeout: 30_000 })
    await results(page).nth(0).getByRole('button', { name: 'Yes' }).click()
    await expect(results(page).nth(0).locator('.judge')).toHaveText('Recorded: match')
    await results(page).nth(1).getByRole('button', { name: 'No' }).click()
    await expect(results(page).nth(1).locator('.judge')).toHaveText('Recorded: not a match')
    await expect(results(page).nth(0).getByRole('button', { name: 'Yes' })).toHaveCount(0)
    const after = (await (await request.get('/api/search?q=x')).json()).calibration.judgements
    expect(after).toBe(before + 2)
    await tab(page, 'Keyword').click()
    await expect(results(page).first().getByRole('button', { name: 'Yes' })).toBeVisible({ timeout: 30_000 })
  })

  test('clearing the box and searching returns to the empty state', async ({ page, corpus }) => {
    const { value } = sharedName(corpus)
    await page.goto(`/search?q=${encodeURIComponent(value)}&mode=keyword`)
    await expect(results(page).first()).toBeVisible({ timeout: 30_000 })
    await search(page, '')
    await expect(page).toHaveURL(/\/search$/)
    await expect(results(page)).toHaveCount(0)
    await expect(page.getByRole('heading', { name: 'About these probabilities' })).toHaveCount(0)
  })

  test('characters with a meaning in web addresses are searched literally', async ({ page }) => {
    await page.goto('/search')
    await tab(page, 'Keyword').click()
    await search(page, 'a&b=c #d? 100% "x/y"')
    await expect(page.getByText(/possible match/)).toBeVisible({ timeout: 30_000 })
    await expect(box(page)).toHaveValue('a&b=c #d? 100% "x/y"')
    await expect(page.locator('.error')).toHaveCount(0)
    await page.reload()
    await expect(box(page)).toHaveValue('a&b=c #d? 100% "x/y"')
  })

  test('a very long query is handled', async ({ page }) => {
    await page.goto('/search')
    await search(page, 'land conveyance '.repeat(120).trim())
    await expect(page.getByText(/possible match/)).toBeVisible({ timeout: 45_000 })
    await expect(page.locator('.error')).toHaveCount(0)
  })

  test('an unknown mode in the address falls back to a working search page', async ({ page }) => {
    await page.goto('/search?q=land&mode=nonsense')
    await expect(page.getByRole('heading', { level: 1, name: 'Search' })).toBeVisible()
    await expect(page.getByRole('tab', { selected: true })).toHaveCount(1)
  })

  test('display rules: singular count, <1% and >99%, personal-data flags only, missing fields', async ({ page }) => {
    await mockJson(page, '**/api/search?*', fakeSearch({
      p_none: 0.999,
      results: [fakeHit({ probability: 0.999, share: 0.004, title: null, doc_date: null, page: null, snippet: null, why: [],
        keyword_score: null, semantic_score: null, activation: null })],
    }))
    await page.goto('/search?q=needle')
    await expect(page.getByText('1 possible match.')).toBeVisible()
    await expect(page.getByText('Chance that none of these is what you want: >99%.')).toBeVisible()
    const r = results(page).first()
    await expect(r.locator('.prob-n')).toHaveText('>99%')
    await expect(r.locator('.prob')).toContainText('<1% best')
    await expect(r.locator('.result-title')).toHaveText('sample.pdf')
    await expect(r.locator('.result-title')).toHaveAttribute('href', '/documents/999')
    await expect(r.locator('.result-body > .sub')).toHaveText('Letter · M-1 · 2 pages · sample.pdf')
    await expect(r.locator('.snippet')).toHaveCount(0)
    await expect(r.locator('.chips')).toHaveCount(0)
    await expect(r.locator('.flag')).toHaveCount(1)
    await expect(r.locator('.flag')).toHaveText('Passport details')
    await expect(r.locator('.scores')).not.toContainText(/activation|keyword|similarity/)
  })

  test('says which words of similar meaning it also looked for', async ({ page }) => {
    const base = fakeSearch()
    await mockJson(page, '**/api/search?*', fakeSearch({
      network: { ...base.network, expanded: [{ term: 'thread', from: 'needle', similarity: 0.81 }, { term: 'pin', from: 'needle', similarity: 0.8 }] },
    }))
    await page.goto('/search?q=needle')
    await expect(page.locator('.related-words')).toHaveText('Also looked for words of similar meaning found in the files: thread (for needle), pin (for needle).')
    await mockJson(page, '**/api/search?*', fakeSearch())
    await page.reload()
    await expect(results(page)).toHaveCount(1)
    await expect(page.locator('.related-words')).toHaveCount(0)
  })

  test('shows what the second reading did to a result', async ({ page }) => {
    await mockJson(page, '**/api/search?*', fakeSearch({
      reread: 2,
      results: [fakeHit({ id: 1, probability: 0.93, first_probability: 0.61, reread: 0.97 }),
                fakeHit({ id: 2, probability: 0.2, first_probability: 0.55, reread: 0.04 }),
                fakeHit({ id: 3, probability: 0.1, first_probability: 0.1 })],
    }))
    await page.goto('/search?q=needle')
    await expect(page.locator('.second-reading')).toContainText('The top 2 results were read a second time')
    await expect(results(page).nth(0).locator('.scores')).toContainText('second reading 0.97 (was 61%)')
    await expect(results(page).nth(1).locator('.scores')).toContainText('second reading 0.04 (was 55%)')
    await expect(results(page).nth(2).locator('.scores')).not.toContainText('second reading')
    await mockJson(page, '**/api/search?*', fakeSearch())
    await page.reload()
    await expect(results(page)).toHaveCount(1)
    await expect(page.locator('.second-reading')).toHaveCount(0)
  })

  test('deeper search is offered when the language model is installed, and says which wordings it added', async ({ page }) => {
    const asked = []
    await mockJson(page, '**/api/status', fakeStatus())
    await page.route('**/api/search?*', (route) => {
      const url = new URL(route.request().url())
      asked.push(url.searchParams.get('deep'))
      route.fulfill({ json: fakeSearch(url.searchParams.get('deep') ? { also: ['sewing pin', 'small sharp thing'] } : {}) })
    })
    await page.goto('/search?q=needle')
    await expect(results(page)).toHaveCount(1)
    await expect(page.locator('.other-wordings')).toHaveCount(0)
    await page.getByLabel(/Deeper search/).check()
    await expect(page).toHaveURL(/[?&]deep=1/)
    await expect(page.locator('.other-wordings')).toHaveText('Also searched for these other wordings, suggested by the language model: sewing pin; small sharp thing.')
    expect(asked).toEqual([null, 'true'])
    await tab(page, 'Keyword').click()                    // other wordings belong to the IAC mode only
    await expect(page).not.toHaveURL(/deep=/)
    await expect(page.getByLabel(/Deeper search/)).toHaveCount(0)
  })

  test('deeper search is not offered without the language model', async ({ page }) => {
    await mockJson(page, '**/api/status', fakeStatus({ models: { names: true, reread: true, language: false } }))
    await mockJson(page, '**/api/search?*', fakeSearch())
    await page.goto('/search?q=needle')
    await expect(results(page)).toHaveCount(1)
    await expect(page.getByLabel(/Deeper search/)).toHaveCount(0)
  })

  test('a real search for a word fans out only to words that are in the files', async ({ page, request }) => {
    const data = await (await request.get('/api/search', { params: { q: 'lawsuit about money', mode: 'iac' } })).json()
    expect(Array.isArray(data.network.expanded)).toBe(true)
    for (const e of data.network.expanded) {
      expect(['lawsuit', 'money']).toContain(e.from)
      expect(e.similarity).toBeGreaterThanOrEqual(0.78)
      const literal = await (await request.get('/api/search', { params: { q: e.term, mode: 'keyword' } })).json()
      expect(literal.results.length, `"${e.term}" is in a file`).toBeGreaterThan(0)
    }
    await page.goto('/search?q=lawsuit+about+money')
    await expect(page.locator('.related-words')).toHaveCount(data.network.expanded.length ? 1 : 0)
  })

  test('a file reached only through links is labelled as not containing the words', async ({ page }) => {
    await mockJson(page, '**/api/search?*', fakeSearch({
      results: [
        fakeHit({ id: 1, matched_text: false, why: [{ kind: 'entity', label: 'Alex Example', in_query: false, input: 0.3 }] }),
        fakeHit({ id: 2, matched_text: false, why: [{ kind: 'semantic', label: 'meaning', in_query: true, input: 0.3 }] }),
        fakeHit({ id: 3, matched_text: true }),
      ],
    }))
    await page.goto('/search?q=needle')
    await expect(results(page)).toHaveCount(3)
    await expect(page.getByText('3 possible matches.')).toBeVisible()
    await expect(results(page).nth(0).locator('.notice')).toContainText('Does not contain the search words')
    await expect(results(page).nth(1).locator('.notice')).toHaveCount(0)
    await expect(results(page).nth(2).locator('.notice')).toHaveCount(0)
    await expect(results(page).nth(0).locator('.chip')).toHaveClass('chip')
    await expect(results(page).nth(2).locator('.chip')).toHaveClass('chip chip-query')
    await expect(results(page).nth(2).locator('mark')).toHaveText('needle')
  })

  test('once enough judgements exist the page says the scale has been fitted', async ({ page }) => {
    await mockJson(page, '**/api/search?*', fakeSearch({ calibration: { fitted: true, judgements: 34, needed: 20 } }))
    await page.goto('/search?q=needle')
    await expect(page.getByText('The match scale has been fitted to 34 Yes/No judgements.')).toBeVisible()
    await page.locator('details summary').click()
    await expect(page.getByText('Words not found in any document')).toHaveCount(0)
    await expect(page.locator('details tbody tr')).toHaveCount(2)
    await expect(page.locator('details tbody tr').nth(1).locator('.bar-fill')).toHaveAttribute('style', /width: 0%/)
  })

  test('shows Searching… while waiting, then the results', async ({ page }) => {
    await page.route('**/api/search?*', async (route) => {
      await new Promise((r) => setTimeout(r, 1500))
      return route.fulfill({ json: fakeSearch() })
    })
    await page.goto('/search?q=needle')
    await expect(page.getByText('Searching…')).toBeVisible()
    await expect(results(page)).toHaveCount(1)
    await expect(page.getByText('Searching…')).toHaveCount(0)
  })

  test('a slow answer to an earlier search never replaces the latest one', async ({ page }) => {
    await page.route('**/api/search?*', async (route) => {
      const slow = route.request().url().includes('q=first')
      await new Promise((r) => setTimeout(r, slow ? 2000 : 100))
      return route.fulfill({ json: fakeSearch({ results: [fakeHit({ title: slow ? 'OLD ANSWER' : 'NEW ANSWER' })] }) })
    })
    await page.goto('/search?q=first')
    await search(page, 'second')
    await expect(results(page).first().locator('.result-title')).toHaveText('NEW ANSWER')
    await page.waitForTimeout(2500)
    await expect(results(page).first().locator('.result-title')).toHaveText('NEW ANSWER')
  })

  test('a failed search shows the server message and no stale results', async ({ page }) => {
    let fail = false
    await page.route('**/api/search?*', (route) =>
      fail ? route.fulfill({ status: 500, json: { detail: 'index is being rebuilt' } }) : route.fulfill({ json: fakeSearch() }))
    await page.goto('/search?q=needle')
    await expect(results(page)).toHaveCount(1)
    fail = true
    await search(page, 'another')
    await expect(page.locator('.error')).toHaveText('index is being rebuilt')
    await expect(results(page)).toHaveCount(0)
  })

  test('a judgement that cannot be saved is reported and can be tried again', async ({ page }) => {
    await mockJson(page, '**/api/search?*', fakeSearch())
    await mockJson(page, '**/api/feedback', { detail: 'document not found' }, 404)
    await page.goto('/search?q=needle')
    await results(page).first().getByRole('button', { name: 'Yes' }).click()
    await expect(page.locator('.error')).toHaveText('document not found')
    await expect(results(page).first().getByRole('button', { name: 'Yes' })).toBeVisible()
  })

  test('the judgement sent to the server carries the query, document and activation', async ({ page }) => {
    let body
    await mockJson(page, '**/api/search?*', fakeSearch())
    await page.route('**/api/feedback', (route) => {
      body = route.request().postDataJSON()
      return route.fulfill({ json: { judgements: 1 } })
    })
    await page.goto('/search?q=needle')
    await results(page).first().getByRole('button', { name: 'No' }).click()
    await expect.poll(() => body).toEqual({ query: 'needle', doc_id: 999, relevant: false, activation: 0.83 })
  })
})
