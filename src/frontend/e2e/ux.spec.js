import AxeBuilder from '@axe-core/playwright'
import { test, expect, watchConsole } from './helpers.js'

const pagesFor = (corpus) => {
  const doc = corpus.details.find((d) => d.segments.length > 1 && d.entities.length) || corpus.details[0]
  return [
    ['overview', '/'],
    ['document list', '/documents'],
    ['document', `/documents/${doc.id}`],
    ['search results', '/search?q=court&mode=iac'],
  ]
}
const settle = async (page, name) => {
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  if (name === 'search results') await expect(page.locator('.result').first()).toBeVisible({ timeout: 30_000 })
  if (name === 'document') await expect(page.locator('.page-view img')).toBeVisible()
  if (name === 'document list') await expect(page.locator('.doc-table')).toBeVisible()
}

test.describe('usability', () => {
  for (const i of [0, 1, 2, 3]) {
    test(`accessibility rules (WCAG A and AA) — page ${i + 1} of 4`, async ({ page, corpus }) => {
      const [name, path] = pagesFor(corpus)[i]
      await page.goto(path)
      await settle(page, name)
      const { violations } = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
      expect(violations.map((v) => `${name}: ${v.id} (${v.impact}) × ${v.nodes.length} — ${v.help}`)).toEqual([])
    })

    test(`nothing spills off a phone-sized screen — page ${i + 1} of 4`, async ({ page, corpus }) => {
      const [name, path] = pagesFor(corpus)[i]
      await page.setViewportSize({ width: 390, height: 800 })
      await page.goto(path)
      await settle(page, name)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `${name} is ${overflow}px wider than the screen`).toBeLessThanOrEqual(1)
    })

    test(`no errors in the browser console — page ${i + 1} of 4`, async ({ page, corpus }) => {
      const [name, path] = pagesFor(corpus)[i]
      const problems = watchConsole(page)
      await page.goto(path)
      await settle(page, name)
      expect(problems).toEqual([])
    })
  }

  test('each page gives the browser tab its own title', async ({ page, corpus }) => {
    const titles = new Set()
    for (const [name, path] of pagesFor(corpus)) {
      await page.goto(path)
      await settle(page, name)
      titles.add(await page.title())
    }
    expect(titles.size).toBe(4)
  })

  test('the whole search flow works from the keyboard', async ({ page }) => {
    await page.goto('/search')
    await page.keyboard.type('court')
    await page.keyboard.press('Enter')
    await expect(page.locator('.result').first()).toBeVisible({ timeout: 30_000 })
    await page.keyboard.press('Tab') // Search button
    await page.keyboard.press('Tab') // first mode
    await expect(page.getByRole('tab', { name: 'IAC network' })).toBeFocused()
    await page.keyboard.press('Tab')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/mode=hybrid/)
    await expect(page.locator('.result').first()).toBeVisible({ timeout: 30_000 })
    await page.locator('.result-title').first().focus()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/documents\/\d+/)
  })

  test('keyboard focus is visible on links, buttons and fields', async ({ page }) => {
    await page.goto('/documents')
    await expect(page.locator('.doc-table')).toBeVisible()
    for (const target of [page.getByRole('link', { name: 'Overview' }), page.getByRole('searchbox'), page.locator('.filters select').first()]) {
      await target.focus()
      await page.keyboard.press('Shift+Tab')
      await page.keyboard.press('Tab')
      const visible = await target.evaluate((el) => {
        const s = getComputedStyle(el)
        return (s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0) || s.boxShadow !== 'none'
      })
      expect(visible).toBe(true)
    }
  })

  test('form fields have labels and images have descriptions', async ({ page, corpus }) => {
    await page.goto(`/documents/${corpus.details[0].id}`)
    await expect(page.locator('.page-view img')).toBeVisible()
    const unlabelled = await page.locator('input, select, textarea').evaluateAll((els) =>
      els.filter((el) => !el.labels?.length && !el.getAttribute('aria-label') && !el.getAttribute('aria-labelledby')).length)
    expect(unlabelled).toBe(0)
    expect(await page.locator('img:not([alt])').count()).toBe(0)
    await page.goto('/search')
    await expect(page.getByRole('searchbox')).toHaveAccessibleName(/.+/)
    await page.goto('/documents')
    await expect(page.getByRole('searchbox')).toHaveAccessibleName(/.+/)
  })

  test('leaving a document with unsaved corrections asks first', async ({ page, corpus }) => {
    await page.goto(`/documents/${corpus.details[0].id}`)
    await page.getByLabel('Subject', { exact: true }).fill('unsaved work')
    let asked = false
    page.on('dialog', (d) => {
      asked = true
      d.dismiss()
    })
    await page.getByRole('navigation').getByRole('link', { name: 'Search' }).click()
    await page.waitForTimeout(500)
    expect(asked || (await page.getByText(/unsaved/i).count()) > 0).toBe(true)
    await expect(page).toHaveURL(/\/documents\/\d+/)
    await expect(page.getByLabel('Subject', { exact: true })).toHaveValue('unsaved work')
  })

  test('re-reading everything asks for confirmation before starting hours of OCR', async ({ page }) => {
    let started = false
    await page.route('**/api/ingest', (route) => {
      started = true
      return route.fulfill({ json: { job_id: 1 } })
    })
    let asked = false
    page.on('dialog', (d) => {
      asked = true
      d.dismiss()
    })
    await page.goto('/')
    await page.getByRole('button', { name: 'Re-read everything' }).click()
    await page.waitForTimeout(500)
    expect(asked).toBe(true)
    expect(started).toBe(false)
  })

  test('pages load quickly enough to feel responsive', async ({ page, corpus }) => {
    for (const [name, path] of pagesFor(corpus).slice(0, 3)) {
      const t0 = Date.now()
      await page.goto(path)
      await settle(page, name)
      expect(Date.now() - t0, `${name} took too long`).toBeLessThan(8000)
    }
  })
})
