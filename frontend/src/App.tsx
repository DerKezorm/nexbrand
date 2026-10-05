import { useEffect, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import { AppShell } from './components/AppShell'
import { AboutPage } from './pages/AboutPage'
import { AccountPage } from './pages/AccountPage'
import { InvitePage, LoginPage, SetupPage } from './pages/AuthPages'
import { ClientPage } from './pages/ClientPage'
import { ClientsPage } from './pages/ClientsPage'
import { CollectPage } from './pages/CollectPage'
import { ContrastPage } from './pages/ContrastPage'
import { NewClientPage } from './pages/NewClientPage'
import { PublicPage, ReviewPage } from './pages/PublicPages'
import { SettingsPage } from './pages/SettingsPage'
import { useAuth } from './state/auth'
import { BrandsProvider, useBrands } from './state/brands'

/** Everything behind the sign-in: without an account the page goes to the sign-in, and comes back after. An account
 * that still has to set up its second factor (the operator requires one) reaches its own account page only. */
function SignedIn({ children }: { children: ReactNode }) {
  const { status, me, ended } = useAuth()
  const location = useLocation()
  if (status === 'loading') return null
  if (status === 'setup') return <Navigate to="/setup" replace />
  if (status === 'signedOut') return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}${ended ? '&ended=1' : ''}`} replace />
  if (me?.second_factor_setup_required && location.pathname !== '/account') return <Navigate to="/account?tab=security" replace />
  return (
    <BrandsProvider>
      <StartAtLast />
      {children}
    </BrandsProvider>
  )
}

/** Once per visit: whoever chose "the client opened last" as their start page lands there instead of the overview. */
let started = false
function StartAtLast() {
  const { me } = useAuth()
  const { loaded, clients } = useBrands()
  const location = useLocation()
  const navigate = useNavigate()
  useEffect(() => {
    if (started || !loaded) return
    started = true
    if (location.pathname !== '/' || location.search || me?.preferences?.start !== 'last') return
    const last = clients.filter((c) => c.opened_at).sort((a, b) => Date.parse(b.opened_at!) - Date.parse(a.opened_at!))[0]
    if (last) navigate(`/c/${last.id}`, { replace: true })
  }, [loaded, clients, me, location, navigate])
  return null
}

export default function App() {
  return (
    <Routes>
      <Route path="setup" element={<SetupPage />} />
      <Route path="login" element={<LoginPage />} />
      <Route path="notzugang" element={<LoginPage emergency />} />
      <Route path="invite/:token" element={<InvitePage />} />
      <Route path="s/:token" element={<PublicPage />} />
      <Route path="r/:token" element={<ReviewPage />} />
      <Route
        element={
          <SignedIn>
            <AppShell />
          </SignedIn>
        }
      >
        <Route index element={<ClientsPage />} />
        <Route path="c/:id" element={<ClientPage />} />
        <Route path="c/:id/p/:pid" element={<ClientPage />} />
        <Route path="new" element={<NewClientPage />} />
        <Route path="collect" element={<CollectPage />} />
        <Route path="contrast" element={<ContrastPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="account" element={<AccountPage />} />
        <Route path="about" element={<AboutPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
