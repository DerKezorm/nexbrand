// Accounts, access and the session as the pages show them (Prüfgang 05.10.2026, block 3): the session check of an open
// page (A8), the access dialog for readers and managers (D4, D5), blocking and the list while connected (F1, G1), the
// mail box of an invitation (F23) and the pages behind a link that does not hold (G4). The server is a stub that
// answers by path; nothing waits for a clock except the session check, which runs on fake timers.
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Me } from '../api/client'
import i18n from '../i18n'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

type Answer = { status: number; body?: unknown }
type Handler = (method: string, path: string, body: unknown) => Answer | Promise<Answer> | undefined

const server: { handler: Handler; calls: { method: string; path: string; body: unknown }[]; pending: number } = {
  handler: () => undefined,
  calls: [],
  pending: 0,
}

function stubFetch() {
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const path = url.split('?')[0]
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    server.calls.push({ method, path, body })
    server.pending++
    try {
      await Promise.resolve()
      const answer = (await server.handler(method, path, body)) ?? { status: 404, body: { detail: { code: 'not_found' } } }
      if (answer.status === 204) return new Response(null, { status: 204 })
      return new Response(JSON.stringify(answer.body ?? {}), { status: answer.status, headers: { 'Content-Type': 'application/json' } })
    } finally {
      server.pending--
    }
  })
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

async function mount(ui: ReactNode, path = '/'): Promise<HTMLElement> {
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
  const field = element as HTMLInputElement
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => {
    setter.call(field, value)
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const buttons = (text: string) => [...document.body.querySelectorAll('button, a')].filter((b) => b.textContent?.trim() === text)

const ME: Me = {
  id: 1,
  name: 'robin',
  display_name: '',
  role: 'operator',
  sign_in: 'password',
  email: '',
  language: 'en',
  mail: true,
  suite: 'off',
} as unknown as Me

const auth = { me: ME as Me | null }
vi.mock('../state/auth', async (importOriginal) => {
  const real = await importOriginal<typeof import('../state/auth')>()
  return {
    ...real,
    useAuth: () => (auth.me ? { status: 'signedIn', me: auth.me, ended: false, refresh: async () => undefined, setMe: () => undefined, signOut: async () => undefined } : real.useAuth()),
  }
})
vi.mock('../state/brands', () => ({ useBrands: () => ({ refresh: async () => undefined, space: () => undefined, spaces: [] }) }))

beforeEach(() => {
  server.handler = () => undefined
  server.calls = []
  server.pending = 0
  auth.me = ME
  stubFetch()
})

afterEach(async () => {
  await act(async () => root?.unmount())
  host?.remove()
  root = null
  host = null
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

// --- A8: the open page notices an ended session within seconds ------------------------------------------------------

describe('an open page whose session ends', () => {
  it('asks after its session every few seconds and sends the sign-in a reason', async () => {
    auth.me = null
    const { AuthProvider, SESSION_MS, useAuth } = await import('../state/auth')
    let alive = true
    server.handler = (_method, path) => {
      if (path === '/api/setup') return { status: 200, body: { needs_setup: false, signed_in: alive } }
      if (path === '/api/auth/me') return alive ? { status: 200, body: ME } : { status: 401, body: { detail: { code: 'sign_in_required' } } }
    }
    const seen: { status?: string; ended?: boolean } = {}
    function Probe() {
      const state = useAuth()
      seen.status = state.status
      seen.ended = state.ended
      return null
    }
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    await mount(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    expect(seen.status).toBe('signedIn')
    const asked = () => server.calls.filter((c) => c.path === '/api/auth/me').length
    const before = asked()
    await act(async () => vi.advanceTimersByTime(SESSION_MS))
    await settle()
    expect(asked()).toBe(before + 1)
    // Blocked in nexsuite, or signed out everywhere: the next check finds out, with nothing else loading.
    alive = false
    await act(async () => vi.advanceTimersByTime(SESSION_MS))
    await settle()
    expect(seen.status).toBe('signedOut')
    expect(seen.ended).toBe(true)
    expect(SESSION_MS).toBeLessThanOrEqual(5_000)
  })

  it('signing out here is no ended session, even with a check under way', async () => {
    auth.me = null
    const { AuthProvider, SESSION_MS, useAuth } = await import('../state/auth')
    let held: ((answer: Answer) => void) | null = null
    let checks = 0
    server.handler = (_method, path) => {
      if (path === '/api/setup') return { status: 200, body: { needs_setup: false, signed_in: true } }
      if (path === '/api/auth/logout') return { status: 204 }
      if (path === '/api/auth/me') {
        // The first answer is the load; the check after it is held until the own sign-out went through.
        if (checks++ === 0) return { status: 200, body: ME }
        return new Promise<Answer>((resolve) => (held = resolve))
      }
    }
    const seen: { ended?: boolean; signOut?: () => Promise<void> } = {}
    function Probe() {
      const state = useAuth()
      seen.ended = state.ended
      seen.signOut = state.signOut
      return null
    }
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    await mount(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    )
    await act(async () => vi.advanceTimersByTime(SESSION_MS))
    await act(async () => {
      for (let i = 0; i < 5; i++) await Promise.resolve()
    })
    expect(held).not.toBeNull()
    await act(async () => seen.signOut!())
    held!({ status: 401, body: { detail: { code: 'sign_in_required' } } })
    await settle()
    expect(seen.ended).toBe(false)
  })

  it('the sign-in says why', async () => {
    auth.me = null
    const { LoginPage } = await import('./AuthPages')
    const { AuthProvider } = await import('../state/auth')
    server.handler = (_method, path) => {
      if (path === '/api/setup') return { status: 200, body: { needs_setup: false, signed_in: false } }
      if (path === '/api/auth/methods') return { status: 200, body: { password: true, oidc: false, oidc_name: '' } }
    }
    const page = await mount(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
      '/login?next=%2F&ended=1',
    )
    expect(page.textContent).toContain(i18n.t('auth.login.ended'))
  })
})

// --- D4, D5: the access dialog ----------------------------------------------------------------------------------------

const LISTING = {
  space: 'Studio',
  members: [
    { name: 'robin', role: 'manage', you: false },
    { name: 'anna', role: 'read', you: true },
  ],
  teams: [{ id: 3, name: 'Design', color: '#2f7bff', role: 'write', people: 2 }],
  count: 4,
  invites: [],
  asked: [],
  role: 'read',
  suite: false,
  managed: false,
}

const SPACE = { id: 7, name: 'Studio', color: '#2f7bff', role: 'read' as const, client: 'c1', members: [], teams: [] }

describe('the access dialog', () => {
  it('shows a reader who has access, with the teams, and no form', async () => {
    auth.me = { ...ME, role: 'member', name: 'anna' } as Me
    server.handler = (_m, path) => (path === '/api/spaces/7/members' ? { status: 200, body: LISTING } : undefined)
    const { MembersDialog } = await import('../components/MembersDialog')
    await mount(<MembersDialog space={SPACE} onClose={() => undefined} />)
    const text = document.body.textContent ?? ''
    expect(text).toContain('Design')
    expect(text).toContain(i18n.t('members.teams'))
    expect(text).toContain(i18n.t('members.count', { count: 4 }))
    expect(text).toContain(i18n.t('members.readOnly'))
    expect(text).not.toContain(i18n.t('errors.forbidden'))
    expect(document.body.querySelector('select')).toBeNull()
    expect(document.body.querySelector('form')).toBeNull()
    // Leaving stays possible.
    expect(buttons(i18n.t('members.leave'))).toHaveLength(1)
  })

  it('lets a manager see and withdraw an invitation by name', async () => {
    let asked = [{ id: 11, name: 'dora', role: 'write', at: '2026-10-05T08:00:00Z' }]
    server.handler = (method, path) => {
      if (path === '/api/spaces/7/members') return { status: 200, body: { ...LISTING, role: 'manage', asked } }
      if (method === 'DELETE' && path === '/api/spaces/7/asked/11') {
        asked = []
        return { status: 204 }
      }
    }
    const { MembersDialog } = await import('../components/MembersDialog')
    await mount(<MembersDialog space={{ ...SPACE, role: 'manage' }} onClose={() => undefined} />)
    expect(document.body.querySelector('[data-testid="space-asked"]')?.textContent).toContain('dora')
    await click(document.body.querySelector('[data-testid="space-asked"] button'))
    expect(server.calls.some((c) => c.method === 'DELETE' && c.path === '/api/spaces/7/asked/11')).toBe(true)
    expect(document.body.querySelector('[data-testid="space-asked"]')).toBeNull()
  })

  it('offers the mail only with an address, and then ticked', async () => {
    server.handler = (method, path) => {
      if (path === '/api/spaces/7/members') return { status: 200, body: { ...LISTING, role: 'manage' } }
      if (method === 'POST' && path === '/api/spaces/7/invites') return { status: 201, body: { id: 1, role: 'write', email: 'x@example.com', link: 'https://brand.example.com/invite/abc', sent: true, expires_at: '2026-10-12T00:00:00Z' } }
    }
    const { MembersDialog } = await import('../components/MembersDialog')
    await mount(<MembersDialog space={{ ...SPACE, role: 'manage' }} onClose={() => undefined} />)
    expect(document.body.querySelector('input[type="checkbox"]')).toBeNull()
    await type(document.body.querySelector('input[type="email"]'), 'x@example.com')
    const box = document.body.querySelector<HTMLInputElement>('input[type="checkbox"]')
    expect(box?.checked).toBe(true)
    await click(buttons(i18n.t('invite.create'))[0])
    const sent = server.calls.find((c) => c.method === 'POST' && c.path === '/api/spaces/7/invites')
    expect(sent?.body).toMatchObject({ email: 'x@example.com', send: true })
  })
})

// --- F1, G1: blocking, and the list while connected ------------------------------------------------------------------

const ACCOUNTS = [
  { ...ME, spaces: 1, locked: false, blocked: false, has_password: true, created_at: '2026-10-01T00:00:00Z', last_seen_at: null },
  { ...ME, id: 2, name: 'anna', role: 'member', spaces: 1, locked: false, blocked: false, has_password: true, created_at: '2026-10-01T00:00:00Z', last_seen_at: null },
  { ...ME, id: 3, name: 'ben', role: 'member', spaces: 0, locked: false, blocked: true, has_password: true, created_at: '2026-10-01T00:00:00Z', last_seen_at: null },
]

describe('the accounts', () => {
  it('can be blocked by the operator, with the password', async () => {
    server.handler = (method, path) => {
      if (path === '/api/accounts') return { status: 200, body: ACCOUNTS }
      if (path === '/api/invites') return { status: 200, body: [] }
      if (method === 'POST' && path === '/api/accounts/2/block') return { status: 204 }
    }
    const { AccountsCard } = await import('./settings/ServerCards')
    await mount(<AccountsCard />)
    expect(buttons(i18n.t('server.block'))).toHaveLength(1)
    expect(buttons(i18n.t('server.unblock'))).toHaveLength(1)
    await click(buttons(i18n.t('server.block'))[0])
    expect(document.body.textContent).toContain(i18n.t('server.confirm.block.title', { name: 'anna' }))
    await type(document.body.querySelector('input[type="password"]'), 'own password')
    await click(buttons(i18n.t('server.confirm.block.button')).at(-1))
    const sent = server.calls.find((c) => c.method === 'POST' && c.path === '/api/accounts/2/block')
    expect(sent?.body).toEqual({ current_password: 'own password' })
  })

  it('are listed while connected, without anything to change', async () => {
    server.handler = (_m, path) => (path === '/api/accounts' ? { status: 200, body: ACCOUNTS } : undefined)
    const { AccountsCard } = await import('./settings/ServerCards')
    const page = await mount(<AccountsCard readOnly />)
    expect(page.textContent).toContain('anna')
    expect(page.textContent).toContain(i18n.t('server.blocked'))
    expect(page.textContent).toContain(i18n.t('suite.managedAccounts'))
    expect(page.querySelectorAll('button')).toHaveLength(0)
    expect(server.calls.some((c) => c.path === '/api/invites')).toBe(false)
  })
})

// --- G4: pages behind a link that does not hold ----------------------------------------------------------------------

describe('a link that does not hold', () => {
  for (const [code, title, text] of [
    ['invite_expired', 'auth.invite.expiredTitle', 'auth.invite.expiredText'],
    ['invite_invalid', 'auth.invite.invalidTitle', 'auth.invite.invalidText'],
  ] as const) {
    it(`says why (${code}) and leads back to the sign-in`, async () => {
      auth.me = null
      server.handler = (_m, path) => {
        if (path.startsWith('/api/invite/')) return { status: 404, body: { detail: { code } } }
        if (path === '/api/auth/methods') return { status: 200, body: { password: true, oidc: false, oidc_name: '' } }
      }
      const { InvitePage } = await import('./AuthPages')
      const { AuthProvider } = await import('../state/auth')
      const page = await mount(
        <AuthProvider>
          <Routes>
            <Route path="invite/:token" element={<InvitePage />} />
          </Routes>
        </AuthProvider>,
        '/invite/abcdefghijklmnopqrstuv',
      )
      expect(page.textContent).toContain(i18n.t(title))
      expect(page.textContent).toContain(i18n.t(text))
      expect(page.querySelector('a[href="/login"]')?.textContent).toBe(i18n.t('auth.backToLogin'))
    })
  }

  it('the emergency access while connected leads back and does not speak of members', async () => {
    auth.me = null
    server.handler = (_m, path) => {
      if (path === '/api/setup') return { status: 200, body: { needs_setup: false, signed_in: false } }
      if (path === '/api/auth/methods') return { status: 200, body: { password: false, oidc: true, oidc_name: 'nexsuite', suite: true } }
    }
    const { LoginPage } = await import('./AuthPages')
    const { AuthProvider } = await import('../state/auth')
    let where = ''
    function Where() {
      where = useLocation().pathname
      return null
    }
    const page = await mount(
      <AuthProvider>
        <LoginPage emergency />
        <Where />
      </AuthProvider>,
      '/notzugang',
    )
    expect(where).toBe('/notzugang')
    expect(page.textContent).toContain(i18n.t('suite.emergencyTitle'))
    expect(page.textContent).not.toContain(i18n.t('auth.login.passwordOff'))
    expect(page.querySelector('a[href="/login"]')?.textContent).toBe(i18n.t('auth.backToLogin'))
  })
})
