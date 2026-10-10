// Versions, checks and export as the pages show them (Prüfgang 05.10.2026, block 5): comparing two versions in every
// part (F10), the contrast calculator with colours as people type them (F16) and ratios as they are graded (F17), the
// defaults and the list of API tokens (F12, F26), the place of a refused value (F11), and the type scale without its
// name twice (F33). The server is a stub that answers by path.
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Me, VersionInfo } from '../api/client'
import { ApiTokens } from '../components/ApiTokens'
import { DiffView } from '../components/brand/DiffView'
import { SetView } from '../components/brand/SetView'
import i18n from '../i18n'
import { emptySet, purposeBeside, type BrandSet } from '../lib/brand'
import { placeOf } from '../lib/where'
import { ContrastPage } from './ContrastPage'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

type Answer = { status: number; body?: unknown }
const server: { handler: (method: string, path: string, body: unknown) => Answer | undefined; calls: { method: string; path: string; body: unknown }[] } = {
  handler: () => undefined,
  calls: [],
}

let root: Root | null = null
let host: HTMLElement | null = null

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i++)
    await act(async () => {
      for (let j = 0; j < 5; j++) await Promise.resolve()
    })
}

async function mount(ui: ReactNode, language = 'en'): Promise<HTMLElement> {
  await i18n.changeLanguage(language)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => root!.render(<MemoryRouter>{ui}</MemoryRouter>))
  await settle()
  return host
}

async function type(element: Element | null | undefined, value: string): Promise<void> {
  if (!element) throw new Error('nothing to type into')
  const field = element as HTMLInputElement
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
  await act(async () => {
    setter.call(field, value)
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await settle()
}

async function click(element: Element | null | undefined): Promise<void> {
  if (!element) throw new Error('nothing to click')
  await act(async () => (element as HTMLElement).click())
  await settle()
}

const ME = { id: 1, name: 'robin', display_name: '', role: 'operator', sign_in: 'password', email: '', language: 'en', mail: true, suite: 'off' } as unknown as Me
vi.mock('../state/auth', async (importOriginal) => {
  const real = await importOriginal<typeof import('../state/auth')>()
  return { ...real, useAuth: () => ({ status: 'signedIn', me: ME, ended: false, refresh: async () => undefined, setMe: () => undefined, signOut: async () => undefined }) }
})
vi.mock('../state/brands', () => ({
  useBrands: () => ({ refresh: async () => undefined, space: () => undefined, spaces: [], clients: [{ id: 'c1', name: 'Example Bakery' }, { id: 'c2', name: 'Example Works' }] }),
}))

beforeEach(() => {
  server.handler = () => undefined
  server.calls = []
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const path = url.split('?')[0]
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined
    server.calls.push({ method, path, body })
    const answer = server.handler(method, path, body) ?? { status: 404, body: { detail: { code: 'not_found' } } }
    return new Response(JSON.stringify(answer.body ?? {}), { status: answer.status, headers: { 'Content-Type': 'application/json' } })
  })
})

afterEach(async () => {
  await act(async () => root?.unmount())
  host?.remove()
  root = null
  host = null
  vi.unstubAllGlobals()
})

function version(id: string, data: Partial<BrandSet>): VersionInfo {
  return { id, label: id, status: 'published', valid_from: '2026-01-01', data: { ...emptySet(), ...data } } as unknown as VersionInfo
}

const STEP = { name: 'Heading 1', use: 'h1' as const, size: 40, weight: 600, font: 'Inter', line_height: 1.15 }

describe('F10: comparing two versions sees every part', () => {
  it('a new type scale, a rule and a dark mode are differences, not "the same"', async () => {
    const colors = [{ name: 'Ink', hex: '#14141A', role: 'neutral' as const }, { name: 'White', hex: '#FFFFFF', role: 'neutral' as const }]
    const a = version('a', { colors, scale: [STEP] })
    const b = version('b', {
      colors,
      scale: [{ ...STEP, size: 52, weight: 800, line_height: 1.3 }],
      rules: [{ kind: 'do', text: 'Warm photos.' }],
      dark: { ground: 'Ink', surface: 'Ink', text: 'White', muted: 'White', primary: 'White', on_primary: 'Ink' },
    })
    const page = await mount(<DiffView a={a} b={b} />)
    const text = page.textContent ?? ''
    expect(text).not.toContain(i18n.t('diff.nothing'))
    expect(text).toContain('Heading 1')
    expect(text).toMatch(/size\s*40 px.*52 px/)
    expect(text).toContain('line height')
    expect(text).toContain('Warm photos.')
    expect(text).toContain(i18n.t('inherit.part.dark'))
  })

  it('says so when the two are the same', async () => {
    const page = await mount(<DiffView a={version('a', { scale: [STEP] })} b={version('b', { scale: [STEP] })} />)
    expect(page.textContent).toContain(i18n.t('diff.nothing'))
  })
})

describe('F16, F17: the contrast calculator', () => {
  const fields = () => [...document.body.querySelectorAll<HTMLInputElement>('input:not([type=color])')]

  it('takes 000 and #000 while typing, and names a colour it cannot read', async () => {
    const page = await mount(<ContrastPage />)
    const [text, ground] = fields()
    await type(text, '#ffffff')
    await type(ground, '000')
    expect(page.textContent).toContain('21.0:1')
    await type(ground, '#000')
    expect(page.textContent).toContain('21.0:1')
    await type(ground, 'rgb(0, 0, 0)')
    expect(page.textContent).toContain('21.0:1')
    await type(ground, 'zzz')
    const alert = page.querySelector('[role=alert]')
    expect(alert?.textContent).toContain('“zzz”')
    expect(ground.getAttribute('aria-invalid')).toBe('true')
  })

  it('shows 4.49:1 beside "fails", never 4.50:1', async () => {
    const page = await mount(<ContrastPage />)
    const [text, ground] = fields()
    await type(text, '#00848A')
    await type(ground, '#FFFFFF')
    expect(page.textContent).toContain('4.49:1')
    expect(page.textContent).not.toContain('4.50:1')
  })
})

describe('F12, F26: API tokens', () => {
  const TOKEN = { id: 7, name: 'Pipeline', level: 'draft', prefix: 'nxb_abcd', created_at: '2026-10-04T18:45:00Z', last_used_at: '2026-10-04T18:45:00Z', expires_at: null, blocked: false, clients: null }

  it('lists the level and the day as the app writes it; a new one starts narrow and for 90 days', async () => {
    server.handler = (method, path) => {
      if (path === '/api/api-tokens' && method === 'GET') return { status: 200, body: { allowed: true, tokens: [TOKEN] } }
      if (path === '/api/api-tokens' && method === 'POST') return { status: 201, body: { token: { ...TOKEN, id: 8 }, secret: 'nxb_secret' } }
      return undefined
    }
    const page = await mount(<ApiTokens />)
    expect(page.querySelector('[data-testid=api-token-level]')?.textContent).toBe(i18n.t('apiTokens.levels.draft'))
    expect(page.textContent).toContain('10/4/2026')
    await click([...page.querySelectorAll('button')].find((b) => b.textContent?.includes(i18n.t('apiTokens.new'))))
    const radios = [...page.querySelectorAll<HTMLInputElement>('input[name=api-clients]')]
    expect(radios.map((r) => r.checked)).toEqual([false, true])
    const days = [...page.querySelectorAll<HTMLInputElement>('input[name=api-days]')]
    expect(days.map((d) => d.checked)).toEqual([false, true, false, false])
    expect(page.querySelector('[data-testid=api-token-choose]')).not.toBeNull()
    await type(page.querySelector('form input:not([type])') ?? page.querySelector('form input'), 'ci')
    const make = page.querySelector<HTMLButtonElement>('form button[type=submit]')
    expect(make?.disabled).toBe(true)
    await click([...page.querySelectorAll<HTMLInputElement>('input[type=checkbox]')][0])
    expect(make?.disabled).toBe(false)
    await click(make)
    const sent = server.calls.find((c) => c.method === 'POST')?.body as Record<string, unknown>
    expect(sent).toMatchObject({ name: 'ci', clients: ['c1'], days: 90 })
    expect(sent.all_clients).toBeUndefined()
  })
})

describe('API tokens of an account let in by a provider (module 1.0.10)', () => {
  const TOKEN = { id: 7, name: 'Pipeline', level: 'read', prefix: 'nxb_abcd', created_at: '2026-10-04T18:45:00Z', last_used_at: null, expires_at: null, blocked: false, clients: null }
  const notes = (page: HTMLElement) => [...page.querySelectorAll('[data-testid=keys-wait]')]
  const listed = () => {
    server.handler = (method, path) => {
      if (path === '/api/api-tokens' && method === 'GET') return { status: 200, body: { allowed: true, tokens: [TOKEN] } }
      if (path === '/api/api-tokens' && method === 'POST') return { status: 201, body: { token: { ...TOKEN, id: 8 }, secret: 'nxb_secret' } }
      return undefined
    }
  }
  afterEach(() => {
    delete (ME as { keys_wait_for_second_factor?: boolean }).keys_wait_for_second_factor
  })

  it.each([
    ['en', 'Works only once you set up a second factor.', 'Set up a second factor'],
    ['de', 'Wirkt erst, wenn du einen zweiten Faktor einrichtest.', 'Zweiten Faktor einrichten'],
  ])('says in %s beside each token, the form and the new token that they wait for a second factor', async (language, sentence, link) => {
    ME.keys_wait_for_second_factor = true
    listed()
    const page = await mount(<ApiTokens />, language)
    expect(notes(page)).toHaveLength(1)
    expect(notes(page)[0].textContent).toBe(`${sentence} ${link}`)
    expect(notes(page)[0].querySelector('a')!.getAttribute('href')).toBe('/account?tab=security')
    // Making one stays possible: the form carries the note too, and so does the token shown once.
    await click([...page.querySelectorAll('button')].find((b) => b.textContent?.includes(i18n.t('apiTokens.new'))))
    expect(notes(page)).toHaveLength(2)
    await type(page.querySelector('form input:not([type])') ?? page.querySelector('form input'), 'ci')
    await click([...page.querySelectorAll<HTMLInputElement>('input[type=checkbox]')][0])
    await click(page.querySelector<HTMLButtonElement>('form button[type=submit]'))
    expect(server.calls.some((c) => c.method === 'POST')).toBe(true)
    expect(page.querySelector('[data-testid=api-token-shown] [data-testid=keys-wait]')).not.toBeNull()
  })

  it('says nothing to an account whose keys work', async () => {
    listed()
    const page = await mount(<ApiTokens />)
    await click([...page.querySelectorAll('button')].find((b) => b.textContent?.includes(i18n.t('apiTokens.new'))))
    expect(notes(page)).toHaveLength(0)
  })
})

describe('F11: where a refused value sits', () => {
  const set: BrandSet = { ...emptySet(), colors: [{ name: 'Primary', hex: '#123456', role: 'primary' }, { name: 'Accent', hex: 'xyz', role: 'accent' }] }
  it('names the colour and the field', () => {
    expect(placeOf('colors.1.hex', set)).toEqual({ part: 'colors', index: 1, name: 'Accent', field: 'hex', twice: false })
    expect(placeOf('dark.primary', set)).toEqual({ part: 'dark', index: null, name: '', field: 'primary', twice: false })
    const twice = { ...set, colors: [...set.colors, { name: 'accent', hex: '#000000', role: 'neutral' as const }] }
    expect(placeOf('colors.2.name', twice)?.twice).toBe(true)
  })
})

describe('F33: a step of the type scale', () => {
  it('shows what it is for only when that is not its name', async () => {
    expect(purposeBeside('Heading 1', 'Heading 1')).toBeNull()
    expect(purposeBeside('Title', 'Heading 1')).toBe('Heading 1')
    const page = await mount(<SetView set={{ ...emptySet(), fonts: [{ family: 'Inter', role: '', weights: [400], license: 'free' }], scale: [STEP, { ...STEP, name: 'Title' }] }} fileUrl={(m) => m} files={{}} tab="fonts" onTab={() => undefined} />)
    expect(page.textContent).not.toContain('Heading 1 (Heading 1)')
    expect(page.textContent).toContain('Title(Heading 1)')
  })
})
