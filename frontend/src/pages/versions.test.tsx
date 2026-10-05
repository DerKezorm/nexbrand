// A client's page and collecting with a version that holds only from a later day (F2), a link to a project that is
// not there (F21), looking back (F29), and a logo the server took as a picture (F9). The server is a stub that answers
// by path.
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { ClientWhole, MediaInfo, Me, ProjectWhole, VersionInfo } from '../api/client'
import { SetEditor } from '../components/brand/SetEditor'
import i18n from '../i18n'
import { emptySet, type BrandSet } from '../lib/brand'
import { ClientPage } from './ClientPage'
import { CollectPage } from './CollectPage'

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true

type Answer = { status: number; body?: unknown }
const server: { handler: (method: string, path: string) => Answer | undefined } = { handler: () => undefined }
const uploads: { answer: MediaInfo | null } = { answer: null }

vi.mock('../api/client', async (importOriginal) => {
  const real = await importOriginal<typeof import('../api/client')>()
  return { ...real, mediaApi: { ...real.mediaApi, upload: async () => uploads.answer } }
})
const ME = { id: 1, name: 'robin', display_name: '', role: 'operator', sign_in: 'password', email: '', language: 'en', mail: true, suite: 'off', may_create_clients: true } as unknown as Me
vi.mock('../state/auth', async (importOriginal) => {
  const real = await importOriginal<typeof import('../state/auth')>()
  return { ...real, useAuth: () => ({ status: 'signedIn', me: ME, ended: false, refresh: async () => undefined, setMe: () => undefined, signOut: async () => undefined }) }
})
const CLIENTS = [{ id: 'clientAAA1', name: 'Example Bakery', role: 'manage', current: '1.0', drafts: 0 }]
vi.mock('../state/brands', () => ({
  useBrands: () => ({ refresh: async () => undefined, put: () => undefined, space: () => undefined, spaces: [], clients: CLIENTS }),
}))

let root: Root | null = null
let host: HTMLElement | null = null

async function settle(): Promise<void> {
  for (let i = 0; i < 15; i++)
    await act(async () => {
      for (let j = 0; j < 5; j++) await Promise.resolve()
    })
}

async function mount(ui: ReactNode, path: string, route: string): Promise<HTMLElement> {
  await i18n.changeLanguage('en')
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
  await act(async () =>
    root!.render(
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={ui} />
        </Routes>
      </MemoryRouter>,
    ),
  )
  await settle()
  return host
}

beforeEach(() => {
  server.handler = () => undefined
  uploads.answer = null
  vi.stubGlobal('fetch', async (url: string, init: RequestInit = {}) => {
    const answer = server.handler(init.method ?? 'GET', url.split('?')[0]) ?? { status: 404, body: { detail: { code: 'not_found' } } }
    return new Response(answer.status === 204 ? null : JSON.stringify(answer.body ?? {}), { status: answer.status, headers: { 'Content-Type': 'application/json' } })
  })
})

afterEach(async () => {
  await act(async () => root?.unmount())
  host?.remove()
  root = null
  host = null
  vi.unstubAllGlobals()
})

const SET: BrandSet = { ...emptySet(), colors: [{ name: 'Oven red', hex: '#B8322A', role: 'primary' }, { name: 'White', hex: '#FFFFFF', role: 'neutral' }] }
const LATER: BrandSet = { ...SET, colors: [{ name: 'Oven red', hex: '#1F5FBF', role: 'primary' }, { name: 'White', hex: '#FFFFFF', role: 'neutral' }] }

function version(id: string, label: string, validFrom: string, data: BrandSet, extra: Partial<VersionInfo> = {}): VersionInfo {
  return { id, label, status: 'published', valid_from: validFrom, origin: 'hand', author: 'robin', note: '', source_id: null, source_label: '', project_id: null, base_id: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', published_at: '2026-01-01T00:00:00Z', published_by: 'robin', data, ...extra } as unknown as VersionInfo
}

function whole(versions: VersionInfo[], currentId: string | null): ClientWhole {
  return {
    id: 'clientAAA1', space_id: 1, name: 'Example Bakery', color: '#2f7bff', managed: false, sector: '', contact: '', links: [], created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z', updated_by: 'robin', deleted_at: null,
    favorite: false, opened_at: null, role: 'manage', current: currentId ? '1.0' : null, current_id: currentId, drafts: 0, news: 0, face: { colors: [], logo: null, mark: null, fonts: [], sample: null },
    note: '', versions, projects: [], shares: 0, reviews: [],
  } as unknown as ClientWhole
}

const FIRST = version('v1aaaaaaaaaa', '1.0', '2026-01-19', SET)
const SECOND = version('v2aaaaaaaaaa', '2.0', '2030-01-01', LATER)

function answering(client: ClientWhole, project?: ProjectWhole | 'missing' | 'malformed') {
  server.handler = (method, path) => {
    if (path === '/api/clients/clientAAA1') return { status: 200, body: client }
    if (path === '/api/clients/clientAAA1/files') return { status: 200, body: {} }
    if (path === '/api/clients/clientAAA1/visit') return { status: 204 }
    if (path.startsWith('/api/clients/clientAAA1/projects/')) {
      if (project === 'missing') return { status: 404, body: { detail: { code: 'not_found' } } }
      if (project === 'malformed') return { status: 422, body: { detail: { code: 'invalid_input' } } }
      return project ? { status: 200, body: project } : undefined
    }
    if (path === '/api/ai/status' || path === '/api/collect/status') return { status: 200, body: {} }
    return method === 'GET' ? { status: 200, body: {} } : undefined
  }
}

const chipOf = (page: HTMLElement, label: string) => {
  const card = [...page.querySelectorAll('ol button')].find((b) => b.querySelector('.truncate')?.textContent === label)
  return card?.textContent ?? ''
}

describe('F2: a version that holds from a later day', () => {
  it('the version that holds today is current, the later one is upcoming', async () => {
    answering(whole([FIRST, SECOND], FIRST.id))
    const page = await mount(<ClientPage />, '/c/clientAAA1', '/c/:id')
    expect(chipOf(page, '1.0')).toContain(i18n.t('client.current'))
    expect(chipOf(page, '2.0')).not.toContain(i18n.t('client.current'))
    expect(chipOf(page, '2.0')).toContain(i18n.t('client.upcoming'))
  })

  it('a project on the later version is offered no lift back to the one that holds today', async () => {
    const own = { ...version('p1aaaaaaaaaa', '1.0', '2026-02-01', SET, { project_id: 'projAAAAAAA1', base_id: SECOND.id }), base_label: '2.0', resolved: SET, parts: { colors: [] } }
    const project = { id: 'projAAAAAAA1', name: 'Website', note: '', version_id: SECOND.id, current: '1.0', current_id: own.id, drafts: 0, base_id: SECOND.id, base_label: '2.0', behind: false, inherit: {}, face: { colors: [], logo: null, mark: null, fonts: [], sample: null }, versions: [own] } as unknown as ProjectWhole
    answering(whole([FIRST, SECOND], FIRST.id), project)
    const page = await mount(<ClientPage />, '/c/clientAAA1/p/projAAAAAAA1', '/c/:id/p/:pid')
    const box = page.querySelector('[data-testid=project-base]')
    expect(box).not.toBeNull()
    expect(box?.textContent).toContain('2.0')
    expect(box?.textContent).not.toContain(i18n.t('projects.liftTo', { label: '1.0' }))
    expect(box?.textContent).not.toContain(i18n.t('projects.newer', { label: '1.0' }).trim())
  })

  it('collecting checks against the version that holds today, and against none before any holds', async () => {
    answering(whole([SECOND], null))
    const page = await mount(<CollectPage />, '/collect?client=clientAAA1&mode=audit', '/collect')
    expect(page.textContent).toContain(i18n.t('collect.noCurrent'))
  })
})

describe('F21: a link to a project that is not there', () => {
  it.each(['missing', 'malformed'] as const)('says so (%s) and leads to the projects', async (kind) => {
    answering(whole([FIRST], FIRST.id), kind)
    const page = await mount(<ClientPage />, '/c/clientAAA1/p/zzz', '/c/:id/p/:pid')
    expect(page.querySelector('[data-testid=project-missing]')?.textContent).toContain(i18n.t('projects.missing'))
    expect(page.textContent).not.toContain(i18n.t('client.missing'))
  })
})

describe('F29: looking back', () => {
  it('no "3 years ago" where nothing held then, and a day without a version is said in the page', async () => {
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => undefined)
    answering(whole([FIRST], FIRST.id))
    const page = await mount(<ClientPage />, '/c/clientAAA1', '/c/:id')
    expect([...page.querySelectorAll('button')].some((b) => b.textContent === i18n.t('client.threeYears'))).toBe(false)
    const day = page.querySelector<HTMLInputElement>('input[type=date]')!
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    await act(async () => {
      setter.call(day, '2020-01-01')
      day.dispatchEvent(new Event('input', { bubbles: true }))
      day.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await settle()
    expect(page.querySelector('[data-testid=none-then]')).not.toBeNull()
    expect(alert).not.toHaveBeenCalled()
    alert.mockRestore()
  })

  it('offers "3 years ago" where a version held then', async () => {
    answering(whole([version('v0aaaaaaaaaa', '0.9', '2019-01-01', SET), FIRST], FIRST.id))
    const page = await mount(<ClientPage />, '/c/clientAAA1', '/c/:id')
    expect([...page.querySelectorAll('button')].some((b) => b.textContent === i18n.t('client.threeYears'))).toBe(true)
  })
})

describe('F9: a logo the server took', () => {
  it('becomes a logo whatever picture kind it is (BMP too)', async () => {
    uploads.answer = { id: 'mediaAAAAAA1', name: 'logo.bmp', kind: 'bmp', mime: 'image/bmp', size: 10, width: 4, height: 4, pages: 0, removed: [], known: false } as unknown as MediaInfo
    const changed: BrandSet[] = []
    const page = await mount(
      <SetEditor value={emptySet()} onChange={(s) => changed.push(s)} name="Example" ctx={{ space: 1, files: {}, addFile: () => undefined, fileUrl: (m) => m }} />,
      '/',
      '/',
    )
    const tab = [...page.querySelectorAll('button, [role=tab]')].find((b) => b.textContent?.startsWith(i18n.t('set.tabs.logos', { count: 0 }).split(' ')[0]))
    await act(async () => (tab as HTMLElement).click())
    await settle()
    const input = [...page.querySelectorAll<HTMLInputElement>('input[type=file]')].find((i) => i.accept.includes('.bmp'))!
    Object.defineProperty(input, 'files', { value: [new File(['x'], 'logo.bmp', { type: 'image/bmp' })] })
    await act(async () => input.dispatchEvent(new Event('change', { bubbles: true })))
    await settle()
    expect(changed.at(-1)?.logos.map((l) => l.media)).toEqual(['mediaAAAAAA1'])
  })
})
