// Settings, Server, Sign-in (blueprint 04): three cards. The authentik steps after "Set up", each by its name, a failed
// one with its reason in words (Prüfgang C4), a line while authentik is asked; the provider list with its marks, read
// only while coupled; the form in the blueprint's order; the confirmations with their numbers. The step keys come from
// the server's own list (`STEP_KEYS` in the shared module), so a step without a name shows up here instead of as a
// bare key on the operator's screen.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Me, OidcProvider } from '../api/client'
import i18n from '../i18n'
import de from '../vendor/nexoidc/oidc.de.json'
import en from '../vendor/nexoidc/oidc.en.json'
import ownEn from '../i18n/en.json'
import { useServerSettings } from './settings/ServerCards'
import { SignInPart } from './settings/SignInCards'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

type Files = { readFileSync: (file: string, encoding: string) => string }
const fsName = 'node:fs'
const files = (await import(/* @vite-ignore */ fsName)) as Files

const service = files.readFileSync('../backend/app/vendor/nexoidc/authentik.py', 'utf-8')
const STEP_KEYS = [...(service.match(/^STEP_KEYS = \(([^)]*)\)/m)?.[1] ?? '').matchAll(/"(\w+)"/g)].map((found) => found[1])
const TEXTS = { de: de.oidc, en: en.oidc } as const
type Language = keyof typeof TEXTS
type Step = { key: string; ok: boolean; detail: string; reason?: string; status?: number }

const ME = { id: 1, name: 'robin', display_name: '', role: 'operator', sign_in: 'password', two_factor: true, suite: '' } as unknown as Me
vi.mock('../state/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../state/auth')>()),
  useAuth: () => ({ status: 'signedIn', me: ME, ended: false, refresh: async () => undefined, setMe: () => undefined, signOut: async () => undefined }),
}))

function entry(change: Partial<OidcProvider> = {}): OidcProvider {
  return {
    id: 1, slug: 'sso', label: 'SSO', issuer: 'https://sso.example.com', client_id: 'c', has_secret: true,
    scopes: 'openid profile email', enabled: true, auto_create: false, trusts_second_factor: true, managed: '', position: 0,
    redirect_uri: 'https://brand.example.com/api/oidc/sso/callback', links: 3, editable: true, ...change,
  }
}

/** What the stub answers; `steps` is the set-up run's answer, held back while `gate` is set. */
const server: { steps: Step[]; gate: Promise<void> | null; pending: number; providers: OidcProvider[]; asked: string[] } = {
  steps: [], gate: null, pending: 0, providers: [], asked: [],
}

function answer(method: string, path: string, query: string): unknown {
  server.asked.push(`${method} ${path}${query ? '?' + query : ''}`)
  if (method === 'GET' && path === '/api/settings') return { password_login: true, two_factor_required: false, public_url: '' }
  if (method === 'GET' && path === '/api/oidc/admin/providers') return server.providers
  if (method === 'GET' && path.endsWith('/impact')) return { issuer_change: 3, count: 4, only: 1, only_names: ['clara'] }
  if (method === 'POST' && path === '/api/oidc/authentik/setup') return { ok: server.steps.every((step) => step.ok), steps: server.steps, links_dropped: 0 }
  return undefined
}

let root: Root | null = null
let host: HTMLElement | null = null

async function settle(): Promise<void> {
  for (let quiet = 0, round = 0; quiet < 3; round++) {
    if (round > 200) throw new Error(`settle: ${server.pending} answer(s) still out`)
    await act(async () => {
      for (let i = 0; i < 5; i++) await Promise.resolve()
    })
    quiet = server.pending === 0 ? quiet + 1 : 0
  }
}

async function type(element: Element | null | undefined, value: string): Promise<void> {
  if (!element) throw new Error('nothing to type into')
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => {
    setter.call(element, value)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

async function click(element: Element | null | undefined): Promise<void> {
  if (!element) throw new Error('nothing to click')
  await act(async () => (element as HTMLElement).click())
  await settle()
}

const button = (scope: ParentNode, text: string) => [...scope.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)

function SignIn({ coupled }: { coupled: boolean }) {
  const settings = useServerSettings()
  return <SignInPart server={settings} coupled={coupled} />
}

async function cards(language: Language, coupled = false): Promise<HTMLElement> {
  await i18n.changeLanguage(language)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => root!.render(<SignIn coupled={coupled} />))
  await settle()
  return host
}

/** The authentik card, with address and token typed in; the button not yet pressed. */
async function authentikCard(language: Language): Promise<HTMLElement> {
  const page = await cards(language)
  const card = page.querySelector('#sign-in-authentik')!
  await type(card.querySelector('input[placeholder="https://auth.example.com"]'), 'https://auth.example.com')
  await type(card.querySelector('input[type="password"]'), 'token')
  return page
}

async function setUp(page: HTMLElement): Promise<void> {
  await act(async () => button(page, i18n.t('oidc.authentik.run'))?.click())
}

const rows = (page: HTMLElement) => [...page.querySelectorAll('[data-testid="authentik-steps"] li')].map((row) => row.textContent)

beforeEach(() => {
  Object.assign(server, { steps: [], gate: null, pending: 0, providers: [], asked: [] })
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    server.pending++
    try {
      const method = init.method ?? 'GET'
      const [path, query = ''] = url.split('?')
      if (path === '/api/oidc/authentik/setup' && server.gate) await server.gate
      await Promise.resolve()
      const body = answer(method, path, query)
      if (body === undefined) return new Response(JSON.stringify({ detail: { code: 'not_found' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })
      return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
    } finally {
      server.pending--
    }
  })
})

afterEach(async () => {
  await act(async () => root?.unmount())
  host?.remove()
  root = null
  host = null
  vi.unstubAllGlobals()
})

describe('the authentik steps', () => {
  it('come from the server list', () => {
    expect(STEP_KEYS).toEqual(['reached', 'signingKey', 'mapping', 'provider', 'application', 'filled'])
  })

  it.each(['en', 'de'] as const)('are named in %s, each with a tick', async (language) => {
    server.steps = STEP_KEYS.map((key) => ({ key, ok: true, detail: `found ${key}` }))
    const page = await authentikCard(language)
    await setUp(page)
    await settle()
    const names: Record<string, string> = TEXTS[language].authentik.step
    expect(rows(page)).toEqual(STEP_KEYS.map((key) => `✓${names[key]}`))
    // Everything worked: the token goes from the field, it is not needed again.
    expect((page.querySelector('#sign-in-authentik input[type="password"]') as HTMLInputElement).value).toBe('')
  })

  it.each(['en', 'de'] as const)('say in %s why a step failed, by its name, and keep the token for the next try', async (language) => {
    const detail = 'POST /crypto/certificatekeypairs/generate/ answered 403 (application/json); the log has the answer'
    server.steps = [
      { key: STEP_KEYS[0], ok: true, detail: 'authentik 2026.8.1' },
      { key: STEP_KEYS[1], ok: false, detail, reason: 'token', status: 403 },
    ]
    const page = await authentikCard(language)
    await setUp(page)
    await settle()
    const names: Record<string, string> = TEXTS[language].authentik.step
    const why = TEXTS[language].authentik.why.token.replace('{{status}}', '403')
    expect(rows(page)).toEqual([`✓${names[STEP_KEYS[0]]}`, `✗${names[STEP_KEYS[1]]}${why}`])
    expect(page.textContent).not.toContain(detail)
    expect((page.querySelector('#sign-in-authentik input[type="password"]') as HTMLInputElement).value).toBe('token')
  })

  it('says authentik is being asked while the run is under way, and the last answer goes first', async () => {
    server.steps = [{ key: STEP_KEYS[0], ok: false, detail: 'not reachable', reason: 'unreachable', status: 0 }]
    const page = await authentikCard('en')
    await setUp(page)
    await settle()
    expect(rows(page)).toHaveLength(1)
    let release = () => undefined as void
    server.gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await setUp(page)
    expect(page.querySelector('#sign-in-authentik [role="status"]')?.textContent).toBe(en.oidc.authentik.asking)
    expect(rows(page)).toEqual([])
    server.gate = null
    release()
    await settle()
    expect(page.querySelector('#sign-in-authentik [role="status"]')).toBeNull()
    expect(rows(page)).toEqual([`✗${en.oidc.authentik.step.reached}${en.oidc.authentik.why.unreachable.replace('{{app}}', 'nexbrand')}`])
  })

  it('warns before the run without a public address', async () => {
    const page = await cards('en')
    expect(page.querySelector('[data-testid="authentik-no-address"]')?.textContent).toContain(en.oidc.authentik.noAddress)
  })
})

describe('the three cards', () => {
  it('stand in the blueprint order, the password switch locked while no provider is on', async () => {
    const page = await cards('en')
    expect([...page.querySelectorAll('section h2')].map((h) => h.textContent)).toEqual([
      en.oidc.admin.signInTitle, en.oidc.admin.providersTitle, en.oidc.authentik.title,
    ])
    const password = page.querySelector(`#sign-in input[aria-label="${en.oidc.admin.password}"]`) as HTMLInputElement
    expect(password.checked && password.disabled).toBe(true)
    expect(page.querySelector('#sign-in-providers')?.textContent).toContain(en.oidc.admin.empty)
  })

  it('list each provider with its issuer, its marks and the grip, and open the form with the fields in order', async () => {
    server.providers = [entry(), entry({ id: 2, slug: 'ak', label: 'authentik', managed: 'authentik', enabled: false })]
    const page = await cards('en')
    const list = page.querySelector('[data-testid="provider-list"]')!
    const items = [...list.querySelectorAll('li')]
    expect(items[0].textContent).toContain('https://sso.example.com')
    expect(items[0].textContent).toContain(en.oidc.admin.active)
    expect(items[1].textContent).toContain(en.oidc.admin.inactive)
    expect(items[1].textContent).toContain(en.oidc.admin.managed)
    expect(items[0].querySelector('button[aria-label^="Move"] svg')).not.toBeNull()
    const password = page.querySelector(`#sign-in input[aria-label="${en.oidc.admin.password}"]`) as HTMLInputElement
    expect(password.disabled).toBe(false)
    await click(button(page, en.oidc.admin.add))
    const form = document.querySelector('[data-testid="provider-form"]')!
    const labels = [...form.querySelectorAll('span.font-medium, summary')].map((node) => node.textContent?.trim())
    const order = [en.oidc.admin.label, en.oidc.admin.slug, en.oidc.admin.issuer, en.oidc.admin.clientId, en.oidc.admin.secret,
      en.oidc.admin.redirect, en.oidc.admin.enabled, en.oidc.admin.autoCreate, en.oidc.admin.trustsSecondFactor, ownEn.server.providers.more]
    expect(labels.filter((label) => order.includes(label ?? ''))).toEqual(order)
    // The short name follows the name on the button, the redirect address the short name.
    await type(form.querySelector('input'), 'My Läden')
    expect((form.querySelectorAll('input')[1] as HTMLInputElement).value).toBe('my-laeden')
    expect((form.querySelector(`input[aria-label="${en.oidc.admin.redirect}"]`) as HTMLInputElement).value).toMatch(/\/api\/oidc\/my-laeden\/callback$/)
  })

  it('ask with the number of accounts before another issuer and before removing', async () => {
    server.providers = [entry()]
    const page = await cards('en')
    await click(button(page, en.oidc.admin.edit))
    const form = document.querySelector('[data-testid="provider-form"]')!
    await type(form.querySelectorAll('input')[1], 'https://other.example.com')
    await act(async () => (form as HTMLFormElement).requestSubmit())
    await settle()
    expect(document.body.textContent).toContain(en.oidc.admin.issuerChangeConfirm.replace('{{count}}', '3'))
    expect(server.asked).toContain('GET /api/oidc/admin/providers/1/impact?issuer=https%3A%2F%2Fother.example.com')
    expect(server.asked.some((line) => line.startsWith('PUT '))).toBe(false)
  })

  it('say before removing how many accounts lose the link and how many sign in only through it', async () => {
    server.providers = [entry()]
    const page = await cards('en')
    await click(button(page, en.oidc.admin.remove))
    expect(document.body.textContent).toContain(
      en.oidc.admin.removeConfirm.replace('{{name}}', 'SSO').replace('{{count}}', '4').replace('{{only}}', '1'),
    )
  })

  it('are read only while coupled, the entry of the coupling marked, the authentik card locked', async () => {
    server.providers = [
      entry({ slug: 'oidc', label: 'nexsuite', managed: 'nexsuite', editable: false }),
      entry({ id: 2, slug: 'oidc-own', label: 'authentik', enabled: false, editable: false }),
    ]
    const page = await cards('en', true)
    const list = page.querySelector('[data-testid="provider-list"]')!
    expect(list.textContent).toContain(ownEn.server.providers.coupled)
    expect(list.textContent).toContain(en.oidc.admin.inactive)
    expect(button(page, en.oidc.admin.add)).toBeUndefined()
    expect(button(page, en.oidc.admin.edit)).toBeUndefined()
    expect(button(page, en.oidc.admin.remove)).toBeUndefined()
    expect(list.querySelector('button[aria-label^="Move"]')).toBeNull()
    expect(page.querySelector('[data-testid="authentik-coupled"]')?.textContent).toBe(en.oidc.authentik.why.coupled.replaceAll('{{app}}', 'nexbrand'))
    // With address and token typed in, "Set up" stays locked, and pressing it asks authentik nothing.
    const card = page.querySelector('#sign-in-authentik')!
    await type(card.querySelector('input[placeholder="https://auth.example.com"]'), 'https://auth.example.com')
    await type(card.querySelector('input[type="password"]'), 'token')
    expect((button(page, en.oidc.authentik.run) as HTMLButtonElement).disabled).toBe(true)
    await act(async () => (card.querySelector('form') as HTMLFormElement).requestSubmit())
    await settle()
    expect(server.asked.some((line) => line.includes('/authentik/setup'))).toBe(false)
    expect(page.querySelector('a[href="/api/oidc/authentik/blueprint"]')).toBeNull()
    const password = page.querySelector(`#sign-in input[aria-label="${en.oidc.admin.password}"]`) as HTMLInputElement
    expect(password.disabled).toBe(true)
  })
})
