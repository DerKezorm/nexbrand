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
import type { AuthentikAddress } from '../vendor/nexoidc/oidc'
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

/** The address view of a server that has a public address and sees what the browser uses. */
function addressView(change: Partial<AuthentikAddress> = {}): AuthentikAddress {
  return {
    public_url: 'https://brand.example.com', seen: 'http://localhost:3000', forwarded_proto: '', forwarded_host: '',
    proxy_ignored: false, callback_path: '/api/oidc/authentik/callback',
    redirect_uri: 'https://brand.example.com/api/oidc/authentik/callback', registered_redirect_uri: '', stale: false, ...change,
  }
}

/** What the stub answers; `steps` is the set-up run's answer, held back while `gate` is set. */
const server: {
  steps: Step[]; gate: Promise<void> | null; pending: number; providers: OidcProvider[]; asked: string[]
  /** With a number: the button stops at `issuer_change` with this count until the run comes with the confirmation. */
  ask: number | null
  /** The bodies of the set-up runs. */
  runs: Array<Record<string, unknown>>
  /** Answers for the next set-up runs (first in, first out); without one, `steps` answers. */
  answers: Array<Record<string, unknown>>
  /** The address view and the public address of the settings; `askAddress` is the question a new address meets. */
  address: AuthentikAddress
  settings: Record<string, unknown>
  askAddress: { count: number; address: string; hand: number } | null
  /** The bodies of the saves: "Use it only" (`saved`) and card 1 (`settingsSaved`). */
  saved: Array<Record<string, unknown>>
  settingsSaved: Array<Record<string, unknown>>
} = {
  steps: [], gate: null, pending: 0, providers: [], asked: [], ask: null, runs: [], answers: [], address: addressView(),
  settings: {}, askAddress: null, saved: [], settingsSaved: [],
}

const SETTINGS = { password_login: true, two_factor_required: false, public_url: 'https://brand.example.com' }

const asking = (question: NonNullable<typeof server.askAddress>) =>
  new Response(JSON.stringify({ detail: { code: 'public_url_change', ...question } }), { status: 409, headers: { 'Content-Type': 'application/json' } })

function answer(method: string, path: string, query: string, body: Record<string, unknown> = {}): unknown {
  server.asked.push(`${method} ${path}${query ? '?' + query : ''}`)
  if (method === 'GET' && path === '/api/settings') return server.settings
  if (method === 'PUT' && path === '/api/settings') {
    server.settingsSaved.push(body)
    if (server.askAddress && body.confirm_address !== true) return asking(server.askAddress)
    server.settings = { ...server.settings, public_url: body.public_url }
    return server.settings
  }
  if (method === 'GET' && path === '/api/oidc/authentik/address') return server.address
  if (method === 'POST' && path === '/api/oidc/authentik/address') {
    server.saved.push(body)
    if (server.askAddress && body.confirm !== true) return asking(server.askAddress)
    const url = String(body.public_url)
    server.address = { ...server.address, public_url: url, redirect_uri: url + server.address.callback_path }
    server.settings = { ...server.settings, public_url: url }
    return server.address
  }
  if (method === 'GET' && path === '/api/oidc/admin/providers') return server.providers
  if (method === 'GET' && path.endsWith('/impact')) return { issuer_change: 3, count: 4, only: 1, only_names: ['clara'] }
  if (method === 'POST' && path === '/api/oidc/authentik/setup') {
    server.runs.push(body)
    const queued = server.answers.shift()
    if (queued) return queued
    if (server.ask !== null && body.confirm_issuer_change !== true) {
      const stop = { key: 'reached', ok: false, detail: 'another issuer', reason: 'issuer_change', status: 0 }
      return { ok: false, steps: [stop], links_dropped: 0, count: server.ask }
    }
    return { ok: server.steps.every((step) => step.ok), steps: server.steps, links_dropped: 0 }
  }
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
  Object.assign(server, {
    steps: [], gate: null, pending: 0, providers: [], asked: [], ask: null, runs: [], answers: [], address: addressView(),
    settings: { ...SETTINGS }, askAddress: null, saved: [], settingsSaved: [],
  })
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    server.pending++
    try {
      const method = init.method ?? 'GET'
      const [path, query = ''] = url.split('?')
      if (path === '/api/oidc/authentik/setup' && server.gate) await server.gate
      await Promise.resolve()
      const body = answer(method, path, query, typeof init.body === 'string' ? JSON.parse(init.body) : {})
      if (body instanceof Response) return body
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

  it('ask with the number of accounts before another issuer takes the links: yes runs again with the confirmation, no changes nothing', async () => {
    server.ask = 3
    server.steps = STEP_KEYS.map((key) => ({ key, ok: true, detail: `found ${key}` }))
    const page = await authentikCard('en')
    await setUp(page)
    await settle()
    // Not a failure and not a result: the question, with the shared sentence, and nothing written.
    expect(document.body.textContent).toContain(en.oidc.admin.issuerChangeConfirm_other.replace('{{count}}', '3'))
    expect(rows(page)).toEqual([])
    expect(server.runs).toEqual([{ url: 'https://auth.example.com', token: 'token', confirm_issuer_change: false }])
    // No: the dialog goes, the token stays, no second run, no steps.
    await click(button(document.body, ownEn.common.cancel))
    expect(document.body.textContent).not.toContain(en.oidc.admin.issuerChangeConfirm_other.replace('{{count}}', '3'))
    expect(server.runs).toHaveLength(1)
    expect(rows(page)).toEqual([])
    expect((page.querySelector('#sign-in-authentik input[type="password"]') as HTMLInputElement).value).toBe('token')
    // Yes: the run goes again, with the confirmation, and the steps show.
    await setUp(page)
    await settle()
    await click(document.body.querySelector('[role="dialog"] button[type="submit"]'))
    expect(server.runs.map((run) => run.confirm_issuer_change)).toEqual([false, false, true])
    expect(rows(page)).toHaveLength(STEP_KEYS.length)
    expect(document.body.textContent).not.toContain(en.oidc.admin.issuerChangeConfirm_other.replace('{{count}}', '3'))
  })

  it('asks in german with the shared sentence too', async () => {
    server.ask = 1
    const page = await authentikCard('de')
    await setUp(page)
    await settle()
    expect(document.body.textContent).toContain(de.oidc.admin.issuerChangeConfirm_one.replace('{{count}}', '1'))
  })

  it('proposes the address of the browser without a public address and sets up with it', async () => {
    server.address = addressView({ public_url: '' })
    server.settings = { ...SETTINGS, public_url: '' }
    server.steps = STEP_KEYS.map((key) => ({ key, ok: true, detail: key }))
    const page = await cards('en')
    const words = en.oidc.authentik
    const note = page.querySelector('[data-testid="authentik-no-address"]')
    expect(note?.textContent).toContain(words.noAddress.replace('{{app}}', 'nexbrand'))
    // The suggestion is the browser's own address, and the redirect address the button would register behind it.
    expect(page.querySelector('[data-testid="authentik-proposal"]')?.textContent).toBe(window.location.origin)
    expect(note?.textContent).toContain(`${window.location.origin}/api/oidc/authentik/callback`)
    expect(page.querySelector('[data-testid="authentik-proxy-warning"]')).toBeNull()
    expect(page.querySelector('[data-testid="authentik-stale"]')).toBeNull()
    // "Use it and set up" replaces "Set up" and sends the suggestion with the run.
    expect(button(page, words.run)).toBeUndefined()
    const card = page.querySelector('#sign-in-authentik')!
    await type(card.querySelector('input[placeholder="https://auth.example.com"]'), 'https://auth.example.com')
    await type(card.querySelector('input[type="password"]'), 'token')
    await click(button(page, words.adopt))
    expect(server.runs[0]).toMatchObject({ url: 'https://auth.example.com', confirm_issuer_change: false, public_url: window.location.origin })
    expect(rows(page)).toHaveLength(STEP_KEYS.length)
  })

  it('does not send a suggestion once the server has an address', async () => {
    server.steps = STEP_KEYS.map((key) => ({ key, ok: true, detail: key }))
    const page = await authentikCard('en')
    expect(page.querySelector('[data-testid="authentik-no-address"]')).toBeNull()
    await setUp(page)
    await settle()
    expect(server.runs[0]).toEqual({ url: 'https://auth.example.com', token: 'token', confirm_issuer_change: false })
  })

  it('warns under the suggestion when the server sees another address than the browser uses', async () => {
    server.address = addressView({ public_url: '', seen: 'http://brand-internal:8000' })
    server.settings = { ...SETTINGS, public_url: '' }
    const page = await cards('en')
    expect(page.querySelector('[data-testid="authentik-proxy-warning"]')?.textContent).toBe(
      en.oidc.authentik.proxyWarning.replaceAll('{{app}}', 'nexbrand').replace('{{address}}', 'http://brand-internal:8000'),
    )
  })

  it('uses the suggestion only, and asks first when authentik knows another redirect address', async () => {
    server.address = addressView({ public_url: '' })
    server.settings = { ...SETTINGS, public_url: '' }
    server.askAddress = { count: 1, address: 'http://old.example.com/api/oidc/authentik/callback', hand: 2 }
    const page = await cards('en')
    await click(button(page, en.oidc.authentik.adoptOnly))
    // The question names the redirect address authentik keeps and the entries made by hand; nothing was saved yet.
    const asked = document.querySelector('[role="dialog"]')?.textContent ?? ''
    expect(asked).toContain(i18n.t('oidc.admin.addressChangeConfirm', { address: server.askAddress.address }))
    expect(asked).toContain(i18n.t('oidc.admin.addressChangeHand', { count: 2 }))
    expect(server.saved.map((body) => body.confirm)).toEqual([false])
    expect(server.address.public_url).toBe('')
    await click(button(document.querySelector('[role="dialog"]')!, en.oidc.authentik.adoptOnly))
    expect(server.saved.map((body) => body.confirm)).toEqual([false, true])
    expect(server.address.public_url).toBe(window.location.origin)
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    // With an address the card has its ordinary button again, and no suggestion.
    expect(page.querySelector('[data-testid="authentik-no-address"]')).toBeNull()
    expect(button(page, en.oidc.authentik.run)).toBeTruthy()
  })

  it('says what authentik still knows after the address changed', async () => {
    server.address = addressView({ stale: true, registered_redirect_uri: 'http://old.example.com/api/oidc/authentik/callback' })
    const page = await cards('en')
    expect(page.querySelector('[data-testid="authentik-stale"]')?.textContent).toBe(
      en.oidc.authentik.stale.replace('{{address}}', 'http://old.example.com/api/oidc/authentik/callback'),
    )
  })

  it('shows the address the server names when the run stopped for want of one', async () => {
    server.address = addressView({ public_url: '', seen: 'http://brand-internal:8000' })
    server.settings = { ...SETTINGS, public_url: '' }
    server.answers = [
      { ok: false, links_dropped: 0, steps: [{ key: STEP_KEYS[0], ok: false, detail: 'none', reason: 'public_url_needed', status: 0 }], address: server.address },
    ]
    const page = await cards('en')
    const card = page.querySelector('#sign-in-authentik')!
    await type(card.querySelector('input[placeholder="https://auth.example.com"]'), 'https://auth.example.com')
    await type(card.querySelector('input[type="password"]'), 'token')
    await click(button(page, en.oidc.authentik.adopt))
    expect(rows(page)).toEqual([`✗${en.oidc.authentik.step.reached}${en.oidc.authentik.why.public_url_needed.replaceAll('{{app}}', 'nexbrand')}`])
    expect(page.querySelector('[data-testid="authentik-proxy-warning"]')).not.toBeNull()
  })

  it('asks before the public address of card 1 changes what authentik knows, and saves on yes', async () => {
    server.askAddress = { count: 2, address: 'https://brand.example.com/api/oidc/authentik/callback', hand: 0 }
    const page = await cards('en')
    const card = page.querySelector('#sign-in') as HTMLElement
    await type(card.querySelector('input[placeholder="https://brand.example.com"]'), 'https://new.example.com')
    await click(button(card, ownEn.common.save))
    const asked = document.querySelector('[role="dialog"]')?.textContent ?? ''
    expect(asked).toContain(i18n.t('oidc.admin.addressChangeConfirm', { address: server.askAddress.address }))
    expect(asked).not.toContain(en.oidc.admin.addressChangeHand_other.slice(0, 20))
    expect(server.settingsSaved.map((body) => body.confirm_address)).toEqual([false])
    expect(server.settings.public_url).toBe('https://brand.example.com')
    await click(button(document.querySelector('[role="dialog"]')!, ownEn.common.save))
    expect(server.settingsSaved.map((body) => body.confirm_address)).toEqual([false, true])
    expect(server.settings.public_url).toBe('https://new.example.com')
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })

  it('names the count in the reason of a step too: a plural text without one would show its bare key', async () => {
    // Two failed steps: the first is no question, so the run is a result and the second step's reason is read.
    server.answers = [
      {
        ok: false, links_dropped: 0, count: 3,
        steps: [
          { key: STEP_KEYS[0], ok: false, detail: 'x', reason: 'unreachable', status: 0 },
          { key: STEP_KEYS[1], ok: false, detail: 'y', reason: 'issuer_change', status: 0 },
        ],
      },
    ]
    const page = await authentikCard('en')
    await setUp(page)
    await settle()
    expect(rows(page)[1]).toContain(en.oidc.authentik.why.issuer_change_other.replace('{{count}}', '3'))
    expect(page.textContent).not.toContain('oidc.authentik.why.issuer_change')
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
    expect(document.body.textContent).toContain(en.oidc.admin.issuerChangeConfirm_other.replace('{{count}}', '3'))
    expect(server.asked).toContain('GET /api/oidc/admin/providers/1/impact?issuer=https%3A%2F%2Fother.example.com')
    expect(server.asked.some((line) => line.startsWith('PUT '))).toBe(false)
  })

  it('say before removing how many accounts lose the link and how many sign in only through it', async () => {
    server.providers = [entry()]
    const page = await cards('en')
    await click(button(page, en.oidc.admin.remove))
    expect(document.body.textContent).toContain(
      en.oidc.admin.removeConfirm_other.replace('{{name}}', 'SSO').replace('{{count}}', '4').replace('{{only}}', '1'),
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
