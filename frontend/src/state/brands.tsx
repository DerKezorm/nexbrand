/**
 * The clients as the overview knows them, from the server, and the group of rights behind each (who has access). One client with its versions and projects is
 * loaded by its page (`ClientPage`); what changes there is put back here, so the overview and the sidebar follow.
 *
 * The lists refresh when the tab comes back into view and every half minute, so clients others made show up.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { clientsApi, spacesApi, type ClientInfo, type SpaceInfo } from '../api/client'

export type Space = SpaceInfo

const REFRESH_MS = 30_000

interface Brands {
  loaded: boolean
  spaces: Space[]
  clients: ClientInfo[]
  bin: ClientInfo[]
  space: (id: number) => Space | undefined
  client: (id: string) => ClientInfo | undefined
  refresh: () => Promise<void>
  loadBin: () => Promise<void>
  /** A client's entry changed elsewhere (opened, renamed, published): put it in the list without a reload. */
  put: (client: ClientInfo) => void
}

const Context = createContext<Brands | null>(null)

export function BrandsProvider({ children }: { children: ReactNode }) {
  const [spaces, setSpaces] = useState<Space[]>([])
  const [clients, setClients] = useState<ClientInfo[]>([])
  const [bin, setBin] = useState<ClientInfo[]>([])
  const [loaded, setLoaded] = useState(false)
  const running = useRef<Promise<void> | null>(null)

  const refresh = useCallback(() => {
    if (running.current) return running.current
    running.current = (async () => {
      try {
        const [spaceList, clientList] = await Promise.all([spacesApi.list(), clientsApi.list()])
        setSpaces(spaceList)
        setClients(clientList)
        setLoaded(true)
      } finally {
        running.current = null
      }
    })()
    return running.current
  }, [])

  const loadBin = useCallback(async () => setBin(await clientsApi.list({ deleted: true })), [])

  useEffect(() => {
    void refresh().catch(() => undefined)
    const timer = window.setInterval(() => document.visibilityState === 'visible' && void refresh().catch(() => undefined), REFRESH_MS)
    const back = () => document.visibilityState === 'visible' && void refresh().catch(() => undefined)
    document.addEventListener('visibilitychange', back)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', back)
    }
  }, [refresh])

  const value = useMemo<Brands>(
    () => ({
      loaded,
      spaces,
      clients,
      bin,
      space: (id) => spaces.find((s) => s.id === id),
      client: (id) => clients.find((c) => c.id === id),
      refresh,
      loadBin,
      put: (client) =>
        setClients((all) => {
          const known = all.some((c) => c.id === client.id)
          if (client.deleted_at) return all.filter((c) => c.id !== client.id)
          return known ? all.map((c) => (c.id === client.id ? client : c)) : [...all, client]
        }),
    }),
    [loaded, spaces, clients, bin, refresh, loadBin],
  )
  return <Context.Provider value={value}>{children}</Context.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useBrands(): Brands {
  const value = useContext(Context)
  if (!value) throw new Error('BrandsProvider missing')
  return value
}
