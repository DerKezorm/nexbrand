import { FolderKanban, Plus, RotateCcw, Search, Star, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'

import { clientsApi, mediaUrl, type ClientInfo } from '../api/client'
import { useShell } from '../components/AppShell'
import { LogoView } from '../components/brand/LogoView'
import { Sidebar } from '../components/Sidebar'
import { useBrands } from '../state/brands'

/** The overview: every client the account may see, or those of one space, or the bin. */
export function ClientsPage() {
  const { t, i18n } = useTranslation()
  const brands = useBrands()
  const shell = useShell()
  const [params, setParams] = useSearchParams()
  const spaceId = params.get('space') ? Number(params.get('space')) : null
  const bin = params.get('bin') === '1'
  const [query, setQuery] = useState('')
  useEffect(() => {
    if (bin) void brands.loadBin()
  }, [bin, brands.loadBin]) // eslint-disable-line react-hooks/exhaustive-deps
  const space = spaceId ? brands.space(spaceId) : undefined
  const list = useMemo(() => {
    const all = bin ? brands.bin : brands.clients
    const q = query.trim().toLocaleLowerCase()
    return all.filter((c) => (spaceId === null || c.space_id === spaceId) && (!q || c.name.toLocaleLowerCase().includes(q) || c.sector.toLocaleLowerCase().includes(q)))
  }, [bin, brands.bin, brands.clients, spaceId, query])
  const canWrite = space ? space.role === 'write' || space.role === 'manage' : brands.spaces.some((s) => s.role === 'write' || s.role === 'manage')
  return (
    <div className="flex min-h-0 flex-1">
      <Sidebar />
      <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-2xl font-bold tracking-tight">{bin ? t('clients.bin') : space ? space.name : t('clients.title')}</h1>
              <p className="mt-1 max-w-2xl text-sm text-mist-500">{bin ? t('clients.binText') : t('clients.text')}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex items-center gap-2 rounded-full border border-ink-700 bg-ink-900 px-3 py-1.5 text-sm">
                <Search className="h-4 w-4 text-mist-500" />
                <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t('clients.filter')} aria-label={t('clients.filter')} className="w-40 bg-transparent outline-none placeholder:text-mist-600" />
              </label>
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setParams(bin ? {} : { bin: '1' })}>
                {bin ? <RotateCcw className="h-4 w-4" /> : <Trash2 className="h-4 w-4" />} {bin ? t('clients.back') : t('clients.binOpen')}
              </button>
              {canWrite && !bin && (
                <button type="button" className="nc-btn nc-btn-accent" onClick={() => shell.newClient(spaceId ?? undefined)}>
                  <Plus className="h-4 w-4" /> {t('client.new')}
                </button>
              )}
            </div>
          </div>
          {brands.loaded && list.length === 0 && (
            <div className="rounded-2xl border border-dashed border-ink-700 p-10 text-center">
              <p className="text-mist-300">{bin ? t('clients.binEmpty') : query ? t('search.nothing') : t('clients.empty')}</p>
              {!bin && !query && canWrite && (
                <button type="button" className="nc-btn nc-btn-accent mt-4" onClick={() => shell.newClient(spaceId ?? undefined)}>
                  <Plus className="h-4 w-4" /> {t('client.new')}
                </button>
              )}
            </div>
          )}
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {list.map((c) => (bin ? <BinCard key={c.id} client={c} /> : <ClientCard key={c.id} client={c} spaceName={spaceId ? undefined : brands.space(c.space_id)?.name} locale={i18n.language} />))}
          </div>
        </div>
      </main>
    </div>
  )
}

function ClientCard({ client, spaceName, locale }: { client: ClientInfo; spaceName?: string; locale: string }) {
  const { t } = useTranslation()
  const logo = client.face.logo
  const ground = logo && logo.ground !== 'transparent' ? logo.ground : '#FFFFFF'
  return (
    <Link to={`/c/${client.id}`} className="group overflow-hidden rounded-2xl border border-ink-700 bg-ink-900 hover:border-ink-600">
      <div className="grid h-28 place-items-center px-6" style={{ background: logo ? ground : client.face.colors[0] ?? 'var(--color-ink-800)' }}>
        {logo ? <LogoView logo={logo} fonts={[]} fileUrl={(id) => mediaUrl(id, true)} className={logo.compact ? 'h-16' : 'h-12'} /> : <span className="text-3xl font-bold text-white/90">{client.name.trim()[0]?.toUpperCase()}</span>}
      </div>
      <div className="flex h-2">
        {client.face.colors.map((c, i) => (
          <span key={i} className="flex-1" style={{ background: c }} />
        ))}
      </div>
      <div className="space-y-1 p-4">
        <div className="flex items-center gap-2">
          <span className="mr-auto truncate font-semibold">{client.name}</span>
          {client.favorite && <Star className="h-4 w-4 shrink-0 text-accent-400" aria-label={t('client.favorite')} />}
          {client.current ? <span className="shrink-0 rounded-full border border-accent-500/40 px-2 py-0.5 text-[11px] text-accent-400">{t('client.versionLabel', { label: client.current })}</span> : <span className="shrink-0 rounded-full border border-magenta-500/50 px-2 py-0.5 text-[11px] text-magenta-text">{t('client.onlyDraft')}</span>}
        </div>
        <p className="truncate text-sm text-mist-500">{[client.sector, spaceName].filter(Boolean).join(' · ') || ' '}</p>
        <p className="flex items-center gap-3 text-xs text-mist-600">
          <span className="inline-flex items-center gap-1">
            <FolderKanban className="h-3.5 w-3.5" /> {t('client.projects', { count: client.projects })}
          </span>
          {client.drafts > 0 && <span>{t('client.drafts', { count: client.drafts })}</span>}
          <span className="ml-auto">{new Date(client.updated_at).toLocaleDateString(locale)}</span>
        </p>
      </div>
    </Link>
  )
}

function BinCard({ client }: { client: ClientInfo }) {
  const { t } = useTranslation()
  const brands = useBrands()
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-ink-700 bg-ink-900 p-4">
      <span className="min-w-0 flex-1 truncate font-semibold">{client.name}</span>
      <button type="button" className="nc-btn nc-btn-ghost" onClick={() => void clientsApi.restore(client.id).then(() => Promise.all([brands.refresh(), brands.loadBin()]))}>
        <RotateCcw className="h-4 w-4" /> {t('clients.restore')}
      </button>
      {client.role === 'manage' && (
        <button type="button" className="nc-btn nc-btn-ghost" onClick={() => window.confirm(t('clients.purgeAsk', { name: client.name })) && void clientsApi.purge(client.id).then(() => brands.loadBin())}>
          <Trash2 className="h-4 w-4" /> {t('clients.purge')}
        </button>
      )}
    </div>
  )
}
