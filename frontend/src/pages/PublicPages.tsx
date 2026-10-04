/** The two pages for people outside: a public page of a design set (/s/…) and a review for the client (/r/…).
 * Neither needs an account; neither shows the agency's app around it. */
import { CircleCheck, Lock, MessageSquare, Send } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router-dom'

import { ApiError, pageMediaUrl, reviewsApi, sharesApi, type PublicPageInfo, type ReviewPageInfo } from '../api/client'
import { LogoView } from '../components/brand/LogoView'
import { SetView } from '../components/brand/SetView'
import { SampleGallery } from '../components/brand/SampleGallery'
import { SchemeSwitch } from '../components/brand/SchemeSwitch'
import { WebPreview } from '../components/brand/WebPreview'
import { Dialog } from '../components/Dialog'
import { Logo } from '../components/Logo'
import { schemeOf } from '../lib/brand'
import { textOn } from '../lib/color'
import { errorText } from '../lib/errors'
import { fontStack } from '../lib/fonts'

function Footer() {
  const { t } = useTranslation()
  return (
    <footer className="flex items-center justify-center gap-2 py-8 text-xs text-mist-600">
      <Logo className="h-4 w-4" /> {t('public.madeWith')}
    </footer>
  )
}

export function PublicPage() {
  const { token = '' } = useParams()
  const { t, i18n } = useTranslation()
  const [page, setPage] = useState<PublicPageInfo | null>(null)
  const [gone, setGone] = useState(false)
  const [password, setPassword] = useState('')
  const [problem, setProblem] = useState<string | null>(null)
  useEffect(() => {
    sharesApi.page(token).then(setPage).catch(() => setGone(true))
  }, [token])
  const fileUrl = useCallback((id: string) => pageMediaUrl('public', token, id), [token])
  if (gone) return <p className="p-10 text-center text-mist-400">{t('public.gone')}</p>
  if (!page) return <main aria-busy="true" />
  if (page.password)
    return (
      <main className="mx-auto max-w-sm px-4 py-20">
        <form
          className="space-y-3 rounded-2xl border border-ink-700 bg-ink-900 p-6"
          onSubmit={(e) => {
            e.preventDefault()
            sharesApi
              .unlock(token, password)
              .then(setPage)
              .catch((error) => setProblem(error instanceof ApiError ? error.code : 'internal_error'))
          }}
        >
          <h1 className="flex items-center gap-2 font-semibold">
            <Lock className="h-4 w-4" /> {t('public.guarded')}
          </h1>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} className="nc-field" aria-label={t('public.password')} autoFocus />
          {problem && <p className="text-sm text-bad-500">{errorText(problem)}</p>}
          <button type="submit" className="nc-btn nc-btn-accent w-full">
            {t('public.open')}
          </button>
        </form>
      </main>
    )
  const logo = page.design.logos.find((l) => !l.compact) ?? page.design.logos[0]
  return (
    <div className="min-h-dvh">
      <header className={'grid place-items-center px-6 py-14 ' + (logo?.ground === 'transparent' ? 'nb-checker' : '')} style={{ background: logo && logo.ground !== 'transparent' ? logo.ground : '#FFFFFF' }}>
        {logo ? <LogoView logo={logo} fonts={page.design.fonts} fileUrl={fileUrl} className="h-20" /> : <span className="text-4xl font-bold text-black">{page.client}</span>}
      </header>
      <main className="mx-auto max-w-6xl space-y-5 px-4 py-8">
        <div>
          <h1 className="text-2xl font-bold">{t('public.title', { name: page.client })}</h1>
          <p className="text-sm text-mist-500">
            {t('public.version', { label: page.version.label, from: new Date(page.version.valid_from).toLocaleDateString(i18n.language) })}
            {page.label && <> · {t('public.for', { label: page.label })}</>}
          </p>
        </div>
        <SetView set={page.design} fileUrl={fileUrl} files={page.files} publicMode />
      </main>
      <Footer />
    </div>
  )
}

export function ReviewPage() {
  const { token = '' } = useParams()
  const { t, i18n } = useTranslation()
  const [page, setPage] = useState<ReviewPageInfo | null>(null)
  const [gone, setGone] = useState(false)
  const [author, setAuthor] = useState(() => {
    try {
      return localStorage.getItem('nexbrand.reviewer') ?? ''
    } catch {
      return ''
    }
  })
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  // Per direction: the example shown, and whether a comment is about it (on by default) or the direction as a whole.
  const [at, setAt] = useState<Record<string, number>>({})
  const [general, setGeneral] = useState<Record<string, boolean>>({})
  const [dark, setDark] = useState<Record<string, boolean>>({})
  const [confirm, setConfirm] = useState<string | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  useEffect(() => {
    reviewsApi.page(token).then(setPage).catch(() => setGone(true))
  }, [token])
  const remember = (name: string) => {
    setAuthor(name)
    try {
      localStorage.setItem('nexbrand.reviewer', name)
    } catch {
      // private mode
    }
  }
  const fileUrl = useCallback((id: string) => pageMediaUrl('review', token, id), [token])
  const fail = (error: unknown) => setProblem(error instanceof ApiError ? error.code : 'internal_error')
  if (gone) return <p className="p-10 text-center text-mist-400">{t('public.reviewGone')}</p>
  if (!page) return <main aria-busy="true" />
  const chosen = page.variants.find((v) => v.id === page.chosen)
  return (
    <div className="min-h-dvh">
      <main className="mx-auto max-w-6xl space-y-6 px-4 py-8">
        <div>
          {page.sender && <div className="text-sm text-mist-500">{t('review.from', { sender: page.sender })}</div>}
          <h1 className="text-3xl font-bold tracking-tight">{t('review.title', { name: page.client })}</h1>
          <p className="mt-1 max-w-2xl text-mist-400">{page.variants.length > 1 ? t('review.textMany', { count: page.variants.length }) : t('review.textOne')}</p>
          {page.message && <p className="mt-3 max-w-2xl rounded-xl border border-ink-700 bg-ink-900 px-4 py-3 whitespace-pre-line text-mist-200">{page.message}</p>}
        </div>
        {chosen && (
          <div className="flex items-center gap-3 rounded-2xl border border-ok-500/40 bg-ok-500/8 px-5 py-4" role="status">
            <CircleCheck className="h-5 w-5 text-ok-500" />
            <span>{t('review.thanks', { label: chosen.label })}</span>
          </div>
        )}
        {page.status === 'open' && (
          <label className="block max-w-xs text-sm">
            <span className="text-xs font-medium text-mist-400">{t('review.yourName')}</span>
            <input value={author} onChange={(e) => remember(e.target.value)} className="nc-field mt-1" />
          </label>
        )}
        {problem && <p role="alert" className="text-sm text-bad-500">{errorText(problem)}</p>}
        {/* Two directions side by side only while there are no designs of the agency's own: those want the width. */}
        <div className={'grid gap-5 ' + (page.variants.length > 1 && page.variants.every((v) => !v.data.samples.length) ? 'lg:grid-cols-2' : '')}>
          {page.variants.map((v) => {
            const logo = v.data.logos.find((l) => !l.compact)
            const comments = page.comments.filter((c) => c.variant === v.id)
            const samples = v.data.samples
            const index = Math.min(at[v.id] ?? 0, Math.max(samples.length - 1, 0))
            const sample = samples[index]
            const aboutSample = !!sample && !general[v.id]
            const scheme = schemeOf(v.data.dark, v.data.colors)
            const counts: Record<string, number> = {}
            for (const c of comments) if (c.sample) counts[c.sample] = (counts[c.sample] ?? 0) + 1
            return (
              <article key={v.id} className={'space-y-3 rounded-2xl border bg-ink-900 p-4 ' + (page.chosen === v.id ? 'border-ok-500' : 'border-ink-700')}>
                <div className="flex items-baseline justify-between gap-2">
                  <h2 className="text-lg font-semibold">{v.label}</h2>
                  <span className="text-xs text-mist-500">{v.data.fonts.map((f) => f.family).join(' / ')}</span>
                </div>
                {samples.length > 0 && <SampleGallery samples={samples} files={page.files} fileUrl={fileUrl} index={index} onIndex={(i) => setAt({ ...at, [v.id]: i })} counts={counts} />}
                {(samples.length > 0 || scheme) && (
                  <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
                    {samples.length > 0 && <h3 className="text-sm font-semibold text-mist-300">{t('review.samplePage')}</h3>}
                    {scheme && <SchemeSwitch dark={!!dark[v.id]} onChange={(on) => setDark({ ...dark, [v.id]: on })} />}
                  </div>
                )}
                <WebPreview colors={v.data.colors} head={fontStack(v.data.fonts[0], fileUrl)} body={fontStack(v.data.fonts[1] ?? v.data.fonts[0], fileUrl)} name={page.client} logo={logo} logos={v.data.logos} fonts={v.data.fonts} fileUrl={fileUrl} scheme={dark[v.id] ? scheme : null} />
                <div className="flex flex-wrap gap-1.5">
                  {v.data.colors.map((c) => (
                    <span key={c.name} className="flex h-12 min-w-16 flex-1 items-end rounded-lg border border-ink-700 p-1 text-[10px]" style={{ background: c.hex, color: textOn(c.hex) }}>
                      {c.name}
                    </span>
                  ))}
                </div>
                {v.why && <p className="text-sm text-mist-400">{v.why}</p>}
                <ul className="space-y-2">
                  {comments.map((c, i) => (
                    <li key={i} className={'rounded-xl px-3 py-2 text-sm ' + (c.agency ? 'bg-accent-500/10' : 'bg-ink-850')}>
                      <span className="text-xs font-semibold text-mist-300">{c.author}</span> <span className="text-[11px] text-mist-600">{new Date(c.at).toLocaleString(i18n.language)}</span>
                      {c.sample && samples.some((x) => x.media === c.sample) && (
                        <button type="button" className="ml-1.5 text-[11px] text-accent-400 hover:underline" onClick={() => setAt({ ...at, [v.id]: samples.findIndex((x) => x.media === c.sample) })}>
                          {t('review.onSample', { name: samples.find((x) => x.media === c.sample)?.name ?? '' })}
                        </button>
                      )}
                      <p className="whitespace-pre-line text-mist-200">{c.text}</p>
                    </li>
                  ))}
                </ul>
                {page.status === 'open' && (
                  <>
                    <form
                      className="flex gap-2"
                      onSubmit={(e) => {
                        e.preventDefault()
                        const text = (drafts[v.id] ?? '').trim()
                        if (!text) return
                        reviewsApi
                          .say(token, v.id, author, text, aboutSample ? sample.media : undefined)
                          .then((p) => (setPage(p), setDrafts({ ...drafts, [v.id]: '' }), setProblem(null)))
                          .catch(fail)
                      }}
                    >
                      <input value={drafts[v.id] ?? ''} onChange={(e) => setDrafts({ ...drafts, [v.id]: e.target.value })} placeholder={aboutSample ? t('review.sayOnSample', { name: sample.name }) : t('review.say')} aria-label={t('review.sayOn', { label: v.label })} className="h-9 min-w-0 flex-1 rounded-lg border border-ink-700 bg-ink-850 px-3 text-sm" />
                      <button type="submit" className="nc-btn nc-btn-ghost">
                        <MessageSquare className="h-4 w-4" /> {t('review.send')}
                      </button>
                    </form>
                    {sample && (
                      <label className="flex items-center gap-2 text-xs text-mist-400">
                        <input type="checkbox" checked={!general[v.id]} onChange={(e) => setGeneral({ ...general, [v.id]: !e.target.checked })} />
                        {t('review.aboutThis', { name: sample.name })}
                      </label>
                    )}
                    <button type="button" className="nc-btn nc-btn-accent" onClick={() => setConfirm(v.id)}>
                      <Send className="h-4 w-4" /> {t('review.choose')}
                    </button>
                  </>
                )}
              </article>
            )
          })}
        </div>
      </main>
      <Footer />
      {confirm && (
        <Dialog title={t('review.chooseTitle')} onClose={() => setConfirm(null)}>
          <p className="text-sm text-mist-300">{t('review.chooseText')}</p>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setConfirm(null)}>
              {t('review.notYet')}
            </button>
            <button
              type="button"
              className="nc-btn nc-btn-accent"
              onClick={() =>
                reviewsApi
                  .choose(token, confirm, author)
                  .then((p) => (setPage(p), setConfirm(null)))
                  .catch((error) => (fail(error), setConfirm(null)))
              }
            >
              {t('review.yes')}
            </button>
          </div>
        </Dialog>
      )}
    </div>
  )
}
