// The steps after "Set up" under Settings, Server, Sign-in (the authentik button): each by its name, then what the server
// found, as in nextasks. The keys come from the server's own list (`STEP_KEYS` in backend/app/services/authentik.py), so
// a step the language files do not name shows up here instead of as a bare English line on the operator's screen.
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
const NAMES: Record<string, Record<string, string>> = { de: de.authentik.step, en: en.authentik.step }

const ME = { id: 1, name: 'robin', display_name: '', role: 'operator', sign_in: 'password', two_factor: true, suite: '' } as unknown as Me
vi.mock('../state/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../state/auth')>()),
  useAuth: () => ({ status: 'signedIn', me: ME, ended: false, refresh: async () => undefined, setMe: () => undefined, signOut: async () => undefined }),
}))

const ANSWERS: Record<string, unknown> = {
  'GET /api/settings': { password_login: true, two_factor_required: false, public_url: '' },
  'GET /api/oidc/config': { configured: false, issuer: '', client_id: '', provider_name: '', auto_create: false, redirect_uri: 'https://brand.example.com/api/oidc/callback' },
  'POST /api/oidc/authentik/setup': { steps: STEP_KEYS.map((key) => ({ key, ok: true, detail: `found ${key}` })) },
}
let pending = 0

let root: Root | null = null
let host: HTMLElement | null = null

async function settle(): Promise<void> {
  for (let quiet = 0, round = 0; quiet < 3; round++) {
    if (round > 200) throw new Error(`settle: ${pending} answer(s) still out`)
    await act(async () => {
      for (let i = 0; i < 5; i++) await Promise.resolve()
    })
    quiet = pending === 0 ? quiet + 1 : 0
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

beforeEach(() => {
  pending = 0
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    pending++
    try {
      await Promise.resolve()
      const answer = ANSWERS[`${init.method ?? 'GET'} ${url.split('?')[0]}`]
      if (answer === undefined) return new Response(JSON.stringify({ detail: { code: 'not_found' } }), { status: 404, headers: { 'Content-Type': 'application/json' } })
      return new Response(JSON.stringify(answer), { status: 200, headers: { 'Content-Type': 'application/json' } })
    } finally {
      pending--
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

  it.each(['en', 'de'])('are named in %s, each before what the server found', async (language) => {
    await i18n.changeLanguage(language)
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    await act(async () => root!.render(<SignIn />))
    await settle()
    await type(host.querySelector('input[placeholder="https://auth.example.com"]'), 'https://auth.example.com')
    await type([...host.querySelectorAll('input[type="password"]')].at(-1), 'token')
    const run = [...host.querySelectorAll('button')].find((b) => b.textContent?.trim() === i18n.t('server.authentik.run'))
    await act(async () => run?.click())
    await settle()
    const rows = [...host.querySelectorAll('[data-testid="authentik-steps"] li')].map((row) => row.textContent)
    expect(rows).toEqual(STEP_KEYS.map((key) => `✓ ${NAMES[language][key]}: found ${key}`))
  })
})
