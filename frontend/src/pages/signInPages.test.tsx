// Sign-in through providers as the pages show it: a button per active provider on the sign-in page,
// below "or" and in the order of the list; with the password sign-in off only the buttons and the operator's way in;
// the code step after an untrusted provider; only known codes from the address in words; "Continue with …" on the
// invitation page; My account with a row per provider, its name after linking, the address offered; the operator's
// account list with the providers as marks and "Unlink" with the own password. The server is a stub; nothing waits for
// a clock.
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Me } from '../api/client'
import i18n from '../i18n'
import oidc from '../vendor/nexoidc/oidc.en.json'
import own from '../i18n/en.json'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

type Answer = { status: number; body?: unknown }
type Handler = (method: string, path: string, body: unknown) => Answer | undefined

const server: { handler: Handler; calls: { method: string; path: string; body: unknown }[]; pending: number } = {
  handler: () => undefined,
  calls: [],
  pending: 0,
}

const ME = { id: 1, name: 'robin', display_name: '', role: 'operator', sign_in: 'password', email: 'robin@example.com', suite: '' } as unknown as Me
const auth: { status: 'signedIn' | 'signedOut'; me: Me | null; refreshed: number } = { status: 'signedOut', me: null, refreshed: 0 }
vi.mock('../state/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../state/auth')>()),
  useAuth: () => ({
    status: auth.status,
    me: auth.me,
    ended: false,
    refresh: async () => {
      auth.refreshed++
    },
    setMe: () => undefined,
    signOut: async () => undefined,
  }),
}))

let root: Root | null = null
let host: HTMLElement | null = null
const assigned: string[] = []

beforeEach(() => {
  server.calls = []
  server.handler = () => undefined
  auth.status = 'signedOut'
  auth.me = null
  auth.refreshed = 0
  assigned.length = 0
  vi.stubGlobal('location', { ...window.location, assign: (url: string) => assigned.push(url) })
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const path = url.split('?')[0]
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    server.calls.push({ method, path, body })
    server.pending++
    try {
      await Promise.resolve()
      const answer = server.handler(method, path, body) ?? { status: 404, body: { detail: { code: 'not_found' } } }
      if (answer.status === 204) return new Response(null, { status: 204 })
      return new Response(JSON.stringify(answer.body ?? {}), { status: answer.status, headers: { 'Content-Type': 'application/json' } })
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

async function settle(): Promise<void> {
  for (let quiet = 0, round = 0; quiet < 3; round++) {
    if (round > 200) throw new Error(`settle: ${server.pending} answer(s) still out`)
    await act(async () => {
      for (let i = 0; i < 5; i++) await Promise.resolve()
    })
    quiet = server.pending === 0 ? quiet + 1 : 0
  }
}

async function mount(ui: ReactNode, path: string): Promise<HTMLElement> {
  await i18n.changeLanguage('en')
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => root!.render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>))
  await settle()
  return host
}

async function click(element: Element | null | undefined): Promise<void> {
  if (!element) throw new Error('nothing to click')
  await act(async () => (element as HTMLElement).click())
  await settle()
}

async function type(element: Element | null | undefined, value: string): Promise<void> {
  if (!element) throw new Error('nothing to type into')
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => {
    setter.call(element, value)
    element.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const button = (text: string) => [...document.body.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)
const providerButtons = (page: HTMLElement) => [...page.querySelectorAll('[data-testid="provider-buttons"] button')].map((b) => b.textContent)
/** The line "or" between the form and the buttons. */
const orLine = (page: HTMLElement) => [...page.querySelectorAll('div')].some((d) => d.textContent === oidc.oidc.login.or)
const TWO = [{ slug: 'sso', label: 'SSO' }, { slug: 'work', label: 'Work' }]

async function login(path: string, methods: unknown): Promise<HTMLElement> {
  server.handler = (_m, p) => (p === '/api/auth/methods' ? { status: 200, body: methods } : undefined)
  const { LoginPage } = await import('./AuthPages')
  return mount(
    <Routes>
      <Route path="login" element={<LoginPage />} />
    </Routes>,
    path,
  )
}

describe('the sign-in page', () => {
  it('shows a button per active provider below the password form and "or", in the order of the list', async () => {
    const page = await login('/login', { password: true, providers: TWO })
    expect(page.querySelector('input[type=password]')).not.toBeNull()
    expect(orLine(page)).toBe(true)
    expect(providerButtons(page)).toEqual(['Sign in with SSO', 'Sign in with Work'])
    await click(button('Sign in with Work'))
    expect(assigned).toEqual(['/api/oidc/work/start'])
  })

  it('takes the page asked for along to the provider', async () => {
    const page = await login('/login?next=%2Fc%2Fabc', { password: true, providers: TWO })
    await click(page.querySelector('[data-testid="provider-buttons"] button'))
    expect(assigned).toEqual(['/api/oidc/sso/start?next=%2Fc%2Fabc'])
  })

  it('with the password sign-in off shows only the buttons and the operator\'s way in', async () => {
    const page = await login('/login', { password: false, providers: TWO })
    expect(page.querySelector('input[type=password]')).toBeNull()
    expect(orLine(page)).toBe(false)
    expect(providerButtons(page)).toEqual(['Sign in with SSO', 'Sign in with Work'])
    await click(button(oidc.oidc.login.operator))
    expect(page.querySelector('input[type=password]')).not.toBeNull()
  })

  it('without any provider keeps the password form and no buttons', async () => {
    const page = await login('/login', { password: true, providers: [] })
    expect(page.querySelector('[data-testid="provider-buttons"]')).toBeNull()
    expect(orLine(page)).toBe(false)
  })

  it('says a known code from the address in words, and nothing for anything else', async () => {
    const known = await login('/login?error=oidc_no_account', { password: true, providers: TWO })
    expect(known.querySelector('[role="alert"]')?.textContent).toBe(oidc.oidc.error.oidc_no_account)
    await act(async () => root?.unmount())
    host?.remove()
    const coupled = await login('/login?error=suite_no_account', { password: true, providers: TWO })
    expect(coupled.querySelector('[role="alert"]')?.textContent).toBe(own.errors.suite_no_account)
    await act(async () => root?.unmount())
    host?.remove()
    const strange = await login('/login?error=wrong_credentials', { password: true, providers: TWO })
    expect(strange.querySelector('[role="alert"]')).toBeNull()
  })

  it('asks for the code after a provider that is not trusted with the second factor', async () => {
    const page = await login('/login?step=code', { password: true, providers: TWO })
    expect(page.querySelector('input[autocomplete="one-time-code"]')).not.toBeNull()
    expect(page.querySelector('input[type=password]')).toBeNull()
  })
})

describe('the invitation page', () => {
  it('offers "Continue with …" per provider below the password form and "or"', async () => {
    server.handler = (_m, p) => {
      if (p === '/api/auth/methods') return { status: 200, body: { password: true, providers: TWO } }
      if (p.startsWith('/api/invite/')) return { status: 200, body: { space: null, role: null, min_password: 12, signed_in_as: null } }
      return undefined
    }
    const { InvitePage } = await import('./AuthPages')
    const page = await mount(
      <Routes>
        <Route path="invite/:token" element={<InvitePage />} />
      </Routes>,
      '/invite/abcdefghijklmnopqrstuv',
    )
    const form = page.querySelector('form')!
    const buttons = page.querySelector('[data-testid="provider-buttons"]')!
    expect(form.compareDocumentPosition(buttons) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(providerButtons(page)).toEqual(['Continue with SSO', 'Continue with Work'])
    await click(button('Continue with SSO'))
    expect(assigned).toEqual(['/api/oidc/sso/start?invite=abcdefghijklmnopqrstuv'])
  })
})

describe('my account', () => {
  async function mine(providers: unknown, me: Partial<Me> = {}, path = '/account?tab=security'): Promise<HTMLElement> {
    auth.status = 'signedIn'
    auth.me = { ...ME, ...me } as Me
    server.handler = (method, p) => {
      if (p === '/api/oidc/me') return { status: 200, body: providers }
      if (method === 'POST' && p === '/api/oidc/me/address') return { status: 200, body: { email: 'robin.sso@example.com' } }
      if (method === 'POST' && p === '/api/oidc/work/link') return { status: 200, body: { url: 'https://work.example.com/authorize?x=1' } }
      return undefined
    }
    const { MyProviders } = await import('../components/MyProviders')
    const params = new URLSearchParams(path.split('?')[1])
    return mount(<MyProviders me={auth.me} linked={params.get('linked')} />, path)
  }

  it('shows a row per active provider with its state, links with the password and says the name after linking', async () => {
    const page = await mine(
      [{ slug: 'sso', label: 'SSO', linked: true, address: null }, { slug: 'work', label: 'Work', linked: false, address: null }],
      {},
      '/account?linked=sso',
    )
    const rows = [...page.querySelectorAll('[data-testid="my-providers"] li')]
    expect(rows.map((row) => row.textContent)).toEqual([
      `SSO${oidc.oidc.account.linked}${oidc.oidc.account.unlink}`,
      `Work${oidc.oidc.account.notLinked}${oidc.oidc.account.link}`,
    ])
    expect(page.textContent).toContain(own.me.oidc.linkedTo.replace('{{name}}', 'SSO'))
    expect(page.textContent).not.toContain('linked to sso')
    await click(rows[1].querySelector('button'))
    await type(rows[1].querySelector('input[type=password]'), 'the password')
    await act(async () => (rows[1].querySelector('form') as HTMLFormElement).requestSubmit())
    await settle()
    expect(server.calls.find((call) => call.path === '/api/oidc/work/link')?.body).toEqual({ password: 'the password' })
    expect(assigned).toEqual(['https://work.example.com/authorize?x=1'])
  })

  it('offers the address the provider knows, and takes it only when asked', async () => {
    const page = await mine([{ slug: 'sso', label: 'SSO', linked: true, address: 'robin.sso@example.com' }])
    expect(page.textContent).toContain(own.me.oidc.addressOffer.replace('{{provider}}', 'SSO').replace('{{address}}', 'robin.sso@example.com'))
    expect(server.calls.some((call) => call.path === '/api/oidc/me/address')).toBe(false)
    await click(button(own.me.oidc.takeAddress))
    expect(server.calls.filter((call) => call.method === 'POST' && call.path === '/api/oidc/me/address')).toHaveLength(1)
    expect(server.calls.find((call) => call.path === '/api/oidc/me/address')?.body).toEqual({ slug: 'sso' })
    expect(auth.refreshed).toBe(1)
  })

  it('keeps the last link of an account through the provider only', async () => {
    const page = await mine([{ slug: 'sso', label: 'SSO', linked: true, address: null }], { sign_in: 'oidc' })
    expect(button(oidc.oidc.account.unlink)).toBeUndefined()
    expect(page.textContent).toContain(oidc.oidc.account.only.replace('{{name}}', 'SSO'))
    expect(button(oidc.oidc.account.link)).toBeUndefined()
  })
})

describe('the operator\'s account list', () => {
  it('shows each account\'s providers as marks and unlinks one with the own password', async () => {
    auth.status = 'signedIn'
    auth.me = ME
    const anna = { ...ME, id: 2, name: 'anna', role: 'member', spaces: 0, locked: false, created_at: '2026-10-01T00:00:00Z', last_seen_at: null,
      providers: [{ id: 7, slug: 'sso', label: 'SSO', managed: '' }] }
    server.handler = (method, p) => {
      if (p === '/api/accounts') return { status: 200, body: [{ ...ME, spaces: 0, locked: false, created_at: '2026-10-01T00:00:00Z', last_seen_at: null, providers: [] }, anna] }
      if (p === '/api/invites') return { status: 200, body: [] }
      if (method === 'DELETE' && p === '/api/oidc/admin/accounts/2/links/7') return { status: 204 }
      return undefined
    }
    const { AccountsCard } = await import('./settings/ServerCards')
    const page = await mount(<AccountsCard />, '/settings')
    expect([...page.querySelectorAll('[data-testid="account-providers"]')].map((row) => row.textContent)).toEqual(['SSO'])
    await click(button(own.server.unlinkProvider.replace('{{name}}', 'SSO')))
    expect(document.body.textContent).toContain(own.server.unlinkConfirm.replace('{{account}}', 'anna').replace('{{name}}', 'SSO'))
    await type(document.querySelector('[role="dialog"] input[type=password]'), 'my own password')
    await act(async () => (document.querySelector('[role="dialog"] form') as HTMLFormElement).requestSubmit())
    await settle()
    expect(server.calls.find((call) => call.method === 'DELETE' && call.path === '/api/oidc/admin/accounts/2/links/7')?.body).toEqual({
      current_password: 'my own password',
    })
  })
})
