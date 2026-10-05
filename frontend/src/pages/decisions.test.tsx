// What was decided after the check of 05.10.2026, as the pages show it: the switch for team leads (D3), the open
// links of a blocked or deleted account (A15), signing in as someone else while connected (B11) and who stops being an
// operator when disconnecting (B17). The server is a stub that answers by path; nothing waits for a clock.
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
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

async function mount(ui: ReactNode, path = '/', language = 'en'): Promise<HTMLElement> {
  await i18n.changeLanguage(language)
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
const calls = (method: string, path: string) => server.calls.filter((c) => c.method === method && c.path === path)

const ME = {
  id: 1,
  name: 'robin',
  display_name: '',
  role: 'operator',
  sign_in: 'password',
  email: '',
  language: 'en',
  mail: true,
  suite: '',
} as unknown as Me

const auth: { me: Me | null } = { me: ME }
vi.mock('../state/auth', async (importOriginal) => {
  const real = await importOriginal<typeof import('../state/auth')>()
  return {
    ...real,
    useAuth: () => (auth.me ? { status: 'signedIn', me: auth.me, ended: false, refresh: async () => undefined, setMe: () => undefined, signOut: async () => undefined } : real.useAuth()),
  }
})

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
  vi.unstubAllGlobals()
})

// --- D3: team leads change their teams only when the operator allows it --------------------------------------------

const DIRECTORY = {
  me: 2,
  people: [
    { id: 1, name: 'robin', display_name: 'Robin', avatar: null, blocked: false },
    { id: 2, name: 'anna', display_name: 'Anna', avatar: null, blocked: false },
  ],
  teams: [{ id: 5, name: 'Design', color: '#2f7bff', lead: 2, source: 'local', members: [2], size: 1 }],
}

describe('team leads', () => {
  it('get the switch from the operator, off from the start', async () => {
    let allowed = false
    server.handler = (method, path, body) => {
      if (path === '/api/directory') return { status: 200, body: { ...DIRECTORY, me: 1 } }
      if (path === '/api/settings' && method === 'GET') return { status: 200, body: { team_leads_edit: allowed } }
      if (path === '/api/settings' && method === 'PUT') {
        allowed = (body as { team_leads_edit: boolean }).team_leads_edit
        return { status: 200, body: { team_leads_edit: allowed } }
      }
      if (path === '/api/auth/me') return { status: 200, body: ME }
    }
    const { TeamsCard } = await import('../components/Teams')
    const page = await mount(<TeamsCard />)
    const box = page.querySelector(`input[aria-label="${i18n.t('teams.leadsSwitch')}"]`) as HTMLInputElement
    expect(box).not.toBeNull()
    expect(box.checked).toBe(false)
    await click(box)
    expect(calls('PUT', '/api/settings').map((c) => c.body)).toEqual([{ team_leads_edit: true }])
    expect(box.checked).toBe(true)
  })

  it('see no way to change their team unless the operator allows it', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/directory') return { status: 200, body: DIRECTORY }
    }
    auth.me = { ...ME, id: 2, name: 'anna', role: 'member', may_edit_led_teams: false } as Me
    const { TeamsCard } = await import('../components/Teams')
    const page = await mount(<TeamsCard />)
    expect(buttons(i18n.t('teams.edit'))).toHaveLength(0)
    expect(page.querySelector(`input[aria-label="${i18n.t('teams.leadsSwitch')}"]`)).toBeNull()
    expect(calls('GET', '/api/settings')).toHaveLength(0)
    await act(async () => root?.unmount())
    host?.remove()
    auth.me = { ...ME, id: 2, name: 'anna', role: 'member', may_edit_led_teams: true } as Me
    await mount(<TeamsCard />)
    expect(buttons(i18n.t('teams.edit'))).toHaveLength(1)
  })
})

// --- A15: the open links of a blocked or deleted account ------------------------------------------------------------

const ACCOUNTS = [
  { id: 1, name: 'robin', display_name: '', role: 'operator', sign_in: 'password', spaces: 1, locked: false, blocked: false, open_links: 0 },
  { id: 3, name: 'wim', display_name: 'Wim', role: 'member', sign_in: 'password', spaces: 1, locked: false, blocked: false, open_links: 2 },
  { id: 4, name: 'mia', display_name: 'Mia', role: 'member', sign_in: 'password', spaces: 1, locked: false, blocked: true, open_links: 1 },
]

describe('the open links of an account', () => {
  it('are named in the block dialog and withdrawn once with the password typed there', async () => {
    let release: () => void = () => undefined
    server.handler = (method, path) => {
      if (path === '/api/accounts') return { status: 200, body: ACCOUNTS }
      if (path === '/api/invites') return { status: 200, body: [] }
      if (path === '/api/accounts/3/links/withdraw') return new Promise<Answer>((done) => (release = () => done({ status: 200, body: { withdrawn: 2 } })))
      if (method === 'POST' && path === '/api/accounts/3/block') return { status: 204 }
    }
    const { AccountsCard } = await import('./settings/ServerCards')
    const page = await mount(<AccountsCard />)
    expect(page.textContent).toContain(i18n.t('server.openLinks', { count: 2 }))
    await click(buttons(i18n.t('server.block'))[0])
    // Title and box name the person alike, by the name others see.
    expect(document.body.querySelector('[role="dialog"]')?.getAttribute('aria-label')).toBe(i18n.t('server.confirm.block.title', { name: 'Wim' }))
    const note = document.body.querySelector('[data-testid="open-links"]')
    expect(note?.textContent).toContain(i18n.t('server.linksStay', { count: 2, name: 'Wim' }))
    const withdraw = [...(note?.querySelectorAll('button') ?? [])].find((b) => b.textContent?.trim() === i18n.t('server.withdrawLinks'))
    expect((withdraw as HTMLButtonElement).disabled).toBe(true)
    await type(document.body.querySelector('input[type="password"]'), 'example-pass')
    await act(async () => {
      ;(withdraw as HTMLElement).click()
      ;(withdraw as HTMLElement).click()
    })
    release()
    await settle()
    expect(calls('POST', '/api/accounts/3/links/withdraw').map((c) => c.body)).toEqual([{ current_password: 'example-pass' }])
    expect(document.body.querySelector('[data-testid="open-links"]')?.textContent).toContain(i18n.t('server.linksWithdrawn'))
    expect(calls('POST', '/api/accounts/3/block')).toHaveLength(0)
  })

  it('of a blocked account are withdrawn from its row, also while connected', async () => {
    server.handler = (method, path) => {
      if (path === '/api/accounts') return { status: 200, body: ACCOUNTS }
      if (method === 'POST' && path === '/api/accounts/4/links/withdraw') return { status: 200, body: { withdrawn: 1 } }
    }
    const { AccountsCard } = await import('./settings/ServerCards')
    await mount(<AccountsCard readOnly />)
    expect(buttons(i18n.t('server.withdrawLinksRow'))).toHaveLength(1)
    await click(buttons(i18n.t('server.withdrawLinksRow'))[0])
    await type(document.body.querySelector('input[type="password"]'), 'example-pass')
    await click(buttons(i18n.t('server.confirm.links.button')).at(-1))
    expect(calls('POST', '/api/accounts/4/links/withdraw').map((c) => c.body)).toEqual([{ current_password: 'example-pass' }])
  })
})

// --- B11: signing in as someone else while connected ----------------------------------------------------------------

describe('the sign-in page', () => {
  it('says that nexsuite may still be signed in and leads there to sign in as someone else', async () => {
    auth.me = null
    server.handler = (_m, path) => {
      if (path === '/api/setup') return { status: 200, body: { needs_setup: false, signed_in: false } }
      if (path === '/api/auth/methods') return { status: 200, body: { password: false, oidc: true, oidc_name: 'nexsuite', suite: true, suite_url: 'https://suite.example.com' } }
    }
    const { LoginPage } = await import('./AuthPages')
    const { AuthProvider } = await import('../state/auth')
    const page = await mount(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
      '/login',
      'de',
    )
    const note = page.querySelector('[data-testid="still-signed-in"]')
    expect(note?.textContent).toContain(i18n.t('suite.stillSignedIn'))
    const other = buttons(i18n.t('suite.someoneElse'))[0]
    expect(other?.getAttribute('href')).toBe('https://suite.example.com')
    expect(other?.getAttribute('target')).toBe('_blank')
    expect(other?.getAttribute('rel')).toContain('noopener')
  })

  it('on its own says nothing about nexsuite', async () => {
    auth.me = null
    server.handler = (_m, path) => {
      if (path === '/api/setup') return { status: 200, body: { needs_setup: false, signed_in: false } }
      if (path === '/api/auth/methods') return { status: 200, body: { password: true, oidc: false, oidc_name: '', suite: false, suite_url: '' } }
    }
    const { LoginPage } = await import('./AuthPages')
    const { AuthProvider } = await import('../state/auth')
    const page = await mount(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
      '/login',
    )
    expect(page.querySelector('[data-testid="still-signed-in"]')).toBeNull()
    expect(buttons(i18n.t('suite.someoneElse'))).toHaveLength(0)
  })
})

// --- B17: who stops being an operator when disconnecting ------------------------------------------------------------

describe('disconnecting', () => {
  it('names the operators through nexsuite before, and after', async () => {
    auth.me = { ...ME, suite: 'connected', suite_emergency: true } as Me
    server.handler = (method, path) => {
      if (path === '/api/suite') return { status: 200, body: { state: 'connected', url: 'https://suite.example.com', last_sync: null, problem: '', emergency_codes: 2, mail: false, operators_from_suite: ['anna', 'fritz'] } }
      if (method === 'POST' && path === '/api/suite/disconnect') return { status: 200, body: { without_password: [], blocked: [], operators_back: ['anna', 'fritz'] } }
      if (path === '/api/auth/me') return { status: 200, body: ME }
    }
    const { SuiteCard } = await import('../components/Suite')
    const page = await mount(<SuiteCard />)
    await click(buttons(i18n.t('suite.disconnect'))[0])
    expect(document.body.querySelector('[data-testid="leave-operators"]')?.textContent).toBe(i18n.t('suite.leaveOperators', { names: 'anna, fritz' }))
    await type(document.body.querySelector('input[type="password"]'), 'example-pass')
    await click(buttons(i18n.t('suite.disconnect')).at(-1))
    expect(calls('POST', '/api/suite/disconnect')).toHaveLength(1)
    expect(page.textContent).toContain(i18n.t('suite.operatorsBack', { names: 'anna, fritz' }))
  })

  it('of a connection from before the roles were kept names who stays an operator', async () => {
    auth.me = { ...ME, suite: 'connected', suite_emergency: true } as Me
    server.handler = (_m, path) => {
      if (path === '/api/suite') return { status: 200, body: { state: 'connected', url: 'https://suite.example.com', last_sync: null, problem: '', emergency_codes: 0, mail: false, operators_from_suite: [], operators_unknown: ['anna'] } }
    }
    const { SuiteCard } = await import('../components/Suite')
    await mount(<SuiteCard />)
    await click(buttons(i18n.t('suite.disconnect'))[0])
    expect(document.body.querySelector('[data-testid="leave-operators-unknown"]')?.textContent).toBe(i18n.t('suite.leaveOperatorsUnknown', { names: 'anna' }))
    expect(document.body.querySelector('[data-testid="leave-operators"]')).toBeNull()
  })
})
