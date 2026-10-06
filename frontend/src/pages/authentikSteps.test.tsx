// The steps after "Set up" under Settings, Server, Sign-in (the authentik button): each by its name, then what the server
// found; a failed one with its reason in words, as nexsuite says it (Prüfgang C4), and a line while authentik is asked.
// As in nextasks. The keys come from the server's own list (`STEP_KEYS` in backend/app/services/authentik.py), so a step
// the language files do not name shows up here instead of as a bare English line on the operator's screen.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Me } from '../api/client'
import i18n from '../i18n'
import de from '../i18n/de.json'
import en from '../i18n/en.json'
import { SignInCard, useServerSettings } from './settings/ServerCards'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

type Files = { readFileSync: (file: string, encoding: string) => string }
const fsName = 'node:fs'
const files = (await import(/* @vite-ignore */ fsName)) as Files

const service = files.readFileSync('../backend/app/services/authentik.py', 'utf-8')
const STEP_KEYS = [...(service.match(/^STEP_KEYS = \(([^)]*)\)/m)?.[1] ?? '').matchAll(/"(\w+)"/g)].map((found) => found[1])
const TEXTS = { de, en } as const
type Language = keyof typeof TEXTS
type Step = { key: string; ok: boolean; detail: string; reason?: string; status?: number }

const ME = { id: 1, name: 'robin', display_name: '', role: 'operator', sign_in: 'password', two_factor: true, suite: '' } as unknown as Me
vi.mock('../state/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../state/auth')>()),
  useAuth: () => ({ status: 'signedIn', me: ME, ended: false, refresh: async () => undefined, setMe: () => undefined, signOut: async () => undefined }),
}))

/** What the stub answers; `steps` is the set-up run's answer, held back while `gate` is set. */
const server: { steps: Step[]; gate: Promise<void> | null; pending: number } = { steps: [], gate: null, pending: 0 }

function answer(method: string, path: string): unknown {
  if (method === 'GET' && path === '/api/settings') return { password_login: true, two_factor_required: false, public_url: '' }
  if (method === 'GET' && path === '/api/oidc/config')
    return { configured: false, issuer: '', client_id: '', provider_name: '', auto_create: false, redirect_uri: 'https://brand.example.com/api/oidc/callback' }
  if (method === 'POST' && path === '/api/oidc/authentik/setup') return { steps: server.steps }
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

function SignIn() {
  const server = useServerSettings()
  return <SignInCard server={server} />
}

/** The card in `language`, with address and token typed in; the button not yet pressed. */
async function card(language: Language): Promise<HTMLElement> {
  await i18n.changeLanguage(language)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => root!.render(<SignIn />))
  await settle()
  await type(host.querySelector('input[placeholder="https://auth.example.com"]'), 'https://auth.example.com')
  await type([...host.querySelectorAll('input[type="password"]')].at(-1), 'token')
  return host
}

async function setUp(page: HTMLElement): Promise<void> {
  const run = [...page.querySelectorAll('button')].find((b) => b.textContent?.trim() === i18n.t('server.authentik.run'))
  await act(async () => run?.click())
}

const rows = (page: HTMLElement) => [...page.querySelectorAll('[data-testid="authentik-steps"] li')].map((row) => row.textContent)

beforeEach(() => {
  server.steps = []
  server.gate = null
  server.pending = 0
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    server.pending++
    try {
      const method = init.method ?? 'GET'
      const path = url.split('?')[0]
      if (path === '/api/oidc/authentik/setup' && server.gate) await server.gate
      await Promise.resolve()
      const body = answer(method, path)
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
    expect(STEP_KEYS).toContain('reached')
    expect(STEP_KEYS).toContain('filled')
  })

  it.each(['en', 'de'] as const)('are named in %s, each before what the server found', async (language) => {
    server.steps = STEP_KEYS.map((key) => ({ key, ok: true, detail: `found ${key}` }))
    const page = await card(language)
    await setUp(page)
    await settle()
    const names: Record<string, string> = TEXTS[language].authentik.step
    expect(rows(page)).toEqual(STEP_KEYS.map((key) => `✓ ${names[key]}: found ${key}`))
  })

  it.each(['en', 'de'] as const)('say in %s why a step failed, by its name, and keep the token for the next try', async (language) => {
    const detail = 'POST /crypto/certificatekeypairs/generate/ answered 403 (application/json); the log has the answer'
    server.steps = [
      { key: STEP_KEYS[0], ok: true, detail: 'authentik 2026.8.1' },
      { key: STEP_KEYS[1], ok: false, detail, reason: 'token', status: 403 },
    ]
    const page = await card(language)
    await setUp(page)
    await settle()
    const names: Record<string, string> = TEXTS[language].authentik.step
    const why = TEXTS[language].server.authentik.why.token.replace('{{status}}', '403')
    expect(rows(page)).toEqual([`✓ ${names[STEP_KEYS[0]]}: authentik 2026.8.1`, `✗ ${names[STEP_KEYS[1]]}: ${why}`])
    expect(page.textContent).not.toContain(detail)
    expect(([...page.querySelectorAll('input[type="password"]')].at(-1) as HTMLInputElement).value).toBe('token')
  })

  it('says authentik is being asked while the run is under way, and the last answer goes first', async () => {
    server.steps = [{ key: STEP_KEYS[0], ok: false, detail: 'not reachable', reason: 'unreachable', status: 0 }]
    const page = await card('en')
    await setUp(page)
    await settle()
    expect(rows(page)).toHaveLength(1)
    let release = () => undefined as void
    server.gate = new Promise<void>((resolve) => {
      release = resolve
    })
    await setUp(page)
    expect(page.querySelector('[role="status"]')?.textContent).toBe(en.server.authentik.asking)
    expect(rows(page)).toEqual([])
    server.gate = null
    release()
    await settle()
    expect(page.querySelector('[role="status"]')).toBeNull()
    expect(rows(page)).toEqual([`✗ ${en.authentik.step.reached}: ${en.server.authentik.why.unreachable}`])
  })
})
