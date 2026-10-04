import { Contrast, LayoutGrid, Plus, Search, Wand2 } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'

import { useBrands } from '../state/brands'
import { AccountMenu } from './AccountMenu'
import { Logo } from './Logo'
import { NewSpaceDialog } from './NewSpaceDialog'
import { QuickSwitcher } from './QuickSwitcher'
import { ThemeSwitcher } from './ThemeSwitcher'
import { WhatsNewBanner } from './WhatsNew'

interface Shell {
  /** The workbench for a new client, in a space when one is given. */
  newClient: (space?: number) => void
  newSpace: () => void
  search: () => void
}

const ShellContext = createContext<Shell>({ newClient: () => undefined, newSpace: () => undefined, search: () => undefined })

// eslint-disable-next-line react-refresh/only-export-components
export function useShell(): Shell {
  return useContext(ShellContext)
}

function navClass(isActive: boolean): string {
  return (
    'inline-flex shrink-0 items-center gap-2 rounded-full px-2.5 py-1.5 text-sm font-medium transition-colors sm:px-3.5 ' +
    (isActive ? 'bg-accent-500/15 text-accent-400' : 'text-mist-500 hover:bg-ink-850 hover:text-mist-100')
  )
}

/** The frame from nexlore: header with menu, new, search, light/dark and the account; the page below. */
export function AppShell() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const brands = useBrands()
  const [searching, setSearching] = useState(false)
  const [spaceDialog, setSpaceDialog] = useState(false)

  const newClient = useCallback((space?: number) => navigate(space ? `/new?space=${space}` : '/new'), [navigate])
  const newSpace = useCallback(() => setSpaceDialog(true), [])
  const search = useCallback(() => setSearching(true), [])
  const shell = useMemo(() => ({ newClient, newSpace, search }), [newClient, newSpace, search])

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearching(true)
      }
      if (e.altKey && e.key.toLowerCase() === 'n') {
        e.preventDefault()
        newClient()
      }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [newClient])

  const items = [
    { to: '/', label: 'nav.clients', Icon: LayoutGrid, end: true },
    { to: '/collect', label: 'nav.collect', Icon: Wand2 },
    { to: '/contrast', label: 'nav.contrast', Icon: Contrast },
  ]

  return (
    <ShellContext.Provider value={shell}>
      <div className="flex h-dvh flex-col overflow-hidden">
        <header className="z-20 shrink-0 border-b border-ink-700/80 bg-ink-950/80 backdrop-blur-xl">
          <div className="flex items-center gap-2 px-3 py-2.5 sm:gap-4 sm:px-4">
            <NavLink to="/" className="hidden shrink-0 sm:block" aria-label={t('app.home')}>
              <Logo withWordmark />
            </NavLink>
            <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto" aria-label={t('app.mainMenu')}>
              {items.map(({ to, label, Icon, end }) => (
                <NavLink key={to} to={to} end={end} className={({ isActive }) => navClass(isActive)} aria-label={t(label)}>
                  <Icon className="h-4 w-4" strokeWidth={1.8} />
                  <span className="hidden lg:inline">{t(label)}</span>
                </NavLink>
              ))}
            </nav>
            <button type="button" onClick={() => newClient()} className="inline-flex shrink-0 items-center gap-2 rounded-full bg-accent-500 px-3 py-1.5 text-sm font-semibold text-on-accent hover:bg-accent-400" title={t('client.newShortcut')}>
              <Plus className="h-4 w-4" strokeWidth={2.2} />
              <span className="hidden sm:inline">{t('client.new')}</span>
            </button>
            <button type="button" onClick={() => setSearching(true)} className="inline-flex shrink-0 items-center gap-2 rounded-full border border-ink-700 bg-ink-850 px-2 py-1.5 text-sm text-mist-500 hover:text-mist-100 xl:pr-2 xl:pl-3" aria-label={t('search.button')}>
              <Search className="h-4 w-4" strokeWidth={1.8} />
              <span className="hidden w-32 text-left xl:inline">{t('search.button')}</span>
              <kbd className="hidden xl:inline">Ctrl K</kbd>
            </button>
            <div className="hidden sm:block">
              <ThemeSwitcher />
            </div>
            <AccountMenu />
          </div>
        </header>
        <WhatsNewBanner />
        <div className="flex min-h-0 flex-1">
          <Outlet />
        </div>
      </div>
      {spaceDialog && (
        <NewSpaceDialog
          onClose={() => setSpaceDialog(false)}
          onCreate={async (name, color) => {
            const made = await brands.createSpace(name, color)
            setSpaceDialog(false)
            navigate(`/?space=${made.id}`)
          }}
        />
      )}
      {searching && <QuickSwitcher onClose={() => setSearching(false)} />}
    </ShellContext.Provider>
  )
}
