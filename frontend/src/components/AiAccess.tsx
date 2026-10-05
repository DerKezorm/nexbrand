/**
 * The own AI service on the account page (`services/ai.py`), as nexlore's: a tile fills in the address of a common
 * service (any other address is just as good), the key is typed once and never shown again, the model list is the test
 * that both are right, and the switch goes on only with a complete access. Below, what went out, word for word: the
 * proof of what left, shown as text and never rendered.
 *
 * When the operator has not allowed AI, it says so, and the operator gets the way to the switch.
 */
import { Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, aiApi, type AiEvent, type AiModel, type AiState } from '../api/client'
import { AI_PROVIDERS } from '../lib/aiProviders'
import { errorText } from '../lib/errors'
import { moment } from '../lib/time'
import { useAuth } from '../state/auth'
import { Section } from './Section'

const QUIET = 'rounded-full border border-ink-700 px-3 py-1 text-sm text-mist-200 hover:bg-ink-850 disabled:opacity-50'
const FIELD = 'mt-1 block h-9 w-full rounded-lg border border-ink-700 bg-ink-850 px-2 text-sm text-mist-100 outline-none focus:border-accent-500'

export function AiAccess() {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [state, setState] = useState<AiState | null>(null)
  const [url, setUrl] = useState('')
  const [key, setKey] = useState('')
  const [model, setModel] = useState('')
  const [models, setModels] = useState<AiModel[] | null>(null)
  const [events, setEvents] = useState<AiEvent[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)

  const take = (next: AiState) => {
    setState(next)
    setUrl(next.access.url)
    setModel(next.access.model)
    setKey('')
  }
  useEffect(() => {
    aiApi.state().then(take, () => setState(null))
  }, [])

  const act = async (work: () => Promise<void>) => {
    setBusy(true)
    setProblem(null)
    setDone(null)
    try {
      await work()
    } catch (error) {
      setProblem(error instanceof ApiError ? error.code : 'internal_error')
    } finally {
      setBusy(false)
    }
  }

  if (!state) return null
  if (!state.allowed)
    return (
      <Section icon={Sparkles} title={t('ai.title')} id="ai">
        <p className="text-sm text-mist-500" data-testid="ai-off">
          {t('ai.off')}{' '}
          {me?.role === 'operator' && (
            <Link to="/settings?tab=server&sub=outside" className="text-accent-400 hover:underline">
              {t('ai.offOperator')}
            </Link>
          )}
        </p>
      </Section>
    )

  const { access } = state
  const saved = access.url === url.trim() || access.url === `${url.trim()}/`
  const save = () =>
    act(async () => {
      const change: Parameters<typeof aiApi.save>[0] = { url: url.trim(), model: model.trim() }
      if (key.trim()) change.key = key.trim()
      take(await aiApi.save(change))
      setDone(t('ai.saved'))
    })

  return (
    <Section icon={Sparkles} title={t('ai.title')} id="ai">
      <p className="mb-4 text-sm text-mist-500">{t('ai.text')}</p>

      <div className="mb-3 flex flex-wrap gap-2" role="group" aria-label={t('ai.tiles')}>
        {AI_PROVIDERS.map((provider) => (
          <button
            key={provider.name}
            type="button"
            aria-pressed={url === provider.url}
            onClick={() => {
              setUrl(provider.url)
              setModels(null)
            }}
            className={'rounded-full border px-3 py-1 text-sm ' + (url === provider.url ? 'border-accent-500/60 bg-accent-500/10 text-mist-100' : 'border-ink-700 text-mist-300 hover:bg-ink-850')}
          >
            {provider.name}
          </button>
        ))}
      </div>
      {AI_PROVIDERS.filter((provider) => provider.url === url && provider.keys).map((provider) => (
        <p key={provider.name} className="mb-3 text-xs text-mist-500">
          <a href={provider.keys!} target="_blank" rel="noreferrer noopener" className="text-accent-400 hover:underline">
            {t('ai.getKey', { name: provider.name })}
          </a>
        </p>
      ))}

      <form
        className="grid gap-3 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault()
          void save()
        }}
      >
        <label className="block text-sm text-mist-300 sm:col-span-2">
          {t('ai.address')}
          <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://…/v1/" maxLength={500} className={FIELD + ' font-mono text-xs'} />
        </label>
        <label className="block text-sm text-mist-300">
          {t('ai.key')}
          <input
            type="password"
            value={key}
            onChange={(event) => setKey(event.target.value)}
            autoComplete="off"
            placeholder={access.key_set ? t('ai.keyKept') : t('ai.keyNone')}
            maxLength={1000}
            className={FIELD}
          />
        </label>
        <label className="block text-sm text-mist-300">
          {t('ai.model')}
          <input value={model} onChange={(event) => setModel(event.target.value)} list="ai-models" maxLength={200} className={FIELD} />
        </label>
        <datalist id="ai-models">
          {(models ?? []).map((item) => (
            <option key={item.id} value={item.id}>
              {item.name || item.id}
            </option>
          ))}
        </datalist>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
          <button
            type="button"
            disabled={busy || !url.trim()}
            onClick={() =>
              void act(async () => {
                const found = await aiApi.models(url.trim(), key.trim() || undefined)
                setModels(found)
                if (!model.trim() && found[0]) setModel(found[0].id)
                setDone(t('ai.modelsFound', { count: found.length }))
              })
            }
            className={QUIET}
          >
            {t('ai.loadModels')}
          </button>
          <button type="submit" disabled={busy} className="rounded-full bg-accent-500 px-3 py-1 text-sm font-semibold text-on-accent hover:bg-accent-400 disabled:opacity-50">
            {t('common.save')}
          </button>
        </div>
      </form>

      <label className="mt-4 flex items-start gap-3 rounded-xl border border-ink-700 p-3">
        <input
          type="checkbox"
          checked={access.active}
          disabled={busy || (!access.active && !(access.url && access.model && saved))}
          onChange={(event) => void act(async () => take(await aiApi.save({ active: event.target.checked })))}
          className="mt-1"
        />
        <span>
          <span className="block text-sm font-medium text-mist-100">{t('ai.switch')}</span>
          <span className="block text-xs text-mist-500">{access.url && access.model ? t('ai.switchHint') : t('ai.switchIncomplete')}</span>
        </span>
      </label>
      <p className="mt-3 text-xs text-mist-500">{t('ai.whereItGoes')}</p>

      <div aria-live="polite">
        {problem && (
          <p role="alert" className="mt-3 rounded-lg border border-bad-500/30 bg-bad-500/10 px-3 py-2 text-sm text-bad-500">
            {errorText(problem)}
          </p>
        )}
        {done && (
          <p role="status" className="mt-3 text-sm text-ok-500">
            {done}
          </p>
        )}
      </div>

      <details
        className="mt-4 rounded-xl border border-ink-700 px-3 py-2 text-sm"
        onToggle={(event) => {
          if ((event.currentTarget as HTMLDetailsElement).open && events === null) void aiApi.events().then(setEvents, () => setEvents([]))
        }}
      >
        <summary className="cursor-pointer text-mist-300">{t('ai.events')}</summary>
        <p className="mt-2 text-xs text-mist-500">{t('ai.eventsText')}</p>
        {events && events.length === 0 && <p className="mt-2 text-xs text-mist-500">{t('ai.eventsNone')}</p>}
        <ul className="mt-2 space-y-2" data-testid="ai-events">
          {(events ?? []).map((event) => (
            <li key={event.id} className="rounded-lg border border-ink-800 p-2 text-xs">
              <details>
                <summary className="cursor-pointer text-mist-300">
                  {moment(event.at, i18n.language)} · {t(`ai.tasks.${event.task}`)} · {event.model}
                  {event.error ? ` · ${errorText(event.error)}` : ` · ${t('ai.tokens', { in: event.tokens_in, out: event.tokens_out })}`}
                </summary>
                <pre className="nc-scroll mt-2 max-h-64 overflow-auto rounded-lg bg-ink-950 p-2 font-mono text-[11px] whitespace-pre-wrap text-mist-300">
                  {JSON.stringify(event.body, null, 2)}
                </pre>
              </details>
            </li>
          ))}
        </ul>
        {events && events.length > 0 && (
          <button
            type="button"
            onClick={() =>
              void act(async () => {
                await aiApi.clear()
                setEvents([])
              })
            }
            className="mt-2 text-xs text-bad-500 hover:underline"
          >
            {t('ai.clear')}
          </button>
        )}
      </details>
    </Section>
  )
}
