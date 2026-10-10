/**
 * My account, Security, Sign-in providers (blueprint 04): one row per active provider with its state and "Link" or
 * "Unlink". Linking asks for the own password first and then goes to the provider; the way back lands on this page
 * with `?linked=<short name>`, said here by the provider's name. An account that signs in through a provider only
 * keeps its last link. Where the provider knows the account by another address, the row offers it (blueprint 01:
 * only an account through the provider only follows it by itself).
 */
import { Shield } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, oidcApi, type Me, type MyProvider } from '../api/client'
import { errorText } from '../lib/errors'
import { useAuth } from '../state/auth'
import { Section } from './Section'

const ROW_BUTTON = 'rounded-full border border-ink-700 px-3 py-1 text-xs hover:bg-ink-850 disabled:opacity-50'

function codeOf(error: unknown): string {
  return error instanceof ApiError ? error.code : 'internal_error'
}

export function MyProviders({ me, linked }: { me: Me; linked: string | null }) {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const [providers, setProviders] = useState<MyProvider[] | null>(null)
  const [linking, setLinking] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  const load = useCallback(async () => setProviders(await oidcApi.mine()), [])
  useEffect(() => {
    void load().catch(() => setProviders([]))
  }, [load])

  if (providers === null || (providers.length === 0 && me.sign_in !== 'oidc')) return null
  // Back from the provider: said by the name on the button, never the short name of the address.
  const backFrom = linked ? providers.find((entry) => entry.slug === linked) : undefined
  const linkedCount = providers.filter((entry) => entry.linked).length

  const run = async (work: () => Promise<unknown>, success: string) => {
    setBusy(true)
    setProblem(null)
    setDone(null)
    try {
      await work()
      await load()
      setDone(success)
    } catch (error) {
      setProblem(errorText(codeOf(error)))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section icon={Shield} title={t('oidc.account.title')}>
      <p className="mb-3 text-sm text-mist-400">{t('oidc.account.text')}</p>
      {backFrom && !done && (
        <p role="status" className="mb-3 text-sm text-ok-500">
          {t('me.oidc.linkedTo', { name: backFrom.label })}
        </p>
      )}
      <ul className="divide-y divide-ink-800 rounded-xl border border-ink-800" data-testid="my-providers">
        {providers.map((provider) => {
          const lastLink = me.sign_in === 'oidc' && provider.linked && linkedCount === 1
          return (
            <li key={provider.slug} className="px-3 py-2.5 text-sm">
              <div className="flex flex-wrap items-center gap-3">
                <span className="min-w-0 flex-1 truncate font-medium">{provider.label}</span>
                <span className={`rounded-full px-2 py-0.5 text-xs ${provider.linked ? 'bg-ok-500/10 text-ok-500' : 'border border-ink-700 text-mist-400'}`}>
                  {provider.linked ? t('oidc.account.linked') : t('oidc.account.notLinked')}
                </span>
                {provider.linked && !lastLink && (
                  <button
                    type="button"
                    disabled={busy}
                    className={ROW_BUTTON}
                    onClick={() => void run(() => oidcApi.unlink(provider.slug), t('me.oidc.unlinkedFrom', { name: provider.label }))}
                  >
                    {t('oidc.account.unlink')}
                  </button>
                )}
                {!provider.linked && me.sign_in === 'password' && linking !== provider.slug && (
                  <button
                    type="button"
                    disabled={busy}
                    className={ROW_BUTTON}
                    onClick={() => {
                      setLinking(provider.slug)
                      setPassword('')
                    }}
                  >
                    {t('oidc.account.link')}
                  </button>
                )}
              </div>
              {lastLink && <p className="mt-1 text-xs text-mist-500">{t('oidc.account.only', { name: provider.label })}</p>}
              {provider.linked && provider.address && me.sign_in === 'password' && (
                <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-mist-400">
                  <span className="min-w-0 flex-1">{t('me.oidc.addressOffer', { provider: provider.label, address: provider.address })}</span>
                  <button
                    type="button"
                    disabled={busy}
                    className={ROW_BUTTON}
                    onClick={() =>
                      void run(async () => {
                        await oidcApi.takeAddress(provider.slug)
                        await refresh()
                      }, t('me.oidc.addressTaken'))
                    }
                  >
                    {t('me.oidc.takeAddress')}
                  </button>
                </div>
              )}
              {linking === provider.slug && (
                <form
                  className="mt-3 flex flex-wrap items-end gap-2"
                  onSubmit={(event) => {
                    event.preventDefault()
                    setBusy(true)
                    setProblem(null)
                    oidcApi.link(provider.slug, password).then(
                      ({ url }) => window.location.assign(url),
                      (error) => {
                        setProblem(errorText(codeOf(error)))
                        setBusy(false)
                      },
                    )
                  }}
                >
                  <label className="min-w-48 flex-1 text-sm">
                    <span className="font-medium">{t('auth.password')}</span>
                    <input
                      type="password"
                      value={password}
                      autoComplete="current-password"
                      autoFocus
                      onChange={(event) => setPassword(event.target.value)}
                      className="mt-1 h-9 w-full rounded-lg border border-edge bg-ink-850 px-3 text-sm outline-none focus:border-accent-500"
                    />
                  </label>
                  <button type="submit" disabled={busy || !password} className={ROW_BUTTON}>
                    {t('oidc.account.link')}
                  </button>
                  <button type="button" disabled={busy} className="text-xs text-mist-500 hover:text-mist-300" onClick={() => setLinking(null)}>
                    {t('common.cancel')}
                  </button>
                </form>
              )}
            </li>
          )
        })}
      </ul>
      <div aria-live="polite" className="mt-2">
        {problem && (
          <p role="alert" className="text-sm text-bad-500">
            {problem}
          </p>
        )}
        {done && (
          <p role="status" className="text-sm text-ok-500">
            {done}
          </p>
        )}
      </div>
    </Section>
  )
}
