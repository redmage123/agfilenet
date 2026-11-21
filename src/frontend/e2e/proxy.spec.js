import { test, expect } from './helpers.js'

// The public entrance (nginx with a password). Read-only; runs only when
// E2E_PROXY_URL, E2E_PROXY_USER and E2E_PROXY_PASSWORD are set.
const { E2E_PROXY_URL: url, E2E_PROXY_USER: username, E2E_PROXY_PASSWORD: password } = process.env

test.describe('public entrance', () => {
  test.skip(!url || !username || !password, 'proxy details not provided')

  test('nothing is served without the password', async ({ playwright }) => {
    const anon = await playwright.request.newContext({ baseURL: url, ignoreHTTPSErrors: true })
    for (const path of ['/', '/api/status', '/api/documents', '/api/export.csv', '/api/documents/1/file', '/assets/x.js']) {
      const res = await anon.get(path)
      expect(res.status(), path).toBe(401)
      expect(res.headers()['www-authenticate']).toContain('Basic')
    }
    await anon.dispose()
  })

  test('a wrong password is refused', async ({ playwright }) => {
    const wrong = await playwright.request.newContext({
      baseURL: url, ignoreHTTPSErrors: true, httpCredentials: { username, password: 'not-the-password', send: 'always' },
    })
    expect((await wrong.get('/api/status')).status()).toBe(401)
    await wrong.dispose()
  })

  test('plain HTTP is redirected to HTTPS', async ({ playwright }) => {
    const plain = await playwright.request.newContext({ ignoreHTTPSErrors: true })
    const res = await plain.get(url.replace(/^https:/, 'http:'), { maxRedirects: 0 })
    expect(res.status()).toBe(301)
    expect(res.headers().location).toMatch(/^https:/)
    await plain.dispose()
  })

  test('with the password the app loads and works in a browser, and asks search engines to stay away', async ({ browser }) => {
    const context = await browser.newContext({ baseURL: url, ignoreHTTPSErrors: true, httpCredentials: { username, password } })
    const page = await context.newPage()
    const res = await page.goto('/')
    expect(res.headers()['x-robots-tag']).toContain('noindex')
    await expect(page.getByRole('heading', { level: 1, name: 'Overview' })).toBeVisible()
    await page.getByRole('navigation').getByRole('link', { name: 'Documents' }).click()
    await expect(page.locator('.doc-table tbody tr').first()).toBeVisible()
    await page.locator('.doc-table tbody tr').first().getByRole('link').click()
    await expect(page.locator('.page-view img')).toBeVisible()
    await expect.poll(() => page.locator('.page-view img').evaluate((el) => el.naturalWidth), { timeout: 30_000 }).toBeGreaterThan(100)
    await page.goto('/search?q=court&mode=keyword')
    await expect(page.locator('.result').first()).toBeVisible({ timeout: 30_000 })
    await context.close()
  })
})
