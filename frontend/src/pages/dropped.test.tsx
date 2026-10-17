// A client the directory service no longer gives nexbrand: only the operator sees it, marked in the side bar and on its page
// with what it means, and the operator may move it to the trash, bring it back and delete it for good here.
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClientInfo, ClientWhole, Me } from '../api/client'
import { Sidebar } from '../components/Sidebar'
import i18n from '../i18n'
import { emptySet } from '../lib/brand'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const ME = { id: 1, name: 'robin', display_name: '', role: 'operator', sign_in: 'password', email: '', language: 'en', mail: true, suite: 'connected', may_create_clients: false } as unknown as Me
vi.mock('../state/auth', async (importOriginal) => {
  const real = await importOriginal<typeof import('../state/auth')>()
  return { ...real, useAuth: () => ({ status: 'signedIn', me: ME, ended: false, refresh: async () => undefined, setMe: () => undefined, signOut: async () => undefined }) }
})
vi.mock('../lib/notices', async (importOriginal) => ({ ...(await importOriginal<typeof import('../lib/notices')>()), useNotices: () => [] }))
vi.mock('../components/AppShell', async (importOriginal) => ({ ...(await importOriginal<typeof import('../components/AppShell')>()), useShell: () => ({ newClient: () => undefined }) }))

const scene: { clients: ClientInfo[]; bin: ClientInfo[] } = { clients: [], bin: [] }
vi.mock('../state/brands', () => ({
  useBrands: () => ({
    loaded: true, spaces: [], clients: scene.clients, bin: scene.bin, space: () => undefined, client: () => undefined,
    refresh: async () => undefined, loadBin: async () => undefined, put: () => undefined,
  }),
}))

function info(patch: Partial<ClientInfo>): ClientInfo {
  return {
    id: 'c1', space_id: 7, name: 'Example Bakery', color: '#f472b6', managed: true, dropped: false, sector: '', contact: '', links: [],
    created_at: '2026-10-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z', updated_by: 'robin', deleted_at: null, favorite: false,
    opened_at: null, role: 'manage', current: null, drafts: 0, projects: 0, news: 0, face: { colors: [], logo: null }, ...patch,
  } as ClientInfo
}

const server: { handler: (method: string, path: string) => { status: number; body?: unknown } | undefined } = { handler: () => undefined }
let root: Root | null = null
let host: HTMLElement | null = null

async function mount(ui: ReactNode, path = '/', route = '*'): Promise<HTMLElement> {
  await i18n.changeLanguage('en')
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () => root!.render(<MemoryRouter initialEntries={[path]}><Routes><Route path={route} element={ui} /></Routes></MemoryRouter>))
  for (let i = 0; i < 15; i++) await act(async () => { for (let j = 0; j < 5; j++) await Promise.resolve() })
  return host
}

beforeEach(() => {
  scene.clients = [info({ id: 'c1', name: 'Ideen', dropped: true }), info({ id: 'c2', name: 'Studio' })]
  scene.bin = []
  server.handler = () => undefined
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const answer = server.handler(init.method ?? 'GET', url.split('?')[0]) ?? { status: 404, body: { detail: { code: 'not_found' } } }
    return new Response(answer.status === 204 ? null : JSON.stringify(answer.body ?? {}), { status: answer.status, headers: { 'Content-Type': 'application/json' } })
  })
})
afterEach(async () => {
  await act(async () => root?.unmount())
  host?.remove()
  root = host = null
  vi.unstubAllGlobals()
})

const HINT = 'nexbrand no longer gets this client from nexsuite. Its versions stay, only the operator sees it. You can move it to the trash.'

describe('a client the directory service let go', () => {
  it('is marked in the side bar with what it means, the others are not', async () => {
    const page = await mount(<Sidebar />)
    const marks = [...page.querySelectorAll('[data-testid="client-dropped"]')]
    expect(marks).toHaveLength(1)
    expect(marks[0].textContent).toBe('no longer in nexsuite')
    expect(marks[0].getAttribute('title')).toBe(HINT)
    expect(marks[0].closest('a')!.textContent).toContain('Ideen')
  })

  it.each([
    ['without a design set', []],
    ['with one', [{ id: 'v1aaaaaaaaaa', label: '1.0', status: 'published', valid_from: '2026-01-19', origin: 'hand', author: 'robin', note: '', source_id: null, source_label: '', project_id: null, base_id: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', published_at: '2026-01-01T00:00:00Z', published_by: 'robin', data: emptySet() }]],
  ])('says so on its page and offers the trash there, %s', async (_kind, versions) => {
    const whole = { ...info({ id: 'clientAAA1', name: 'Ideen', dropped: true }), note: '', versions, projects: [], shares: 0, reviews: [], current_id: versions.length ? 'v1aaaaaaaaaa' : null, current: versions.length ? '1.0' : null } as unknown as ClientWhole
    server.handler = (method, path) => {
      if (path === '/api/clients/clientAAA1') return { status: 200, body: whole }
      if (path === '/api/clients/clientAAA1/visit') return { status: 204 }
      return method === 'GET' ? { status: 200, body: {} } : undefined
    }
    const { ClientPage } = await import('./ClientPage')
    const page = await mount(<ClientPage />, '/c/clientAAA1', '/c/:id')
    expect(page.querySelector('[data-testid="client-dropped-hint"]')?.textContent).toBe(HINT)
    expect([...page.querySelectorAll('button')].some((b) => b.textContent?.trim() === i18n.t('client.trash'))).toBe(true)
  })

  it('in the trash it can be brought back and deleted for good here; one deleted in the directory service cannot', async () => {
    scene.bin = [
      info({ id: 'c1', name: 'Ideen', dropped: true, deleted_at: '2026-10-04T10:00:00Z' }),
      info({ id: 'c3', name: 'Kurbel', deleted_at: '2026-10-04T10:00:00Z' }),
    ]
    const { ClientsPage } = await import('./ClientsPage')
    const page = await mount(<ClientsPage />, '/?bin=1')
    const card = (name: string) => [...page.querySelectorAll('[data-testid="bin-card"]')].find((c) => c.querySelector('h2')?.textContent === name)!
    expect(card('Ideen').querySelector(`[aria-label="${i18n.t('clients.restoreThis', { name: 'Ideen' })}"]`)).not.toBeNull()
    expect(card('Ideen').querySelector(`[aria-label="${i18n.t('clients.purgeThis', { name: 'Ideen' })}"]`)).not.toBeNull()
    expect(card('Ideen').textContent).not.toContain(i18n.t('clients.binSuite'))
    expect(card('Kurbel').querySelector(`[aria-label="${i18n.t('clients.restoreThis', { name: 'Kurbel' })}"]`)).toBeNull()
    expect(card('Kurbel').textContent).toContain(i18n.t('clients.binSuite'))
  })
})
