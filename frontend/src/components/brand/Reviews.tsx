import { Eye, MessagesSquare, Send, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { reviewsApi, type ClientWhole, type ReviewComment, type ReviewInfo, type VersionInfo } from '../../api/client'
import { Button, CopyLink, Feedback, Input, Select, useAction } from '../../pages/settings/ui'
import { useAuth } from '../../state/auth'
import { useBrands } from '../../state/brands'
import { Dialog } from '../Dialog'

/** The reviews of a client, as the agency sees them: status, the link, every comment, an answer. */
/** `only`: the reviews of these versions (a client's own, or one project's). */
export function ReviewsPanel({ client, versions, only, canWrite, canManage, onChange }: { client: string; versions: VersionInfo[]; only?: string[]; canWrite: boolean; canManage: boolean; onChange: () => void }) {
  const { t, i18n } = useTranslation()
  const brands = useBrands()
  const [reviews, setReviews] = useState<ReviewInfo[]>([])
  // What was new when the panel opened stays marked while it is open; the server already counts it as seen.
  const [newSince, setNewSince] = useState<Record<number, string>>({})
  const key = only?.join(',')
  const load = useCallback(() => void reviewsApi.list(client).then((all) => setReviews(key === undefined ? all : all.filter((r) => key.split(',').includes(r.version_id)))).catch(() => setReviews([])), [client, key])
  useEffect(load, [load])
  // Each review is marked seen once per news: the refresh after it changes `brands` and would mark it again, round
  // and round.
  const marked = useRef(new Set<string>())
  useEffect(() => {
    const fresh = reviews.filter((r) => r.news > 0 && !marked.current.has(`${r.id}:${r.comments.length}:${r.status}`))
    if (!fresh.length) return
    fresh.forEach((r) => marked.current.add(`${r.id}:${r.comments.length}:${r.status}`))
    setNewSince((was) => ({ ...was, ...Object.fromEntries(fresh.map((r) => [r.id, r.seen_at ?? ''])) }))
    void Promise.all(fresh.map((r) => reviewsApi.seen(client, r.id)))
      .then(() => (onChange(), void brands.refresh()))
      .catch(() => undefined)
  }, [reviews, client, onChange, brands])
  if (!reviews.length) return <p className="text-sm text-mist-500">{t('reviews.none')}</p>
  return (
    <div className="space-y-4">
      {reviews.map((r) => (
        <ReviewCard key={r.id} client={client} review={r} newSince={newSince[r.id]} version={versions.find((v) => v.id === r.version_id)} canWrite={canWrite} canManage={canManage} locale={i18n.language} onChange={() => (load(), onChange())} />
      ))}
    </div>
  )
}

function ReviewCard({ client, review, newSince, version, canWrite, canManage, locale, onChange }: { client: string; review: ReviewInfo; newSince?: string; version?: VersionInfo; canWrite: boolean; canManage: boolean; locale: string; onChange: () => void }) {
  const { t } = useTranslation()
  const [answer, setAnswer] = useState<Record<string, string>>({})
  const tone = review.status === 'open' ? 'border-magenta-500/50 text-magenta-text' : review.status === 'chosen' ? 'border-ok-500/40 text-ok-500' : 'border-ink-700 text-mist-500'
  const chosen = review.variants.find((v) => v.id === review.chosen)
  // Marked new: from the client, after the last look before this panel opened (none before: all of them).
  const isNew = (c: ReviewComment) => newSince !== undefined && !c.agency && (!newSince || c.at > newSince)
  return (
    <article className="space-y-3 rounded-2xl border border-ink-700 bg-ink-900 p-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <MessagesSquare className="h-4 w-4 text-accent-400" />
        <b className="mr-auto">
          {version?.label ?? review.label} → {review.label}
        </b>
        <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + tone}>{t(`reviews.status.${review.status}`)}</span>
        <span className="text-xs text-mist-500">{new Date(review.created_at).toLocaleDateString(locale)}</span>
        {review.status === 'open' && (
          <a href={new URL(review.link).pathname} target="_blank" rel="noreferrer" className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs">
            <Eye className="h-3.5 w-3.5" /> {t('reviews.asClient')}
          </a>
        )}
        {review.status === 'open' && canManage && (
          <button type="button" className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs" onClick={() => window.confirm(t('reviews.withdrawAsk')) && void reviewsApi.withdraw(client, review.id).then(onChange)}>
            <Undo2 className="h-3.5 w-3.5" /> {t('reviews.withdraw')}
          </button>
        )}
      </div>
      {review.status === 'open' && <CopyLink value={review.link} label={t('reviews.link')} />}
      {chosen && <p className="rounded-xl border border-ok-500/30 bg-ok-500/8 px-3 py-2 text-sm text-mist-200">{t('reviews.chosen', { label: chosen.label, who: review.chosen_by || t('reviews.theClient') })}</p>}
      <div className="grid gap-3 md:grid-cols-2">
        {review.variants.map((v) => (
          <section key={v.id} className="rounded-xl border border-ink-700 bg-ink-850 p-3">
            <div className="flex items-center gap-2">
              <span className="font-semibold">{v.label}</span>
              <span className="ml-auto flex overflow-hidden rounded border border-ink-700">
                {v.data.colors.slice(0, 6).map((c, i) => (
                  <span key={i} className="h-4 w-4" style={{ background: c.hex }} />
                ))}
              </span>
            </div>
            <ul className="mt-2 space-y-1.5">
              {review.comments
                .filter((c) => c.variant === v.id)
                .map((c, i) => (
                  <li key={i} className={'rounded-lg px-2.5 py-1.5 text-sm ' + (c.agency ? 'bg-accent-500/10' : 'bg-ink-900') + (isNew(c) ? ' ring-1 ring-magenta-500/60' : '')}>
                    <span className="text-xs font-semibold text-mist-300">{c.author}</span> <span className="text-[11px] text-mist-600">{new Date(c.at).toLocaleString(locale)}</span>
                    {isNew(c) && <span className="ml-1.5 rounded-full bg-magenta-500 px-1.5 text-[10px] font-semibold text-white">{t('reviews.new')}</span>}
                    {c.sample && <span className="ml-1.5 text-[11px] text-mist-500">{t('reviews.onSample', { name: v.data.samples.find((x) => x.media === c.sample)?.name ?? '' })}</span>}
                    <p className="whitespace-pre-line text-mist-200">{c.text}</p>
                  </li>
                ))}
            </ul>
            {review.status === 'open' && canWrite && (
              <form
                className="mt-2 flex gap-2"
                onSubmit={(e) => {
                  e.preventDefault()
                  const text = (answer[v.id] ?? '').trim()
                  if (text) void reviewsApi.comment(client, review.id, v.id, text).then(() => (setAnswer({ ...answer, [v.id]: '' }), onChange()))
                }}
              >
                <input value={answer[v.id] ?? ''} onChange={(e) => setAnswer({ ...answer, [v.id]: e.target.value })} placeholder={t('reviews.answer')} aria-label={t('reviews.answerOn', { label: v.label })} className="h-9 min-w-0 flex-1 rounded-lg border border-ink-700 bg-ink-900 px-3 text-sm" />
                <button type="submit" className="nc-btn nc-btn-ghost">
                  <Send className="h-4 w-4" />
                </button>
              </form>
            )}
          </section>
        ))}
      </div>
    </article>
  )
}

/** Putting a draft before the client: its name once chosen, who sends it, a few words, and other drafts to compare. */
/** `versions`: a project's (as stored: what is its own; the server shows them on the client version they stand on). */
export function NewReview({ whole, version, versions = whole.versions, onClose, onMade }: { whole: ClientWhole; version: VersionInfo; versions?: VersionInfo[]; onClose: () => void; onMade: () => void }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  const others = versions.filter((v) => v.status === 'draft' && v.id !== version.id)
  const published = versions.filter((v) => v.status === 'published')
  const [label, setLabel] = useState(published.length ? version.label : '1.0')
  const [sender, setSender] = useState(me?.display_name || me?.name || '')
  const [message, setMessage] = useState('')
  const [days, setDays] = useState('30')
  const [along, setAlong] = useState<Record<string, boolean>>({})
  const [why, setWhy] = useState<Record<string, string>>({})
  const { busy, problem, run } = useAction()
  const variants = [version, ...others.filter((o) => along[o.id])].map((v, i) => ({ id: String.fromCharCode(97 + i), label: v.label, why: why[v.id] ?? v.note ?? '', data: v.data }))
  return (
    <Dialog title={t('reviews.new')} onClose={onClose} wide>
      <div className="space-y-3">
        <p className="text-sm text-mist-400">{t('reviews.newText')}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Input label={t('reviews.label')} value={label} onChange={setLabel} hint={t('reviews.labelHint')} />
          <Input label={t('reviews.sender')} value={sender} onChange={setSender} />
        </div>
        <label className="block text-sm">
          <span className="text-xs font-medium text-mist-400">{t('reviews.message')}</span>
          <textarea value={message} onChange={(e) => setMessage(e.target.value)} rows={3} placeholder={t('reviews.messageHint')} className="mt-1 w-full rounded-lg border border-ink-700 bg-ink-850 px-3 py-2 text-sm" />
        </label>
        <div className="space-y-2">
          <span className="text-xs font-medium text-mist-400">{t('reviews.directions')}</span>
          {[version, ...others].map((v) => (
            <div key={v.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 p-3 text-sm">
              <input type="checkbox" checked={v.id === version.id || !!along[v.id]} disabled={v.id === version.id} onChange={(e) => setAlong({ ...along, [v.id]: e.target.checked })} className="accent-accent-500" aria-label={v.label} />
              <b>{v.label}</b>
              <span className="flex overflow-hidden rounded border border-ink-700">
                {v.data.colors.slice(0, 6).map((c, i) => (
                  <span key={i} className="h-5 w-4" style={{ background: c.hex }} />
                ))}
              </span>
              <input value={why[v.id] ?? v.note ?? ''} onChange={(e) => setWhy({ ...why, [v.id]: e.target.value })} placeholder={t('reviews.why')} aria-label={t('reviews.why')} className="h-8 min-w-0 flex-1 rounded-lg border border-ink-700 bg-ink-850 px-2 text-sm" />
            </div>
          ))}
          {!others.length && <p className="text-xs text-mist-500">{t('reviews.onlyOne')}</p>}
        </div>
        <Select
          label={t('reviews.runs')}
          value={days}
          onChange={setDays}
          options={['7', '14', '30', '90'].map((d) => ({ value: d, label: t('shares.days', { count: Number(d) }) }))}
        />
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} disabled={!label.trim()} onClick={() => void run(async () => (await reviewsApi.create(whole.id, { version_id: version.id, variants, label, sender, message, days: Number(days) }), onMade()))}>
            <Send className="h-4 w-4" /> {t('reviews.make')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
