// Handling and looks after the check of 05.10.2026 (block 6), as the pages show them: the sign-in pages wait for the
// ways in, the bin names its clients and asks with the family's dialog (F6), a protected page says so in words (F14),
// collecting says up front that it is off and does not point the wrong way (F19), the emergency page alone is the
// usual sign-in (F20), the assistant has one way on and says why it waits (F25), the two "Edit" say what they edit
// (F28), a new person learns whom to ask (G5), the account list is readable and names its buttons (G6), and the family
// is the same in words (G11). The server is a stub that answers by path; nothing waits for a clock.
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClientInfo, Me, ReviewInfo, ShareInfo } from '../api/client'
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

/** Until every answer is in. `held`: answers kept back on purpose do not count. */
async function settle(held = 0): Promise<void> {
  for (let quiet = 0, round = 0; quiet < 3; round++) {
    if (round > 200) throw new Error(`settle: ${server.pending} answer(s) still out`)
    await act(async () => {
      for (let i = 0; i < 5; i++) await Promise.resolve()
    })
    quiet = server.pending <= held ? quiet + 1 : 0
  }
}

async function mount(ui: ReactNode, path = '/', language = 'en', held = 0): Promise<HTMLElement> {
  await i18n.changeLanguage(language)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => root!.render(<MemoryRouter initialEntries={[path]}>{ui}</MemoryRouter>))
  await settle(held)
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
const named = (name: string) => document.body.querySelector(`[aria-label="${name}"]`)
const dialog = () => document.body.querySelector('[role="dialog"]')
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
  may_create_clients: true,
  shares_allowed: true,
  collect_allowed: true,
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

let confirmed: ReturnType<typeof vi.fn>

beforeEach(() => {
  server.handler = () => undefined
  server.calls = []
  server.pending = 0
  auth.me = ME
  brands.clients = []
  brands.bin = []
  stubFetch()
  // The browser's own dialog is not the family's: nothing here may call it.
  confirmed = vi.fn(() => true)
  vi.stubGlobal('confirm', confirmed)
})

afterEach(async () => {
  await act(async () => root?.unmount())
  // A test that switched to German leaves English behind for the next one.
  await i18n.changeLanguage('en')
  host?.remove()
  root = null
  host = null
  vi.unstubAllGlobals()
})

// --- The sign-in pages wait for the ways in ---------------------------------------------------------------------

describe('the pages before signing in', () => {
  async function signIn(path: string, methods: Record<string, unknown>) {
    auth.me = null
    let release: () => void = () => undefined
    server.handler = (_m, p) => {
      if (p === '/api/setup') return { status: 200, body: { needs_setup: false, signed_in: false } }
      if (p === '/api/auth/methods') return new Promise<Answer>((done) => (release = () => done({ status: 200, body: methods })))
    }
    const { LoginPage } = await import('./AuthPages')
    const { AuthProvider } = await import('../state/auth')
    const page = await mount(
      <AuthProvider>
        <Routes>
          <Route path="login" element={<LoginPage />} />
          <Route path="notzugang" element={<LoginPage emergency />} />
        </Routes>
      </AuthProvider>,
      path,
      'en',
      1,
    )
    return { page, release: async () => (release(), await settle()) }
  }

  it('show no password form while connected, not even before the ways in are known', async () => {
    const { page, release } = await signIn('/login', { password: false, providers: [{ slug: 'oidc', label: 'nexsuite' }], suite: true, suite_url: 'https://suite.example.com' })
    expect(page.querySelector('input[type=password]')).toBeNull()
    expect(page.querySelector('h1')).toBeNull()
    await release()
    expect(page.querySelector('input[type=password]')).toBeNull()
    expect(page.querySelector('a[href^="/api/oidc/oidc/start"]')?.textContent).toBe(i18n.t('suite.loginButton'))
  })

  it('show the emergency page as such from the start while connected, and the usual sign-in alone (F20)', async () => {
    const connected = await signIn('/notzugang', { password: false, providers: [{ slug: 'oidc', label: 'nexsuite' }], suite: true })
    expect(connected.page.querySelector('h1')).toBeNull()
    await connected.release()
    expect(connected.page.querySelector('h1')?.textContent).toBe(i18n.t('suite.emergencyTitle'))
    await act(async () => root?.unmount())
    host?.remove()
    const alone = await signIn('/notzugang', { password: true, providers: [] })
    await alone.release()
    expect(alone.page.querySelector('h1')?.textContent).toBe(i18n.t('auth.login.title'))
    expect(alone.page.textContent).not.toContain('nexsuite')
    expect(alone.page.querySelector('input[type=password]')).not.toBeNull()
  })

  it('show an invitation with the provider only without a password form flashing up first', async () => {
    auth.me = null
    let release: () => void = () => undefined
    server.handler = (_m, p) => {
      if (p === '/api/setup') return { status: 200, body: { needs_setup: false, signed_in: false } }
      if (p.startsWith('/api/invite/')) return { status: 200, body: { space: null, role: null, min_password: 12, signed_in_as: null, by: 'Robin Example' } }
      if (p === '/api/auth/methods') return new Promise<Answer>((done) => (release = () => done({ status: 200, body: { password: false, providers: [{ slug: 'oidc', label: 'authentik' }] } })))
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
      'en',
      1,
    )
    expect(page.querySelector('input[type=password]')).toBeNull()
    release()
    await settle()
    expect(page.querySelector('input[type=password]')).toBeNull()
    // One button per provider, "Continue with …" (blueprint 04): it takes the invitation along to the provider.
    const button = [...page.querySelectorAll('[data-testid="provider-buttons"] button')]
    expect(button.map((b) => b.textContent)).toEqual([i18n.t('oidc.invite.button', { name: 'authentik' })])
  })
})

// --- F6: the bin, and asking with the family's dialog -------------------------------------------------------------

describe('the bin', () => {
  it('names each client on a line of its own and in its buttons, and deletes for good only after the dialog', async () => {
    brands.bin = [client({ id: 'c1', name: 'Example Bakery of the Very Long Name in Town', deleted_at: '2026-10-04T10:00:00Z' })]
    server.handler = (method, path) => {
      if (method === 'DELETE' && path === '/api/clients/c1/purge') return { status: 204 }
    }
    const { ClientsPage } = await import('./ClientsPage')
    const page = await mount(<ClientsPage />, '/?bin=1')
    const card = page.querySelector('[data-testid="bin-card"]')!
    const heading = card.querySelector('h2')
    expect(heading?.textContent).toBe('Example Bakery of the Very Long Name in Town')
    // Not in the row of buttons, where it shrank to nothing.
    expect(heading?.querySelector('button')).toBeNull()
    expect(heading?.className).not.toContain('truncate')
    const name = 'Example Bakery of the Very Long Name in Town'
    expect(named(i18n.t('clients.restoreThis', { name }))).not.toBeNull()
    await click(named(i18n.t('clients.purgeThis', { name })))
    expect(dialog()?.getAttribute('aria-label')).toBe(i18n.t('clients.purgeTitle', { name }))
    expect(calls('DELETE', '/api/clients/c1/purge')).toHaveLength(0)
    expect(confirmed).not.toHaveBeenCalled()
  })
})

const DATA = { colors: [{ name: 'Ink', hex: '#123456', role: 'primary' }], fonts: [], logos: [], scale: [], rules: [], samples: [] }

describe('withdrawing a review and ending a public page', () => {
  it('ask with the family dialog and act only on its button', async () => {
    const review = {
      id: 3, link: 'https://brand.example.com/r/abc', mine: true, version_id: 'v1', label: '2.0', sender: '', message: '',
      status: 'open', chosen: '', chosen_by: '', chosen_at: null, variants: [{ id: 'a', label: 'A', data: DATA }], comments: [], news: 0,
      seen_at: null, created_at: '2026-10-04T10:00:00Z',
    } as unknown as ReviewInfo
    server.handler = (method, path) => {
      if (path === '/api/clients/c1/reviews' && method === 'GET') return { status: 200, body: [review] }
      if (method === 'DELETE' && path === '/api/clients/c1/reviews/3') return { status: 204 }
    }
    const { ReviewsPanel } = await import('../components/brand/Reviews')
    await mount(<ReviewsPanel client="c1" versions={[]} role="manage" onChange={() => undefined} />)
    await click(buttons(i18n.t('reviews.withdraw'))[0])
    expect(confirmed).not.toHaveBeenCalled()
    expect(dialog()?.getAttribute('aria-label')).toBe(i18n.t('reviews.withdrawTitle', { label: '2.0' }))
    expect(calls('DELETE', '/api/clients/c1/reviews/3')).toHaveLength(0)
    await click([...dialog()!.querySelectorAll('button')].find((b) => b.textContent === i18n.t('reviews.withdraw')))
    expect(calls('DELETE', '/api/clients/c1/reviews/3')).toHaveLength(1)
  })

  it('a page with a password says so in words, and ending it asks first (F14)', async () => {
    const share = { id: 9, project_id: null, label: 'Press kit', link: 'https://brand.example.com/s/abc', mine: true, version_id: null, version_label: null, views: 2, created_at: '2026-10-04T10:00:00Z', expires_at: null, password: true } as ShareInfo
    server.handler = (method, path) => {
      if (path === '/api/clients/c1/shares' && method === 'GET') return { status: 200, body: [share] }
      if (method === 'DELETE' && path === '/api/shares/9') return { status: 204 }
    }
    const { SharesPanel } = await import('../components/brand/SharesPanel')
    const page = await mount(<SharesPanel client="c1" versions={[{ id: 'v1', status: 'published' } as never]} role="manage" />)
    const guarded = page.querySelector('[data-testid="share-guarded"]')
    expect(guarded?.textContent?.trim()).toBe(i18n.t('shares.guarded'))
    expect(guarded?.getAttribute('title')).toBe(i18n.t('shares.guardedHint'))
    await click(named(i18n.t('shares.removeThis', { name: 'Press kit' })))
    expect(dialog()?.getAttribute('aria-label')).toBe(i18n.t('shares.removeTitle', { name: 'Press kit' }))
    expect(calls('DELETE', '/api/shares/9')).toHaveLength(0)
    await click([...dialog()!.querySelectorAll('button')].find((b) => b.textContent === i18n.t('shares.remove')))
    expect(calls('DELETE', '/api/shares/9')).toHaveLength(1)
  })
})

// --- G5: a new person without a client ------------------------------------------------------------------------------

describe('a person without a client', () => {
  it('reads one wording and whom to ask, alone and connected', async () => {
    auth.me = { ...ME, role: 'member', may_create_clients: false } as Me
    const { ClientsPage } = await import('./ClientsPage')
    const page = await mount(<ClientsPage />)
    expect(page.textContent).toContain(i18n.t('clients.empty'))
    expect(page.querySelector('[data-testid="clients-ask"]')?.textContent).toBe(i18n.t('clients.ask'))
    await act(async () => root?.unmount())
    host?.remove()
    auth.me = { ...ME, role: 'member', may_create_clients: false, suite: 'connected' } as Me
    const joined = await mount(<ClientsPage />)
    expect(joined.querySelector('[data-testid="clients-ask"]')?.textContent).toBe(i18n.t('clients.askSuite'))
  })

  it('who may make one gets the button, not the sentence', async () => {
    const { ClientsPage } = await import('./ClientsPage')
    const page = await mount(<ClientsPage />)
    expect(page.querySelector('[data-testid="clients-ask"]')).toBeNull()
    expect(buttons(i18n.t('client.new')).length).toBeGreaterThan(0)
  })
})

// --- G6: the list of accounts --------------------------------------------------------------------------------------

const ACCOUNTS = [
  { id: 1, name: 'robin', display_name: '', role: 'operator', sign_in: 'password', spaces: 1, locked: false, blocked: false, open_links: 0 },
  { id: 3, name: 'wim', display_name: 'Wim Example', role: 'member', sign_in: 'password', spaces: 1, locked: false, blocked: false, open_links: 0 },
  { id: 4, name: 'op2', display_name: 'Oda Example', role: 'operator', sign_in: 'password', spaces: 0, locked: false, blocked: false, open_links: 0 },
]

describe('the list of accounts', () => {
  it('says an operator sees every client, shows each line whole and names the account in every button', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/accounts') return { status: 200, body: ACCOUNTS }
      if (path === '/api/invites') return { status: 200, body: [] }
    }
    const { AccountsCard } = await import('./settings/ServerCards')
    const page = await mount(<AccountsCard />)
    const lines = [...page.querySelectorAll('[data-testid="account-status"]')]
    expect(lines.map((line) => line.className.includes('truncate'))).toEqual([false, false, false])
    expect(lines[0].textContent).toContain(i18n.t('server.allClients'))
    expect(lines[2].textContent).toContain(i18n.t('server.allClients'))
    expect(lines[1].textContent).toContain(i18n.t('server.inSpaces', { count: 1 }))
    // The buttons below the name, not beside the line they cut.
    for (const row of page.querySelectorAll('[data-testid="account-actions"]')) expect(row.className).toContain('w-full')
    for (const action of ['server.deleteAccount', 'server.block', 'server.signOutEverywhere', 'server.newPassword']) {
      expect(named(i18n.t('server.forAccount', { action: i18n.t(action), name: 'Wim Example' }))).not.toBeNull()
    }
    const unnamed = [...page.querySelectorAll('[data-testid="account-actions"] button')].filter((b) => !b.getAttribute('aria-label')?.includes('Example'))
    expect(unnamed).toHaveLength(0)
  })
})

// --- F19: collecting --------------------------------------------------------------------------------------------------

describe('collecting', () => {
  it('says before any click that the operator has switched it off, and does not try', async () => {
    auth.me = { ...ME, collect_allowed: false } as Me
    const { CollectPage } = await import('./CollectPage')
    const page = await mount(<CollectPage />, '/collect')
    expect(page.querySelector('[data-testid="collect-off"]')?.textContent).toContain(i18n.t('collect.offNow'))
    await type(page.querySelector(`input[aria-label="${i18n.t('collect.kinds.website')}"]`), 'https://www.example.com')
    await settle()
    const run = buttons(i18n.t('collect.run'))[0] as HTMLButtonElement
    expect(run.disabled).toBe(true)
    expect(calls('POST', '/api/collect')).toHaveLength(0)
  })

  it('does not suggest JavaScript when no source could be read at all', async () => {
    let notes = [{ source: 'http://10.0.0.1/', problem: 'not_public' }]
    server.handler = (method, path, body) => {
      if (method === 'POST' && path === '/api/collect') {
        const sources = (body as { sources: { value: string }[] }).sources
        expect(sources.map((s) => s.value)).toEqual(['http://10.0.0.1/'])
        return { status: 200, body: { colors: [], fonts: [], logos: [], notes, ai: false, system_font: '' } }
      }
    }
    const { CollectPage } = await import('./CollectPage')
    const page = await mount(<CollectPage />, '/collect')
    await type(page.querySelector(`input[aria-label="${i18n.t('collect.kinds.website')}"]`), 'http://10.0.0.1/')
    await settle()
    await click(buttons(i18n.t('collect.run'))[0])
    expect(page.querySelector('[data-testid="collect-notes"]')?.textContent).toContain(i18n.t('collect.problems.not_public'))
    expect(page.textContent).not.toContain(i18n.t('collect.nothing'))
    // Read, and nothing in it: then the hint is the right one.
    notes = []
    await click(buttons(i18n.t('collect.run'))[0])
    expect(page.textContent).toContain(i18n.t('collect.nothing'))
  })
})

// --- F25: the assistant ------------------------------------------------------------------------------------------------

describe('the assistant for a new client', () => {
  it('says why "Next" waits and has one way on from the start step', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/clients/name-check') return { status: 200, body: { free: true, code: null } }
    }
    const { NewClientPage } = await import('./NewClientPage')
    const page = await mount(<NewClientPage />, '/new')
    const next = buttons(i18n.t('wizard.next'))[0] as HTMLButtonElement
    expect(next.disabled).toBe(true)
    const waits = page.querySelector('[data-testid="wizard-waits"]')
    expect(waits?.textContent).toBe(i18n.t('wizard.needName'))
    expect(next.getAttribute('aria-describedby')).toBe(waits?.id)
    await type(page.querySelector(`input[placeholder="${i18n.t('wizard.nameHint')}"]`), 'Example Works')
    await settle()
    expect(page.querySelector('[data-testid="wizard-waits"]')).toBeNull()
    await click(buttons(i18n.t('wizard.next'))[0])
    // The start: only the buttons of the chosen start lead on.
    expect(page.querySelector('[aria-current="step"]')?.textContent).toContain(i18n.t('wizard.step.start'))
    expect(buttons(i18n.t('wizard.next'))).toHaveLength(0)
    expect(buttons(i18n.t('wizard.keepColors'))).toHaveLength(0)
  })
  async function directionsFrom(ai: boolean): Promise<HTMLElement> {
    server.handler = (_m, path) => {
      if (path === '/api/clients/name-check') return { status: 200, body: { free: true, code: null } }
      if (path === '/api/ai') return { status: 200, body: { ready: ai } }
      if (path === '/api/ai/directions')
        return { status: 200, body: { directions: [{ label: 'Oven', why: 'Warm like bread', hue: 20, accent_hue: 200, saturation: 60, mood: 'warm', head: 'fraunces', body: 'inter' }] } }
    }
    const { NewClientPage } = await import('./NewClientPage')
    const page = await mount(<NewClientPage />, '/new')
    await type(page.querySelector(`input[placeholder="${i18n.t('wizard.nameHint')}"]`), 'Example Bakery')
    const brief = page.querySelector('textarea') as HTMLTextAreaElement
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(brief, 'warm craft bakery')
      brief.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await settle()
    await click(buttons(i18n.t('wizard.next'))[0])
    if (ai) await click(buttons(i18n.t('wizard.proposeAi'))[0])
    else {
      // Without AI the rules answer after a short pause; the clock is moved by hand, nothing waits for it.
      vi.useFakeTimers({ toFake: ['setTimeout'] })
      try {
        await click(buttons(i18n.t('wizard.propose'))[0])
        await act(async () => void vi.advanceTimersByTime(300))
      } finally {
        vi.useRealTimers()
      }
      await settle()
    }
    return page
  }

  it('says that the directions came from the account\'s AI when they did', async () => {
    const page = await directionsFrom(true)
    expect(page.textContent).toContain(i18n.t('wizard.proposeNoteAi'))
    expect(page.textContent).not.toContain(i18n.t('wizard.proposeNote'))
  })

  it('says that the directions came from the keywords when there is no AI', async () => {
    const page = await directionsFrom(false)
    expect(page.textContent).toContain(i18n.t('wizard.proposeNote'))
    expect(page.textContent).not.toContain(i18n.t('wizard.proposeNoteAi'))
  })

  it('keeps a start colour as entered and only offers the one that reaches on the light ground (decided 06.10.2026)', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/clients/name-check') return { status: 200, body: { free: true, code: null } }
    }
    const { NewClientPage } = await import('./NewClientPage')
    const page = await mount(<NewClientPage />, '/new')
    await type(page.querySelector(`input[placeholder="${i18n.t('wizard.nameHint')}"]`), 'Example Works')
    await settle()
    await click(buttons(i18n.t('wizard.next'))[0])
    const field = () => page.querySelector(`input:not([type="color"])[aria-label="${i18n.t('wizard.startColor')}"]`) as HTMLInputElement
    const note = () => page.querySelector('[role="status"]')
    // The default reads on its off-white: nothing to say.
    expect(field().value).toBe('#2E7D5B')
    expect(note()).toBeNull()
    // #D04343 reads on white, not on its off-white: the colour stays, the note says how far and what would reach.
    await type(field(), '#D04343')
    await settle()
    expect(field().value).toBe('#D04343')
    expect(note()?.textContent).toContain(i18n.t('wizard.shortStart', { ratio: '4.13:1', hex: '#C43F3F' }))
    // Going on takes the colour as entered.
    await click(buttons(i18n.t('wizard.takeThis'))[0])
    const values = [...page.querySelectorAll('input')].map((input) => input.value.toUpperCase())
    expect(values).toContain('#D04343')
    expect(values).not.toContain('#C43F3F')
  })

  it('changes the start colour only with the button', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/clients/name-check') return { status: 200, body: { free: true, code: null } }
    }
    const { NewClientPage } = await import('./NewClientPage')
    const page = await mount(<NewClientPage />, '/new', 'de')
    await type(page.querySelector(`input[placeholder="${i18n.t('wizard.nameHint')}"]`), 'Beispielwerk')
    await settle()
    await click(buttons(i18n.t('wizard.next'))[0])
    const field = () => page.querySelector(`input:not([type="color"])[aria-label="${i18n.t('wizard.startColor')}"]`) as HTMLInputElement
    await type(field(), '#D04343')
    await settle()
    expect(page.querySelector('[role="status"]')?.textContent).toContain('Auf dem hellen Grundton, den nexbrand dazulegt, erreicht diese Farbe nur 4,13:1. Für Text sind 4,5:1 nötig. Im gleichen Farbton reicht #C43F3F.')
    await click(buttons('Übernehmen')[0])
    expect(field().value).toBe('#C43F3F')
    expect(page.querySelector('[role="status"]')).toBeNull()
    await click(buttons(i18n.t('wizard.takeThis'))[0])
    const values = [...page.querySelectorAll('input')].map((input) => input.value.toUpperCase())
    expect(values).toContain('#C43F3F')
    expect(values).not.toContain('#D04343')
  })

  it('takes a start colour as people write it: without "#", or short', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/clients/name-check') return { status: 200, body: { free: true, code: null } }
    }
    const { NewClientPage } = await import('./NewClientPage')
    const page = await mount(<NewClientPage />, '/new')
    await type(page.querySelector(`input[placeholder="${i18n.t('wizard.nameHint')}"]`), 'Example Works')
    await settle()
    await click(buttons(i18n.t('wizard.next'))[0])
    const field = () => page.querySelector(`input:not([type="color"])[aria-label="${i18n.t('wizard.startColor')}"]`) as HTMLInputElement
    const go = () => buttons(i18n.t('wizard.takeThis'))[0] as HTMLButtonElement
    // Without "#": the same note as with it, and the way on is open.
    await type(field(), 'd04343')
    await settle()
    expect(page.querySelector('[role="status"]')?.textContent).toContain(i18n.t('wizard.shortStart', { ratio: '4.13:1', hex: '#C43F3F' }))
    expect(go().disabled).toBe(false)
    // Short: #555 is #555555, which reads on its off-white, so nothing to say.
    await type(field(), '#555')
    await settle()
    expect(page.querySelector('[role="status"]')).toBeNull()
    expect(go().disabled).toBe(false)
    // Not a colour: the way on stays shut.
    await type(field(), '#55')
    await settle()
    expect(go().disabled).toBe(true)
    await type(field(), '#555')
    await settle()
    await click(go())
    expect(taken(page)[0]).toBe('#555555')
  })

  /** The start "from a picture" with a picture of these colours (and how many pixels each), read the way the page reads
   * one: through a canvas. */
  async function withPicture(parts: [string, number][], test: (page: HTMLElement) => Promise<void>): Promise<void> {
    server.handler = (_m, path) => {
      if (path === '/api/clients/name-check') return { status: 200, body: { free: true, code: null } }
    }
    const pixels = new Uint8ClampedArray(96 * 96 * 4)
    let at = 0
    for (const [hex, count] of parts)
      for (let n = 0; n < count; n++, at += 4) pixels.set([parseInt(hex.slice(1, 3), 16), parseInt(hex.slice(3, 5), 16), parseInt(hex.slice(5, 7), 16), 255], at)
    const context = { clearRect: () => undefined, drawImage: () => undefined, getImageData: () => ({ data: pixels }) }
    const canvas = vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation((() => context) as unknown as HTMLCanvasElement['getContext'])
    const picture = vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockImplementation(() => 'data:image/png;base64,')
    vi.stubGlobal('Image', class {
      onload: () => void = () => undefined
      set src(_value: string) {
        queueMicrotask(() => this.onload())
      }
    })
    const urls = URL as unknown as { createObjectURL?: unknown; revokeObjectURL?: unknown }
    urls.createObjectURL = () => 'blob:picture'
    urls.revokeObjectURL = () => undefined
    try {
      const { NewClientPage } = await import('./NewClientPage')
      const page = await mount(<NewClientPage />, '/new')
      await type(page.querySelector(`input[placeholder="${i18n.t('wizard.nameHint')}"]`), 'Example Works')
      await settle()
      await click(buttons(i18n.t('wizard.next'))[0])
      await click([...page.querySelectorAll('[role="tab"]')].find((tab) => tab.textContent?.includes(i18n.t('wizard.mode.picture'))))
      const input = page.querySelector('input[type="file"]') as HTMLInputElement
      Object.defineProperty(input, 'files', { value: [new File(['x'], 'mood.png', { type: 'image/png' })] })
      await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
      await settle()
      await test(page)
    } finally {
      canvas.mockRestore()
      picture.mockRestore()
      delete urls.createObjectURL
      delete urls.revokeObjectURL
    }
  }

  const swatches = (page: HTMLElement) => [...page.querySelectorAll('span.font-mono')].map((s) => s.textContent)
  /** The colours in the colour step, in their order (main colour first), each once. */
  const taken = (page: HTMLElement) => [...new Set([...page.querySelectorAll('input')].map((field) => field.value.toUpperCase()).filter((value) => /^#[0-9A-F]{6}$/.test(value)))]

  it('keeps the colours of a picture as measured and offers the main one that reaches, only taken by the button', async () => {
    await withPicture([['#F6EFE4', 5000], ['#D9822B', 2000], ['#2B2A28', 1500], ['#6F8F55', 716]], async (page) => {
      const { contrast, formatRatio, reach } = await import('../lib/color')
      // The main colour on the light one of the picture, and the nearest of its hue that reaches, as the checker says.
      const better = reach('#D9822B', '#F6EFE4', 4.5)!
      const note = () => page.querySelector('[role="status"]')
      expect(note()?.textContent).toContain(i18n.t('wizard.shortPicture', { color: '#D9822B', ratio: formatRatio(contrast('#D9822B', '#F6EFE4'), 'en'), hex: better }))
      expect(swatches(page)).toEqual(['#F6EFE4', '#D9822B', '#2B2A28', '#6F8F55'])
      await click(buttons(i18n.t('wizard.useBetter'))[0])
      expect(note()).toBeNull()
      expect(swatches(page)).toEqual(['#F6EFE4', better, '#2B2A28', '#6F8F55'])
      await click(buttons(i18n.t('wizard.takeColors'))[0])
      expect(taken(page)).toEqual([better, '#6F8F55', '#F6EFE4', '#2B2A28'])
    })
  })

  it('keeps the roles of a picture when the darker main colour is taken, though it is now the darkest', async () => {
    // Read anew, the darker orange would be the dark neutral and the grey blue the main colour.
    await withPicture([['#F6EFE4', 5000], ['#F2A65A', 2000], ['#8A9A8A', 1500], ['#6F8FA5', 716]], async (page) => {
      const { reach } = await import('../lib/color')
      const better = reach('#F2A65A', '#F6EFE4', 4.5)!
      await click(buttons(i18n.t('wizard.useBetter'))[0])
      await click(buttons(i18n.t('wizard.takeColors'))[0])
      expect(taken(page)).toEqual([better, '#8A9A8A', '#F6EFE4', '#6F8FA5'])
    })
  })
})

// --- G11: the family in words --------------------------------------------------------------------------------------

describe('the family', () => {
  it('the about page says "Version" for the app and shows the family', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/about') return { status: 200, body: { version: '0.1.0', license: 'AGPL-3.0', repo_url: 'https://github.com/example/nexbrand', releases_url: 'https://github.com/example/nexbrand/releases', project_url: '' } }
    }
    const { AboutPage } = await import('./AboutPage')
    const page = await mount(<AboutPage />, '/about', 'de')
    expect(page.querySelector('[data-testid="about-facts"] dt')?.textContent).toBe('Version')
    const family = page.querySelector('#about-family')
    expect(family?.querySelector('h2')?.textContent).toBe(i18n.t('about.family'))
    expect([...family!.querySelectorAll('li')].map((li) => li.querySelector('.font-semibold')?.textContent)).toEqual(['nexcanvas', 'nexlore', 'nextasks', 'nexmail'])
    expect(document.title).toBe(`${i18n.t('about.menu')} · nexbrand`)
  })

  it('the about page does not name nexsuite, in either language: it is what everybody sees, coupled or not', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/about') return { status: 200, body: { version: '0.1.0', license: 'AGPL-3.0', repo_url: 'https://github.com/example/nexbrand', releases_url: 'https://github.com/example/nexbrand/releases', project_url: '' } }
    }
    const { AboutPage } = await import('./AboutPage')
    for (const language of ['de', 'en'] as const) {
      const page = await mount(<AboutPage />, '/about', language)
      expect(page.querySelector('#about-family')?.textContent).toContain(i18n.t('about.familyText'))
      expect(page.textContent?.toLowerCase()).not.toContain('nexsuite')
      await act(async () => root?.unmount())
      host?.remove()
    }
  })

  it('offers the languages in the order of their names (account menu and settings both ask languageOptions)', async () => {
    const added = [
      { code: 'fr', name: 'Français', keys: 10 },
      { code: 'cs', name: 'Čeština', keys: 10 },
      { code: 'es', name: 'Español', keys: 10 },
      { code: 'nl', name: 'Nederlands', keys: 10 },
    ]
    server.handler = (_m, path) => {
      if (path === '/api/locales') return { status: 200, body: added }
      if (path === '/api/settings') return { status: 200, body: {} }
    }
    const { forgetAddedLanguages, languageOptions } = await import('../i18n')
    forgetAddedLanguages()
    const order = ['Čeština', 'Deutsch', 'English', 'Español', 'Français', 'Nederlands']
    expect((await languageOptions()).map((o) => o.name)).toEqual(order)
    const { AccountMenu } = await import('../components/AccountMenu')
    const page = await mount(<AccountMenu />, '/')
    const shown = () => [...page.querySelectorAll('select option')].map((o) => o.textContent)
    await click(page.querySelector('button[aria-haspopup="true"]'))
    expect(shown()).toEqual(order)
    forgetAddedLanguages()
  })

  it('lists the added languages on the operator\'s card by name, after the two built in', async () => {
    server.handler = (_m, path) => {
      if (path === '/api/locales')
        // As the server sends them: by code.
        return { status: 200, body: [{ code: 'af', name: 'Zulu', keys: 3 }, { code: 'cs', name: 'Čeština', keys: 3 }, { code: 'es', name: 'Español', keys: 3 }, { code: 'fr', name: 'Français', keys: 3 }] }
    }
    const { LanguagesCard } = await import('./settings/ServerCards')
    const page = await mount(<LanguagesCard />, '/settings')
    const chips = [...page.querySelectorAll('span.rounded-full')].map((chip) => chip.textContent?.split(' ')[0])
    expect(chips).toEqual(['Deutsch', 'English', 'Čeština', 'Español', 'Français', 'Zulu'])
  })

  it('German keys are "Strg", and the header names its parts as nexsuite and nextasks do', async () => {
    await i18n.changeLanguage('de')
    expect(i18n.t('keys.ctrl')).toBe('Strg')
    expect(i18n.t('app.home')).toBe('Zur Startseite')
    expect(i18n.t('theme.group')).toBe('Hell oder dunkel')
    expect(i18n.t('account.menu', { name: 'Robin' })).toBe('Konto von Robin')
    await i18n.changeLanguage('en')
  })
})

// --- F28: two "Edit" on the client's page ----------------------------------------------------------------------------

describe('the client page', () => {
  it('says what each of its two edit buttons edits', () => {
    for (const language of ['de', 'en']) {
      const t = i18n.getFixedT(language)
      expect(t('client.edit')).not.toBe(t('client.editDraft'))
      // Before, both said only this.
      expect([t('client.edit'), t('client.editDraft')]).not.toContain(language === 'de' ? 'Bearbeiten' : 'Edit')
    }
  })
})

// --- Connecting: nexsuite's refusals of a pairing (nexsuite 3ef5282) --------------------------------------------------

describe('the connect assistant', () => {
  it('says what to do when nexsuite refuses for an older connection of this address', async () => {
    const { errorText } = await import('../lib/errors')
    for (const code of ['app_still_connected', 'app_not_reachable', 'invalid_characters', 'password_unchanged']) {
      expect(errorText(code)).toBe(i18n.t(`errors.${code}`))
      expect(errorText(code)).not.toBe(i18n.t('errors.internal_error'))
    }
  })
})
