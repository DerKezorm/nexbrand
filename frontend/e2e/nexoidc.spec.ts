/**
 * Pflichttests 33 and 34 of the shared sign-in blueprint (copied once from bauplaene/oidc, then nexbrand's file).
 *
 * The provider is the stand-in of e2e/fake-provider.mjs (an OpenID Connect provider over http on 8547 with a key made
 * at its start, sending the browser straight back with a code for whoever POST /oidc/next named). Never a real
 * provider, never the network. The page is the operator `tester` of the global set-up.
 */
import { expect, request, test, type Page } from '@playwright/test'

const TAB = { 'X-Nexbrand-Client': 'tab-e2e-oidc00' }
const PROVIDER = process.env.NEXBRAND_E2E_PROVIDER ?? 'http://127.0.0.1:8547'
const ISSUER = `${PROVIDER}/oidc`
const PASSWORD = 'e2e provider test password'
/** The card's button: "Use it and set up" while the app has no public address of its own, else "Set up". */
const SET_UP = /^(Set up|Use it and set up)$/

type Entry = { id: number; slug: string; label: string }

async function entries(page: Page): Promise<Entry[]> {
  return (await (await page.request.get('/api/oidc/admin/providers')).json()) as Entry[]
}

async function removeEntry(page: Page, slug: string): Promise<void> {
  for (const entry of await entries(page)) {
    if (entry.slug === slug) await page.request.delete(`/api/oidc/admin/providers/${entry.id}`, { headers: TAB })
  }
}

function collectProblems(page: Page): string[] {
  const problems: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && !/status of 4(01|04|09|22)/.test(message.text())) problems.push(message.text())
  })
  page.on('pageerror', (error) => problems.push(error.message))
  return problems
}

async function next(person: Record<string, string>): Promise<void> {
  await fetch(`${ISSUER}/next`, { method: 'POST', body: JSON.stringify(person) })
}

test('33: sign-in through the provider button ends in a session', async ({ page, browser, baseURL }) => {
  await removeEntry(page, 'standin33')
  const made = await page.request.post('/api/oidc/admin/providers', {
    data: { label: 'Stand-in 33', slug: 'standin33', issuer: ISSUER, client_id: 'e2e-client', client_secret: `e2e-${Date.now()}` },
    headers: TAB,
  })
  expect(made.ok(), await made.text()).toBe(true)
  // An account of its own, linked to the stand-in's person through its profile.
  const invite = await page.request.post('/api/invites', { data: { days: 1 }, headers: TAB })
  expect(invite.ok(), await invite.text()).toBe(true)
  const token = new URL((await invite.json()).link).pathname.split('/').pop()!
  const outside = await request.newContext({ baseURL })
  const joined = await outside.post(`/api/invite/${token}`, { data: { name: 'ossie', password: PASSWORD }, headers: TAB })
  expect(joined.ok(), await joined.text()).toBe(true)
  await outside.dispose()
  await next({ sub: 'ossie-33', preferred_username: 'someone-else', email: 'ossie@example.com' })
  const own = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const ossie = await own.newPage()
  await ossie.goto('/login')
  await ossie.getByLabel('Sign-in name').fill('ossie')
  await ossie.getByLabel('Password').fill(PASSWORD)
  await ossie.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(ossie).toHaveURL(/\/$/)
  await ossie.goto('/account?tab=security')
  const row = ossie.getByTestId('my-providers').locator('li').filter({ hasText: 'Stand-in 33' })
  await expect(row).toContainText('Not linked')
  await row.getByRole('button', { name: 'Link' }).click()
  await row.getByLabel('Password').fill(PASSWORD)
  await row.getByRole('button', { name: 'Link' }).click()
  await expect(ossie).toHaveURL(/\/account\?linked=standin33/)
  // The provider by the name on its button, not by the short name in the address.
  await expect(ossie.getByText('Your account is linked to Stand-in 33.')).toBeVisible()
  const linked = ossie.getByTestId('my-providers').locator('li').filter({ hasText: 'Stand-in 33' })
  await expect(linked).toContainText('Linked')
  // The address the provider knows is offered, not taken.
  await expect(linked).toContainText('Stand-in 33 knows you as ossie@example.com.')
  await own.close()

  // A browser without a session: the button on the sign-in page, and in.
  const fresh = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const visitor = await fresh.newPage()
  const problems = collectProblems(visitor)
  await visitor.goto('/login')
  await visitor.getByRole('button', { name: 'Sign in with Stand-in 33' }).click()
  await visitor.waitForURL((url) => !url.pathname.startsWith('/login') && !url.pathname.startsWith('/api/'))
  await expect(visitor).not.toHaveURL(/error=/)
  expect((await (await visitor.request.get('/api/auth/me')).json()).name).toBe('ossie')
  expect(problems).toEqual([])
  await fresh.close()
  // A stranger at the provider comes in with nothing: the sign-in page says why, in words.
  await next({ sub: 'stranger-33', email: 'ossie@example.com' })
  const strange = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const stranger = await strange.newPage()
  await stranger.goto('/login')
  await stranger.getByRole('button', { name: 'Sign in with Stand-in 33' }).click()
  await expect(stranger).toHaveURL(/\/login\?error=oidc_no_account/)
  await expect(stranger.getByText('There is no account for you here. Ask for an invitation')).toBeVisible()
  await strange.close()
  await removeEntry(page, 'standin33')
})

test('34: add, edit and remove a provider; the authentik card lists its steps', async ({ page }) => {
  const problems = collectProblems(page)
  await removeEntry(page, 'stand-in')
  await page.goto('/settings?tab=server&sub=signin')
  await expect(page.getByRole('heading', { name: 'Sign-in', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sign-in providers' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'authentik in one step' })).toBeVisible()
  await page.getByRole('button', { name: 'Add a provider' }).click()
  const form = page.getByTestId('provider-form')
  await form.getByLabel('Name on the button').fill('Stand-in')
  // The short name follows the name until it is typed itself; the redirect address follows the short name.
  await expect(form.getByLabel('Short name')).toHaveValue('stand-in')
  await expect(form.getByRole('textbox', { name: 'Redirect address for the provider' })).toHaveValue(/\/api\/oidc\/stand-in\/callback$/)
  // An issuer that does not answer as one is refused at its field, and nothing is stored.
  await form.getByLabel('Issuer').fill(`${PROVIDER}/nothing-here`)
  await form.getByLabel('Client ID').fill('e2e-client')
  await form.getByLabel('Client secret').fill(`e2e-${Date.now()}`)
  await form.getByRole('button', { name: 'Save' }).click()
  await expect(form.getByRole('alert')).toBeVisible()
  expect((await entries(page)).some((entry) => entry.slug === 'stand-in')).toBe(false)
  await form.getByLabel('Issuer').fill(ISSUER)
  await form.getByRole('button', { name: 'Save' }).click()
  const list = page.getByTestId('provider-list')
  const row = list.locator('li').filter({ hasText: 'Stand-in' })
  await expect(row).toContainText(ISSUER)
  await expect(row).toContainText('on')
  await row.getByRole('button', { name: 'Edit' }).click()
  await expect(form.getByText('Short name: stand-in')).toBeVisible()
  await form.getByLabel('Name on the button').fill('Stand-in 2')
  await form.getByLabel('The provider checks the second factor itself').uncheck()
  await form.getByRole('button', { name: 'Save' }).click()
  const renamed = list.locator('li').filter({ hasText: 'Stand-in 2' })
  await expect(renamed).toBeVisible()
  // The sign-in page has its button now.
  const signIn = await (await page.request.get('/api/auth/methods')).json()
  expect(signIn.providers).toContainEqual({ slug: 'stand-in', label: 'Stand-in 2' })
  await renamed.getByRole('button', { name: 'Remove' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText(/accounts lose the link/)
  await dialog.getByRole('button', { name: 'Remove' }).click()
  await expect(list.locator('li').filter({ hasText: 'Stand-in 2' })).toHaveCount(0)
  // The authentik card: an address nobody answers at gives the step list with the first step failed, in words.
  const card = page.locator('#sign-in-authentik')
  await card.getByLabel('Address of authentik').fill('http://127.0.0.1:9')
  await card.getByLabel('API token').fill(`e2e-${Date.now()}`)
  await card.getByRole('button', { name: SET_UP }).click()
  const steps = page.getByTestId('authentik-steps')
  await expect(steps).toContainText('Connection to authentik')
  await expect(steps).toContainText('authentik cannot be reached at this address')
  expect(problems).toEqual([])
})

test('35: another issuer asks first in the authentik card; No changes nothing, Yes runs the button again', async ({ page }) => {
  // The server's question is covered by the backend tests; here the card as the operator sees it, over the built page.
  const bodies: Array<Record<string, unknown>> = []
  await page.route('**/api/oidc/authentik/setup', async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    bodies.push(body)
    const stop = { key: 'reached', ok: false, detail: 'another issuer', reason: 'issuer_change', status: 0 }
    const answer = body.confirm_issuer_change === true
      ? { ok: true, steps: [{ key: 'reached', ok: true, detail: 'authentik 2026.8.1' }], links_dropped: 2 }
      : { ok: false, steps: [stop], links_dropped: 0, count: 2 }
    await route.fulfill({ json: answer })
  })
  await page.goto('/settings?tab=server&sub=signin')
  const card = page.locator('#sign-in-authentik')
  await card.getByLabel('Address of authentik').fill('http://127.0.0.1:9')
  await card.getByLabel('API token').fill(`e2e-${Date.now()}`)
  await card.getByRole('button', { name: SET_UP }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('Another issuer is another provider. 2 accounts will have to link again afterwards.')
  // No failure on the page behind it: the button waits for the answer.
  await expect(page.getByTestId('authentik-steps')).toHaveCount(0)
  if (process.env.E2E_SHOT) await page.screenshot({ path: process.env.E2E_SHOT })
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toHaveCount(0)
  expect(bodies.map((body) => body.confirm_issuer_change)).toEqual([false])
  await expect(page.getByTestId('authentik-steps')).toHaveCount(0)
  await card.getByRole('button', { name: SET_UP }).click()
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: SET_UP }).click()
  await expect(dialog).toHaveCount(0)
  expect(bodies.map((body) => body.confirm_issuer_change)).toEqual([false, false, true])
  await expect(page.getByTestId('authentik-steps')).toContainText('Connection to authentik')
})
