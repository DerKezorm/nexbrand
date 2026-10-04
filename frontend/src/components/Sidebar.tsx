import { ChevronDown, ChevronRight, Clock, LayoutDashboard, Plus, Star } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { ClientInfo } from '../api/client'
import { useNotices } from '../lib/notices'
import { useAuth } from '../state/auth'
import { useBrands } from '../state/brands'
import { useShell } from './AppShell'
import { NoticeList } from './Notices'

function Section({ title, children, open, onToggle, action }: { title: string; children: ReactNode; open: boolean; onToggle: () => void; action?: ReactNode }) {
  return (
    <section className="border-b border-ink-700/60 px-2.5 py-2.5">
      <div className="flex items-center">
        <button type="button" onClick={onToggle} aria-expanded={open} className="flex flex-1 items-center gap-1.5 px-1.5 py-1 text-[11px] font-semibold tracking-wider text-mist-500 uppercase hover:text-mist-100">
          {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          {title}
        </button>
        {action}
      </div>
      {open && <div className="mt-1 space-y-0.5">{children}</div>}
    </section>
  )
}

/** A client's colours as a small striped square, the way the sidebar and lists tell clients apart. */
export function Swatch({ client, className = 'h-3.5 w-3.5' }: { client: Pick<ClientInfo, 'face' | 'color'>; className?: string }) {
  // Without a design set yet, the client's own colour stands in.
  const colors = client.face.colors.length ? client.face.colors.slice(0, 3) : [client.color]
  return (
    <span className={'flex shrink-0 overflow-hidden rounded border border-ink-700 ' + className} aria-hidden>
      {colors.length ? colors.map((c, i) => <span key={i} className="flex-1" style={{ background: c }} />) : <span className="flex-1 bg-ink-800" />}
    </span>
  )
}

/** The left column of the overview, built like nexlore's and nexcanvas's: recent, favourites, every client. */
export function Sidebar() {
  const { me } = useAuth()
  const { t } = useTranslation()
  const brands = useBrands()
  const shell = useShell()
  const [open, setOpen] = useState({ recent: true, favorites: true })
  const live = brands.clients
  const recent = live.filter((c) => c.opened_at).sort((a, b) => Date.parse(b.opened_at!) - Date.parse(a.opened_at!)).slice(0, 4)
  const favorites = live.filter((c) => c.favorite)
  const notices = useNotices()

  const row = 'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[13px] text-mist-400 hover:bg-ink-850 hover:text-mist-100'

  return (
    <aside className="nc-scroll hidden w-72 shrink-0 flex-col overflow-y-auto border-r border-ink-700/80 bg-ink-950/60 md:flex" aria-label={t('sidebar.label')}>
      {notices.length > 0 && (
        <section className="border-b border-ink-700/60 px-2.5 py-2.5" data-testid="sidebar-notices">
          <div className="px-1.5 py-1 text-[11px] font-semibold tracking-wider text-accent-400 uppercase">{t('notices.section', { count: notices.length })}</div>
          <div className="mt-1">
            <NoticeList notices={notices} />
          </div>
        </section>
      )}
      <Section title={t('sidebar.recent')} open={open.recent} onToggle={() => setOpen((o) => ({ ...o, recent: !o.recent }))}>
        {recent.length === 0 && <p className="px-2.5 py-1 text-xs text-mist-600">{t('sidebar.noRecent')}</p>}
        {recent.map((c) => (
          <Link key={c.id} to={`/c/${c.id}`} className={row}>
            <Clock className="h-3.5 w-3.5 shrink-0 opacity-60" />
            <span className="truncate">{c.name}</span>
          </Link>
        ))}
      </Section>
      <Section title={t('sidebar.favorites')} open={open.favorites} onToggle={() => setOpen((o) => ({ ...o, favorites: !o.favorites }))}>
        {favorites.length === 0 && <p className="px-2.5 py-1 text-xs text-mist-600">{t('sidebar.noFavorites')}</p>}
        {favorites.map((c) => (
          <Link key={c.id} to={`/c/${c.id}`} className={row}>
            <Star className="h-3.5 w-3.5 shrink-0 text-accent-400" />
            <span className="truncate">{c.name}</span>
          </Link>
        ))}
      </Section>
      <section className="px-2.5 py-2.5">
        <div className="flex items-center justify-between px-1.5">
          <span className="rounded-full bg-ink-850 px-3 py-1 text-[11px] font-semibold tracking-wider text-mist-100 uppercase">{t('sidebar.clients')}</span>
          {/* Connected to nexsuite, clients are made there; here they get their design set. */}
          {me?.may_create_clients && (
            <button type="button" className="rounded p-1 text-mist-500 hover:bg-ink-850 hover:text-mist-100" title={t('client.new')} aria-label={t('client.new')} onClick={() => shell.newClient()}>
              <Plus className="h-4 w-4" />
            </button>
          )}
        </div>
        <div className="mt-2 space-y-0.5">
          <Link to="/" className={row + ' bg-accent-500/12 text-mist-100'}>
            <LayoutDashboard className="h-3.5 w-3.5 shrink-0 opacity-70" />
            <span className="font-semibold">{t('clients.all')}</span>
            <span className="ml-auto text-[11px] text-mist-600 tabular-nums">{live.length}</span>
          </Link>
          {[...live].sort((a, b) => a.name.localeCompare(b.name)).map((c) => (
            <Link key={c.id} to={`/c/${c.id}`} className={row}>
              <Swatch client={c} />
              <span className="truncate">{c.name}</span>
              {c.current === null && c.drafts === 0 && <span className="ml-auto shrink-0 text-[10px] text-mist-600">{t('client.noCi')}</span>}
            </Link>
          ))}
          {live.length === 0 && <p className="px-2.5 py-1 text-xs text-mist-600">{t('sidebar.nothingHere')}</p>}
        </div>
      </section>
    </aside>
  )
}
