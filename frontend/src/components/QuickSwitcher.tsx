import { Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import type { ClientInfo } from '../api/client'
import { useBrands } from '../state/brands'
import { useShell } from './AppShell'
import { Swatch } from './Sidebar'

/** Ctrl K, as in nexlore: type, arrows, Enter. Finds clients by name and sector, and by the fonts they use. */
export function QuickSwitcher({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const brands = useBrands()
  const shell = useShell()
  const [query, setQuery] = useState('')
  const [index, setIndex] = useState(0)

  const hits = useMemo(() => {
    const q = query.trim().toLocaleLowerCase()
    if (!q) return [...brands.clients].filter((c) => c.opened_at).sort((a, b) => Date.parse(b.opened_at!) - Date.parse(a.opened_at!)).slice(0, 8)
    const found: ClientInfo[] = brands.clients.filter(
      (c) => c.name.toLocaleLowerCase().includes(q) || c.sector.toLocaleLowerCase().includes(q) || (c.face.fonts ?? []).some((f) => f.toLocaleLowerCase().includes(q)),
    )
    return found.slice(0, 12)
  }, [query, brands.clients])

  const rows = hits.length + 1
  const open = (i: number) => {
    onClose()
    if (i < hits.length) navigate(`/c/${hits[i].id}`)
    else shell.newClient()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-scrim p-4 pt-[12vh]" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-label={t('search.button')} className="w-full max-w-xl overflow-hidden rounded-2xl border border-ink-700 bg-ink-900 shadow-2xl shadow-black/50">
        <div className="flex items-center gap-3 border-b border-ink-700/70 px-4">
          <Search className="h-4 w-4 text-mist-500" />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setIndex(0)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') onClose()
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                setIndex((i) => (i + 1) % rows)
              }
              if (e.key === 'ArrowUp') {
                e.preventDefault()
                setIndex((i) => (i - 1 + rows) % rows)
              }
              if (e.key === 'Enter') open(index)
            }}
            placeholder={t('search.placeholder')}
            className="w-full bg-transparent py-3.5 text-sm text-mist-100 placeholder:text-mist-600 focus:outline-none"
          />
          <kbd>Esc</kbd>
        </div>
        <ul className="nc-scroll max-h-[50vh] overflow-y-auto p-1.5" role="listbox" aria-label={t('search.button')}>
          {!query && hits.length > 0 && <li className="px-3 pt-1.5 pb-1 text-[11px] font-semibold tracking-wider text-mist-600 uppercase">{t('sidebar.recent')}</li>}
          {hits.map((client, i) => {
            return (
              <li key={client.id} role="option" aria-selected={i === index}>
                <button
                  type="button"
                  onMouseEnter={() => setIndex(i)}
                  onClick={() => open(i)}
                  className={'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left ' + (i === index ? 'bg-accent-500/12 text-mist-100' : 'text-mist-300')}
                >
                  <Swatch client={client} className="h-4 w-4" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{client.name}</span>
                    {client.sector && <span className="block truncate text-xs text-mist-600">{client.sector}</span>}
                  </span>
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: client.color }} aria-hidden />
                </button>
              </li>
            )
          })}
          {query && hits.length === 0 && <li className="px-3 py-2 text-sm text-mist-600">{t('search.nothing')}</li>}
          <li role="option" aria-selected={index === hits.length}>
            <button
              type="button"
              onMouseEnter={() => setIndex(hits.length)}
              onClick={() => open(hits.length)}
              className={'flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm ' + (index === hits.length ? 'bg-accent-500/12 text-mist-100' : 'text-accent-400')}
            >
              <Plus className="h-4 w-4" />
              {t('client.new')}
            </button>
          </li>
        </ul>
      </div>
    </div>
  )
}
