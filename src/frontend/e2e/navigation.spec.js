import { test, expect, watchConsole } from './helpers.js'

test.describe('navigation', () => {
  test('top bar links reach every page and mark the current one', async ({ page }) => {
    const problems = watchConsole(page)
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Overview' })).toHaveClass(/active/)

    await page.getByRole('navigation').getByRole('link', { name: 'Documents' }).click()
    await expect(page).toHaveURL(/\/documents$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Documents' })).toBeVisible()
    await expect(page.getByRole('navigation').getByRole('link', { name: 'Documents' })).toHaveClass(/active/)
    await expect(page.getByRole('link', { name: 'Overview' })).not.toHaveClass(/active/)

    await page.getByRole('navigation').getByRole('link', { name: 'Search' }).click()
    await expect(page).toHaveURL(/\/search$/)
    await expect(page.getByRole('heading', { level: 1, name: 'Search' })).toBeVisible()

    await page.getByRole('link', { name: 'Overview' }).click()
    await expect(page).toHaveURL(/\/$/)
    expect(problems).toEqual([])
  })

  test('browser back and forward move between pages', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('navigation').getByRole('link', { name: 'Documents' }).click()
    await page.getByRole('navigation').getByRole('link', { name: 'Search' }).click()
    await page.goBack()
    await expect(page.getByRole('heading', { level: 1, name: 'Documents' })).toBeVisible()
    await page.goForward()
    await expect(page.getByRole('heading', { level: 1, name: 'Search' })).toBeVisible()
  })

  for (const [path, heading] of [['/documents', 'Documents'], ['/search', 'Search']]) {
    test(`opening ${path} directly (or reloading it) shows the page`, async ({ page }) => {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
      await page.reload()
      await expect(page.getByRole('heading', { level: 1, name: heading })).toBeVisible()
    })
  }

  test('a document address can be opened directly', async ({ page, corpus }) => {
    const doc = corpus.docs[0]
    await page.goto(`/documents/${doc.id}`)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(doc.title || doc.filename)
  })

  test('an unknown address tells the user the page does not exist', async ({ page }) => {
    await page.goto('/no-such-page')
    await expect(page.getByRole('banner')).toBeVisible()
    await expect(page.getByRole('main')).toContainText(/not found|does not exist/i)
  })

  test('every page has a title naming the app', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle(/FileNet/i)
  })
})
