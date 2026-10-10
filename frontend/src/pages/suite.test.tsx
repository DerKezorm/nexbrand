// Clients and people while connected (Prüfgang 05.10.2026, block 4), as the pages show them: the bin (B6, B14), where
// clients come from (B19), the connect assistant (B8, B9, B16, B23, B24, B25), the sign-in and invitation pages (B12,
// B26), the way to nexsuite (G3) and the mail card (G8). The server is a stub that answers by path; nothing waits for a
// clock.
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClientInfo, Me } from '../api/client'
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

async function choose(select: Element | null | undefined, value: string): Promise<void> {
  if (!select) throw new Error('nothing to choose in')
  const field = select as HTMLSelectElement
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
  await act(async () => {
    setter.call(field, value)
    field.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await settle()
}

const buttons = (text: string) => [...document.body.querySelectorAll('button, a')].filter((b) => b.textContent?.trim() === text)

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

const brands: { clients: ClientInfo[]; bin: ClientInfo[] } = { clients: [], bin: [] }
vi.mock('../state/brands', () => ({
  useBrands: () => ({
    loaded: true,
    spaces: [],
    clients: brands.clients,
    bin: brands.bin,
    space: () => undefined,
    client: () => undefined,
    refresh: async () => undefined,
    loadBin: async () => undefined,
    put: () => undefined,
  }),
}))

function client(patch: Partial<ClientInfo>): ClientInfo {
  return {
    id: 'c1', space_id: 7, name: 'Example Bakery', color: '#f472b6', managed: false, sector: 'Bakery', contact: '', links: [],
    created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z', updated_by: 'robin', deleted_at: null, favorite: false,
    opened_at: null, role: 'manage', current: null, drafts: 0, projects: 0, news: 0, face: { colors: [], logo: null },
    ...patch,
  } as ClientInfo
}

beforeEach(() => {
  server.handler = () => undefined
  server.calls = []
  server.pending = 0
  auth.me = ME
  brands.clients = []
  brands.bin = []
  stubFetch()
})

afterEach(async () => {
  await act(async () => root?.unmount())
  host?.remove()
  root = null
  host = null
  vi.unstubAllGlobals()
})

// --- B6, B14: the bin ----------------------------------------------------------------------------------------------

describe('the bin', () => {
  it('offers nothing for a client deleted in nexsuite and says where it goes back', async () => {
    auth.me = { ...ME, suite: 'connected' } as Me
    brands.bin = [client({ managed: true, deleted_at: '2026-10-04T10:00:00Z' })]
    const { ClientsPage } = await import('./ClientsPage')
    const page = await mount(<ClientsPage />, '/?bin=1')
    expect(page.textContent).toContain(i18n.t('clients.binSuite'))
    expect(buttons(i18n.t('clients.restore'))).toHaveLength(0)
    expect(buttons(i18n.t('clients.purge'))).toHaveLength(0)
  })

  it('says why bringing back failed instead of doing nothing', async () => {
    brands.bin = [client({ deleted_at: '2026-10-04T10:00:00Z' })]
    server.handler = (method, path) => {
      if (method === 'POST' && path === '/api/clients/c1/restore') return { status: 409, body: { detail: { code: 'managed_by_suite' } } }
    }
    const { ClientsPage } = await import('./ClientsPage')
    const page = await mount(<ClientsPage />, '/?bin=1')
    await click(buttons(i18n.t('clients.restore'))[0])
    expect(page.textContent).toContain(i18n.t('errors.managed_by_suite'))
  })

  it('deletes for good only with the own password', async () => {
    brands.bin = [client({ deleted_at: '2026-10-04T10:00:00Z' })]
    server.handler = (method, path, body) => {
      if (method === 'DELETE' && path === '/api/clients/c1/purge') {
        return (body as { current_password: string }).current_password === 'own password' ? { status: 204 } : { status: 401, body: { detail: { code: 'wrong_password' } } }
      }
    }
    const { ClientsPage } = await import('./ClientsPage')
    const page = await mount(<ClientsPage />, '/?bin=1')
    await click(buttons(i18n.t('clients.purge'))[0])
    expect(page.ownerDocument.body.textContent).toContain(i18n.t('clients.purgeText'))
    await type(document.body.querySelector('input[type=password]'), 'wrong')
    await click(document.body.querySelector('form button[type=submit]'))
    expect(document.body.textContent).toContain(i18n.t('errors.wrong_password'))
    await type(document.body.querySelector('input[type=password]'), 'own password')
    await click(document.body.querySelector('form button[type=submit]'))
    const sent = server.calls.filter((c) => c.method === 'DELETE')
    expect(sent.map((c) => c.body)).toEqual([{ current_password: 'wrong' }, { current_password: 'own password' }])
    expect(document.body.querySelector('input[type=password]')).toBeNull()
  })
})

// --- B19: where clients come from ----------------------------------------------------------------------------------

describe('clients from nexsuite', () => {
  it('are named so for everybody, not only on an empty list', async () => {
    auth.me = { ...ME, role: 'member', suite: 'connected', may_create_clients: false } as Me
    brands.clients = [client({ current: '1.0' })]
    const { ClientsPage } = await import('./ClientsPage')
    const page = await mount(<ClientsPage />)
    expect(page.querySelector('[data-testid="clients-from-suite"]')?.textContent).toBe(i18n.t('clients.fromSuiteAll'))
  })

  it('are offered on "New client" when they have no CI yet, without a form for nothing', async () => {
    auth.me = { ...ME, suite: 'connected', may_create_clients: false } as Me
    brands.clients = [
      client({ id: 'noci1', name: 'Example Bakery' }),
      client({ id: 'hasci', name: 'Example Works', current: '1.0' }),
      client({ id: 'reader', name: 'Example Reads', role: 'read' }),
    ]
    const { NewClientPage } = await import('./NewClientPage')
    const page = await mount(<NewClientPage />, '/new')
    const offered = [...page.querySelectorAll('[data-testid="wizard-pick"] a')]
    expect(offered.map((a) => a.getAttribute('href'))).toEqual(['/new?client=noci1'])
    expect(page.querySelector('input')).toBeNull()
    expect(page.textContent).toContain(i18n.t('wizard.fromSuite'))
  })

  it('says so when there is none to choose', async () => {
    auth.me = { ...ME, suite: 'connected', may_create_clients: false } as Me
    const { NewClientPage } = await import('./NewClientPage')
    const page = await mount(<NewClientPage />, '/new')
    expect(page.textContent).toContain(i18n.t('wizard.pickNone'))
  })
})

// --- B8, B9, B16, B23, B24, B25: the connect assistant -------------------------------------------------------------

const PROPOSAL = {
  people: [
    { id: '1', name: 'robin', display_name: '', email: 'robin@example.com' },
    { id: '60', name: 'cleo', display_name: 'Cleo Example', email: '' },
  ],
  accounts: [
    { id: 1, name: 'robin', display_name: 'Robin Example', email: 'robin@example.com', role: 'operator', suggest: '1', blocked: false, from_suite: false, gone: false },
    { id: 4, name: 'cleo', display_name: '', email: '', role: 'member', suggest: 'skip', blocked: true, from_suite: false, gone: false },
    { id: 5, name: 'anna', display_name: '', email: '', role: 'member', suggest: 'skip', blocked: true, from_suite: true, gone: true },
  ],
  clients: [],
  candidates: [],
  teams: [],
  team_candidates: [],
  chosen: null as null | Record<string, unknown>,
}

async function wizard(state: 'connecting' | '' = 'connecting'): Promise<HTMLElement> {
  const { SuiteCard } = await import('../components/Suite')
  const page = await mount(<SuiteCard />)
  void state
  await click(buttons(i18n.t(state === 'connecting' ? 'suite.resume' : 'suite.connect'))[0])
  return page
}

describe('the connect assistant', () => {
  it('marks blocked and deleted accounts and names what changes on a match', async () => {
    server.handler = (method, path) => {
      if (path === '/api/suite') return { status: 200, body: { state: 'connecting', url: 'https://suite.example.com' } }
      if (path === '/api/suite/proposal') return { status: 200, body: PROPOSAL }
      if (method === 'PUT' && path === '/api/suite/choices') return { status: 204 }
    }
    await wizard()
    // robin's person has no display name there: connecting gives it the one from here (B16), so nothing changes.
    const robin = document.body.querySelector('[data-testid="suite-row-robin"]')
    expect(robin?.textContent).not.toContain(i18n.t('suite.changesName', { name: 'robin' }))
    const cleo = document.body.querySelector('[data-testid="suite-row-cleo"]')!
    const badges = (row: Element) => [...row.querySelectorAll('span')].map((span) => span.textContent)
    expect(badges(cleo)).toContain(i18n.t('suite.rowBlocked'))
    expect(badges(document.body.querySelector('[data-testid="suite-row-robin"]')!)).not.toContain(i18n.t('suite.rowBlocked'))
    expect(cleo.textContent).not.toContain(i18n.t('suite.rowBlockedTaken'))
    await choose(cleo.querySelector('select'), '60')
    expect(cleo.textContent).toContain(i18n.t('suite.rowBlockedTaken'))
    expect(cleo.textContent).toContain(i18n.t('suite.changesName', { name: 'Cleo Example' }))
    const anna = document.body.querySelector('[data-testid="suite-row-anna"]')!
    expect(anna.textContent).toContain(i18n.t('suite.rowGone'))
    expect(anna.textContent).toContain(i18n.t('suite.rowFromSuite'))
    // Every choice is kept on the server as it is made (B23).
    const kept = server.calls.filter((c) => c.method === 'PUT' && c.path === '/api/suite/choices').at(-1)
    expect(kept?.body).toEqual({ accounts: { 1: '1', 4: '60', 5: 'skip' }, clients: {}, teams: {}, step: 2 })
  })

  it('resumes with the choices and the step from before', async () => {
    server.handler = (method, path) => {
      if (path === '/api/suite') return { status: 200, body: { state: 'connecting', url: 'https://suite.example.com' } }
      if (path === '/api/suite/proposal') return { status: 200, body: { ...PROPOSAL, chosen: { accounts: { 4: 'new', 5: '99' }, clients: {}, teams: {}, step: 3 } } }
      if (method === 'PUT' && path === '/api/suite/choices') return { status: 204 }
    }
    await wizard()
    expect(document.body.textContent).toContain(i18n.t('suite.finish'))
    await click(buttons(i18n.t('suite.back'))[0])
    const cleo = document.body.querySelector('[data-testid="suite-row-cleo"] select') as HTMLSelectElement
    const anna = document.body.querySelector('[data-testid="suite-row-anna"] select') as HTMLSelectElement
    expect(cleo.value).toBe('new')
    expect(anna.value).toBe('skip') // a person nexsuite no longer has is not taken over
  })

  it('connects once however often it is clicked, saying it is at work', async () => {
    let release: () => void = () => undefined
    server.handler = (method, path) => {
      if (path === '/api/suite') return { status: 200, body: { state: 'connecting', url: 'https://suite.example.com' } }
      if (path === '/api/suite/proposal') return { status: 200, body: { ...PROPOSAL, chosen: { accounts: {}, clients: {}, teams: {}, step: 3 } } }
      if (method === 'PUT' && path === '/api/suite/choices') return { status: 204 }
      if (method === 'POST' && path === '/api/suite/finish') return new Promise<Answer>((resolve) => (release = () => resolve({ status: 200, body: { new_people: [] } })))
    }
    await wizard()
    const go = buttons(i18n.t('suite.finish'))[0] as HTMLButtonElement
    await act(async () => {
      go.click()
      go.click()
    })
    await act(async () => {
      for (let i = 0; i < 10; i++) await Promise.resolve()
    })
    expect(document.body.querySelector('[data-testid="suite-busy"]')?.textContent).toBe(i18n.t('suite.finishing'))
    await act(async () => release())
    await settle()
    expect(server.calls.filter((c) => c.path === '/api/suite/finish')).toHaveLength(1)
    expect(document.body.textContent).toContain(i18n.t('suite.done1'))
  })

  it('loads the lists anew when a chosen person is gone, back on the accounts', async () => {
    let gone = false
    server.handler = (method, path) => {
      if (path === '/api/suite') return { status: 200, body: { state: 'connecting', url: 'https://suite.example.com' } }
      if (path === '/api/suite/proposal') return { status: 200, body: gone ? { ...PROPOSAL, people: PROPOSAL.people.slice(0, 1) } : { ...PROPOSAL, chosen: { accounts: { 4: '60' }, clients: {}, teams: {}, step: 3 } } }
      if (method === 'PUT' && path === '/api/suite/choices') return { status: 204 }
      if (method === 'POST' && path === '/api/suite/finish') {
        gone = true
        return { status: 409, body: { detail: { code: 'person_unknown' } } }
      }
    }
    await wizard()
    await click(buttons(i18n.t('suite.finish'))[0])
    expect(document.body.textContent).toContain(i18n.t('errors.person_unknown'))
    const cleo = document.body.querySelector('[data-testid="suite-row-cleo"] select') as HTMLSelectElement
    expect(cleo.value).toBe('skip')
  })

  it('says when the address is not nexsuite', async () => {
    server.handler = (method, path) => {
      if (path === '/api/suite') return { status: 200, body: { state: '', url: '' } }
      if (method === 'POST' && path === '/api/suite/start') return { status: 409, body: { detail: { code: 'not_suite' } } }
    }
    await wizard('')
    await type(document.body.querySelector('input[placeholder="https://suite.example.com"]'), 'https://tasks.example.com')
    await type(document.body.querySelector('input[placeholder="ABCD-EFGH-JKLM"]'), 'GOOD-CODE-1234')
    await click(buttons(i18n.t('suite.next'))[0])
    expect(document.body.textContent).toContain(i18n.t('errors.not_suite'))
  })
})

// --- A connection that fails at its last step, or whose answer got lost (from nexcanvas) -------------------------

const CONNECTING = { status: 200, body: { state: 'connecting', url: 'https://suite.example.com' } }

describe('the connect assistant after a failed last step', () => {
  it('names no change of display name for a person without one: connecting gives it the one from here', async () => {
    server.handler = (method, path) => {
      if (path === '/api/suite') return CONNECTING
      if (path === '/api/suite/proposal') return { status: 200, body: PROPOSAL }
      if (method === 'PUT' && path === '/api/suite/choices') return { status: 204 }
    }
    await wizard()
    // robin's person has no display name in nexsuite: finishing sends "Robin Example" along (B16), nothing changes.
    const robin = document.body.querySelector('[data-testid="suite-row-robin"]')!
    expect(robin.textContent).not.toContain('Display name becomes')
    // A person with a display name of its own still names the change.
    const cleo = document.body.querySelector('[data-testid="suite-row-cleo"]')!
    await choose(cleo.querySelector('select'), '60')
    expect(cleo.textContent).toContain('Display name becomes “Cleo Example”')
  })

  it('says what stays in nexsuite on giving up, only once something was created there', async () => {
    let made = 0
    server.handler = (method, path) => {
      if (path === '/api/suite') return CONNECTING
      if (path === '/api/suite/proposal') return { status: 200, body: { ...PROPOSAL, made } }
      if (method === 'PUT' && path === '/api/suite/choices') return { status: 204 }
      if (method === 'POST' && path === '/api/suite/finish') {
        made = 1
        return { status: 502, body: { detail: { code: 'suite_unreachable' } } }
      }
    }
    await wizard()
    expect(document.body.querySelector('[data-testid="suite-made"]')).toBeNull()
    await click(buttons(i18n.t('suite.next'))[0])
    await click(buttons(i18n.t('suite.finish'))[0])
    await click(buttons(i18n.t('suite.back'))[0])
    expect(document.body.querySelector('[data-testid="suite-made"]')?.textContent).toBe(
      'What is created in nexsuite already (people, teams, clients) stays there if you cancel. New people with an address have been sent the mail to set their password. Connecting again suggests them once more.',
    )
  })

  it('locks the choices once the connection went out to nexsuite, and says so', async () => {
    let sent = false
    server.handler = (method, path) => {
      if (path === '/api/suite') return CONNECTING
      if (path === '/api/suite/proposal') return { status: 200, body: { ...PROPOSAL, made: sent ? 1 : 0, sent } }
      if (method === 'PUT' && path === '/api/suite/choices') return { status: 204 }
      if (method === 'POST' && path === '/api/suite/finish') {
        sent = true
        return { status: 502, body: { detail: { code: 'suite_unreachable' } } }
      }
    }
    await wizard()
    expect(document.body.querySelector('[data-testid="suite-sent"]')).toBeNull()
    expect((document.body.querySelector('[data-testid="suite-row-cleo"] select') as HTMLSelectElement).disabled).toBe(false)
    await click(buttons(i18n.t('suite.next'))[0])
    await click(buttons(i18n.t('suite.finish'))[0])
    const sentence = 'The connection has been sent to nexsuite already. The choices from then apply; for other choices, cancel and connect again.'
    expect(document.body.querySelector('[data-testid="suite-sent"]')?.textContent).toBe(sentence)
    await click(buttons(i18n.t('suite.back'))[0])
    expect(document.body.querySelector('[data-testid="suite-sent"]')?.textContent).toBe(sentence)
    const selects = [...document.body.querySelectorAll('li select')] as HTMLSelectElement[]
    expect(selects.length).toBeGreaterThan(0)
    expect(selects.every((select) => select.disabled)).toBe(true)
  })

  it('shows after a reload exactly the choices that went out, locked, though nexsuite offers no client any more', async () => {
    server.handler = (method, path) => {
      if (path === '/api/suite') return CONNECTING
      if (path === '/api/suite/proposal')
        return {
          status: 200,
          body: {
            ...PROPOSAL,
            clients: [{ id: 'c1', name: 'Example Bakery', color: '#f472b6', suggest: 'new' }],
            candidates: [{ id: '10', name: 'Ideen' }],
            sent: true,
            made: 1,
            chosen: { accounts: { 1: '1', 4: '60', 5: 'skip' }, clients: { c1: '10' }, teams: {}, step: 3 },
          },
        }
      if (method === 'PUT' && path === '/api/suite/choices') return { status: 204 }
    }
    await wizard()
    const bakery = document.body.querySelector('li select') as HTMLSelectElement
    expect(bakery.value).toBe('10')
    expect(bakery.selectedOptions[0].textContent).toContain('Ideen')
    expect(bakery.disabled).toBe(true)
    expect(document.body.querySelector('[data-testid="suite-sent"]')).not.toBeNull()
    await click(buttons(i18n.t('suite.back'))[0])
    expect((document.body.querySelector('[data-testid="suite-row-cleo"] select') as HTMLSelectElement).value).toBe('60')
    expect((document.body.querySelector('[data-testid="suite-row-anna"] select') as HTMLSelectElement).value).toBe('skip')
    expect((document.body.querySelector('[data-testid="suite-row-cleo"] select') as HTMLSelectElement).disabled).toBe(true)
    expect(server.calls.filter((c) => c.method === 'PUT' && c.path === '/api/suite/choices')).toHaveLength(0)
  })

  it('says after giving up when nexsuite may still list nexbrand, and only then', async () => {
    let kept = true
    server.handler = (method, path) => {
      if (path === '/api/suite') return CONNECTING
      if (path === '/api/suite/proposal') return { status: 200, body: PROPOSAL }
      if (method === 'PUT' && path === '/api/suite/choices') return { status: 204 }
      if (method === 'POST' && path === '/api/suite/abort') return kept ? { status: 200, body: { kept_in_suite: true } } : { status: 204 }
      // The card loads the state and the own account anew once the assistant is closed.
      if (path === '/api/auth/me') return { status: 200, body: ME }
    }
    await wizard()
    await click(buttons(i18n.t('suite.abort'))[0])
    expect(document.body.querySelector('[data-testid="suite-kept"]')?.textContent).toBe(
      'nexsuite could not be reached. nexbrand may still be listed there under Apps; disconnect it there before you connect again.',
    )
    await act(async () => root?.unmount())
    host?.remove()
    kept = false
    await wizard()
    await click(buttons(i18n.t('suite.abort'))[0])
    expect(document.body.querySelector('[data-testid="suite-kept"]')).toBeNull()
  })
})

// --- B12, B26: sign-in and invitation ------------------------------------------------------------------------------

describe('the pages before signing in', () => {
  it('name a new password in nexsuite among the reasons a session ended', async () => {
    auth.me = null
    server.handler = (_m, path) => {
      if (path === '/api/setup') return { status: 200, body: { needs_setup: false, signed_in: false } }
      if (path === '/api/auth/methods') return { status: 200, body: { password: false, providers: [{ slug: 'oidc', label: 'nexsuite' }], suite: true } }
    }
    const { LoginPage } = await import('./AuthPages')
    const { AuthProvider } = await import('../state/auth')
    const page = await mount(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
      '/login?next=%2Fc%2Fabc&ended=1',
    )
    expect(page.textContent).toContain(i18n.t('auth.login.endedSuite'))
    expect(page.querySelector('a[href^="/api/oidc/oidc/start"]')?.getAttribute('href')).toBe('/api/oidc/oidc/start?next=%2Fc%2Fabc')
  })

  it('say at once that an invitation from before the connection does not hold', async () => {
    auth.me = null
    server.handler = (_m, path) => {
      if (path.startsWith('/api/invite/')) return { status: 404, body: { detail: { code: 'invite_suite' } } }
      if (path === '/api/auth/methods') return { status: 200, body: { password: false, providers: [{ slug: 'oidc', label: 'nexsuite' }], suite: true } }
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
    expect(page.textContent).toContain(i18n.t('errors.invite_suite'))
    expect(page.querySelector('a[href="/login"]')).not.toBeNull()
    expect(page.textContent).not.toContain('Example Bakery')
  })

  it('name who invites and the rule for the name', async () => {
    auth.me = null
    server.handler = (_m, path) => {
      if (path.startsWith('/api/invite/')) return { status: 200, body: { space: 'Example Bakery', role: 'write', min_password: 12, signed_in_as: null, by: 'Robin Example' } }
      if (path === '/api/auth/methods') return { status: 200, body: { password: true, providers: [] } }
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
    expect(page.textContent).toContain(i18n.t('auth.invite.intoSpaceBy', { by: 'Robin Example', space: 'Example Bakery', role: i18n.t('roles.write') }))
    expect(page.textContent).toContain(i18n.t('auth.invite.nameHint'))
  })
})

// --- G3, G8 --------------------------------------------------------------------------------------------------------

describe('while connected', () => {
  it('the own account leads to nexsuite for password and second factor', async () => {
    auth.me = { ...ME, role: 'member', sign_in: 'oidc', suite: 'connected', suite_url: 'https://suite.example.com' } as Me
    server.handler = (_m, path) => {
      if (path === '/api/auth/methods') return { status: 200, body: { password: false, providers: [{ slug: 'oidc', label: 'nexsuite' }], suite: true } }
    }
    const { AccountPage } = await import('./AccountPage')
    const page = await mount(<AccountPage />, '/account?tab=security')
    expect(page.textContent).toContain(i18n.t('suite.managedPassword'))
    expect(page.querySelector('[data-testid="suite-link"]')?.getAttribute('href')).toBe('https://suite.example.com')
  })

  it('the second factor names the emergency codes from nexsuite only while connected', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/auth/methods') return { status: 200, body: { password: true, providers: [] } }
    }
    const { AccountPage } = await import('./AccountPage')
    const alone = await mount(<AccountPage />, '/account?tab=security')
    const lead = (page: HTMLElement) => page.querySelector('[data-testid="second-factor-lead"]')?.textContent
    expect(lead(alone)).toBe(i18n.t('twofactor.lead'))
    expect(lead(alone)).not.toContain('nexsuite')
    await act(async () => root?.unmount())
    host?.remove()
    // The emergency account signs in with its password while connected: there are emergency codes to tell apart.
    auth.me = { ...ME, suite: 'connected', suite_emergency: true } as Me
    const connected = await mount(<AccountPage />, '/account?tab=security')
    expect(lead(connected)).toBe(`${i18n.t('twofactor.lead')} ${i18n.t('twofactor.leadSuite')}`)
    expect(lead(connected)).toContain('emergency codes from nexsuite')
  })

  it('the mail card shows what came from nexsuite, in words of the page', async () => {
    auth.me = { ...ME, suite: 'connected', suite_mail: true } as Me
    const { MailCard } = await import('./settings/ServerCards')
    const settings = { smtp_host: 'smtp.example.com', smtp_port: 25, smtp_security: 'none', smtp_user: '', smtp_from: 'brand@example.com' }
    const page = await mount(<MailCard server={{ settings, busy: false, problem: null, done: null, save: async () => undefined } as never} managed />, '/', 'de')
    const shown = [...page.querySelectorAll('[data-testid="mail-from-suite"] dd')].map((dd) => dd.textContent)
    expect(shown).toEqual(['smtp.example.com:25', i18n.t('server.none'), i18n.t('suite.notSet'), 'brand@example.com'])
    expect(shown).not.toContain('none')
    expect(page.querySelector('input')).toBeNull()
  })

  it('the mail card says once that nexsuite has no mail server', async () => {
    auth.me = { ...ME, suite: 'connected', suite_mail: true } as Me
    const { MailCard } = await import('./settings/ServerCards')
    const settings = { smtp_host: '', smtp_port: 587, smtp_security: 'starttls', smtp_user: '', smtp_from: '' }
    const page = await mount(<MailCard server={{ settings, busy: false, problem: null, done: null, save: async () => undefined } as never} managed />)
    const text = page.textContent ?? ''
    expect(text.split(i18n.t('suite.mailNone')).length - 1).toBe(1)
    expect(text).not.toContain(i18n.t('suite.managedMail'))
    expect(page.querySelector('[data-testid="mail-from-suite"]')).toBeNull()
  })

  it('every client and its access is only looked at where nexsuite keeps the rights', async () => {
    auth.me = { ...ME, suite: 'connected' } as Me
    server.handler = (_m, path) => {
      if (path === '/api/admin/spaces') return { status: 200, body: [{ id: 7, name: 'Example Bakery', members: 1, managers: ['robin'], role: 'manage', managed: true }] }
    }
    const { AllSpacesCard } = await import('./settings/ServerCards')
    const page = await mount(<AllSpacesCard server={{ settings: null } as never} />)
    expect(buttons(i18n.t('server.allSpaces.view'))).toHaveLength(1)
    expect(page.textContent).toContain(i18n.t('server.allSpaces.textSuite'))
  })
})
