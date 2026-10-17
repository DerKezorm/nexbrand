/** One client, or one of its projects: its versions on a time line, the one chosen shown or (a draft) edited,
 * projects, history, public pages and reviews. A project's parts come from the client version it stands on, its
 * own, or both (`lib/inherit.ts`); the page shows what that makes, and the editor where each part comes from. */
import { ArrowRight, ArrowUpCircle, CalendarClock, Copy, Download, FilePlus2, FolderKanban, GitCompare, Globe, History, MessagesSquare, Pencil, Plus, Send, Sparkles, Star, Trash2, Upload, Users, UsersRound, Wand2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { ApiError, clientsApi, mediaUrl, type ClientLink, type ClientWhole, type MediaInfo, type ProjectWhole, type VersionInfo } from '../api/client'
import { DiffView } from '../components/brand/DiffView'
import { ExportDialog } from '../components/brand/ExportDialog'
import { ClientMark } from '../components/brand/LogoView'
import { ReviewsPanel, NewReview } from '../components/brand/Reviews'
import { SetEditor, type FileMap } from '../components/brand/SetEditor'
import { SetView } from '../components/brand/SetView'
import { SharesPanel } from '../components/brand/SharesPanel'
import { Dialog } from '../components/Dialog'
import { MembersDialog } from '../components/MembersDialog'
import { TeamRightsDialog } from '../components/Teams'
import { textOn } from '../lib/color'
import { CLIENT_COLORS } from '../lib/palette'
import { emptySet, type BrandSet } from '../lib/brand'
import { INHERIT_PARTS, modesOf, type Modes } from '../lib/inherit'
import { placeOf, type Place } from '../lib/where'
import { UiElements } from '../components/brand/UiElements'
import { Button, Confirm, Feedback, Input, Select, useAction } from './settings/ui'
import { useTitle } from '../lib/title'
import { useBrands } from '../state/brands'

/** A value the server refused, with the item and field it is in. */
function placeText(t: TFunction, place: Place): string {
  const what = t(`where.part.${place.part}`, { defaultValue: place.part })
  const name = place.name ? t('where.named', { what, name: place.name }) : place.index !== null ? t('where.numbered', { what, n: place.index + 1 }) : what
  if (place.twice) return t('where.twice', { name: place.name })
  if (!place.field) return t('where.at', { place: name })
  const field = place.part === 'dark' ? t(`dark.part.${place.field}`, { defaultValue: place.field }) : t(`diff.field.${place.field}`, { defaultValue: place.field })
  return t('where.field', { place: name, field })
}

const ORIGIN_TONE = { hand: 'border-ink-700 text-mist-500', collect: 'border-gelb-500/50 text-gelb-text', mcp: 'border-magenta-500/50 text-magenta-text', review: 'border-ok-500/40 text-ok-500' }

export function ClientPage() {
  const { id = '', pid } = useParams()
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const brands = useBrands()
  const [params, setParams] = useSearchParams()
  const [whole, setWhole] = useState<ClientWhole | null>(null)
  const [project, setProject] = useState<ProjectWhole | null>(null)
  const [modes, setModes] = useState<Modes | null>(null)
  const [missing, setMissing] = useState(false)
  const [projectMissing, setProjectMissing] = useState(false)
  const [noneThen, setNoneThen] = useState<string | null>(null)
  const [files, setFiles] = useState<FileMap>({})
  const [draft, setDraft] = useState<BrandSet | null>(null)
  const [dirty, setDirty] = useState(false)
  const [dialog, setDialog] = useState<'edit' | 'version' | 'publish' | 'export' | 'review' | 'trash' | 'deleteDraft' | 'lift' | 'leave' | null>(null)
  const save = useAction()
  const [refused, setRefused] = useState<Place | null>(null)
  useTitle(project ? `${project.name}, ${whole?.name ?? ''}` : whole?.name)

  const load = useCallback(async () => {
    try {
      // A project that is not there (deleted, a link typed wrong) is said as such, under its client.
      const asked = pid
        ? clientsApi.project(id, pid).catch((error: unknown) => {
            if (error instanceof ApiError && (error.status === 404 || error.status === 422)) return 'missing' as const
            throw error
          })
        : Promise.resolve(null)
      const [client, known, made] = await Promise.all([clientsApi.read(id), clientsApi.files(id), asked])
      setWhole(client)
      setProjectMissing(made === 'missing')
      setProject(made === 'missing' ? null : made)
      setFiles((before) => ({ ...before, ...known }))
      return client
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) setMissing(true)
      return null
    }
  }, [id, pid])

  useEffect(() => {
    setWhole(null)
    setProject(null)
    setMissing(false)
    setProjectMissing(false)
    setDraft(null)
    setDirty(false)
    void load()
    void clientsApi.visit(id).catch(() => undefined)
  }, [id, pid, load])

  // A project's versions are shown as they look (resolved); edited as what is their own.
  const versions: VersionInfo[] = useMemo(() => (pid ? (project?.versions ?? []).map((v) => ({ ...v, data: v.resolved })) : (whole?.versions ?? [])), [pid, project, whole])
  const published = versions.filter((v) => v.status === 'published')
  // The one that holds today, as the server says: a version published to hold from a later day is not it yet.
  const currentId = pid ? project?.current_id : whole?.current_id
  const current = published.find((v) => v.id === currentId)
  const chosenId = params.get('v')
  const shown = versions.find((v) => v.id === chosenId) ?? current ?? versions[0]
  const editing = shown?.status === 'draft' && params.get('edit') === '1' && (whole?.role === 'write' || whole?.role === 'manage')
  const canWrite = whole?.role === 'write' || whole?.role === 'manage'

  const own = pid ? project?.versions.find((v) => v.id === shown?.id) : undefined
  const base = own?.base_id ? whole?.versions.find((v) => v.id === own.base_id) : undefined

  // A draft opened for editing starts from what the server holds (a project's: what is its own).
  useEffect(() => {
    if (editing && shown && !dirty) {
      if (own) {
        const { inherit, ...parts } = own.data
        setDraft({ ...emptySet(), ...parts, dark: parts.dark ?? null })
        setModes(modesOf({ inherit }))
      } else setDraft(shown.data)
    }
    if (!editing) setDraft(null)
  }, [editing, shown?.id, shown?.updated_at]) // eslint-disable-line react-hooks/exhaustive-deps

  // Unsaved changes: the browser asks before the tab goes; "Done" asks before the editor closes.
  useEffect(() => {
    const leave = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault()
    }
    window.addEventListener('beforeunload', leave)
    return () => window.removeEventListener('beforeunload', leave)
  }, [dirty])

  const choose = (versionId: string, extra: Record<string, string> = {}) => setParams({ v: versionId, ...extra }, { replace: true })
  // A button above the tabs (a review waiting, comparing) opens one and brings it into view: the tabs can be far down.
  const openTab = (tab: string) => {
    if (shown) choose(shown.id, { tab })
    requestAnimationFrame(() => document.getElementById('set-view')?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
  const fileUrl = useCallback((media: string) => mediaUrl(media), [])
  const addFile = useCallback((m: MediaInfo) => setFiles((f) => ({ ...f, [m.id]: { name: m.name, kind: m.kind, size: m.size } })), [])

  const saveDraft = async () => {
    if (!whole || !shown || !draft) return
    setRefused(null)
    const ok = await save.run(async () => {
      const kept = modes ? Object.fromEntries(INHERIT_PARTS.filter((part) => modes[part] !== 'inherit').map((part) => [part, modes[part]])) : null
      try {
        await clientsApi.saveDraft(whole.id, shown.id, { data: kept ? { ...draft, inherit: kept } : draft })
      } catch (error) {
        // Which colour, which field: the server says where.
        if (error instanceof ApiError && error.code === 'invalid_set' && typeof error.values.where === 'string') setRefused(placeOf(error.values.where, draft))
        throw error
      }
      setDirty(false)
      await load()
    }, t('client.saved'))
    return ok
  }

  const asOf = (day: string) => {
    const held = published.filter((v) => v.valid_from <= day)
    const hit = held[held.length - 1]
    if (hit) choose(hit.id)
    return !!hit
  }

  const threeYears = useMemo(() => {
    const d = new Date()
    d.setFullYear(d.getFullYear() - 3)
    return d.toISOString().slice(0, 10)
  }, [])

  if (missing)
    return (
      <main className="mx-auto max-w-xl px-4 py-16 text-center">
        <p className="text-mist-300">{t('client.missing')}</p>
        <Link to="/" className="nc-btn nc-btn-ghost mt-4">
          {t('clients.title')}
        </Link>
      </main>
    )
  if (whole && projectMissing)
    return (
      <main className="mx-auto max-w-xl px-4 py-16 text-center" data-testid="project-missing">
        <p className="text-mist-300">{t('projects.missing')}</p>
        <Link to={`/c/${whole.id}?tab=projects`} className="nc-btn nc-btn-ghost mt-4">
          {t('projects.toClient', { client: whole.name })}
        </Link>
      </main>
    )
  if (!whole || (pid && !project)) return <main className="flex-1" aria-busy="true" />
  if (!shown && !project) return <NoDesignYet whole={whole} reload={load} onMade={(v) => choose(v.id, { edit: '1' })} />
  if (!shown) return <main className="flex-1" aria-busy="true" />

  const space = brands.space(whole.space_id)
  const openReview = whole.reviews.find((r) => r.version_id === shown.id && r.status === 'open')
  const next = published.find((v) => v.valid_from > shown.valid_from)
  const face = project ? project.face : whole.face
  const clientCurrent = whole.versions.find((v) => v.id === whole.current_id)
  // The project stands on a published client version older than the one that holds today: lifting it is a step
  // forward. On the one that holds, or on one that holds only from a later day, nothing to lift.
  const order = whole.versions.map((v) => v.id)
  const behind = !!(clientCurrent && own && base?.status === 'published' && order.indexOf(base.id) < order.indexOf(clientCurrent.id))
  // Published to hold from a later day than the one that holds now.
  const upcoming = (v: VersionInfo) => v.status === 'published' && (!current || published.indexOf(v) > published.indexOf(current))
  const mine = new Set(versions.map((v) => v.id))

  return (
    <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-wrap items-center gap-4">
          <ClientMark name={project?.name ?? whole.name} logo={face.mark ?? face.logo} colors={face.colors} fileUrl={(m) => mediaUrl(m, true)} className="h-16 w-16" />
          <div className="min-w-0 flex-1">
            <div className="text-xs text-mist-500">
              <Link to="/" className="hover:text-mist-200">
                {t('clients.title')}
              </Link>
              {project && (
                <>
                  {' · '}
                  <Link to={`/c/${whole.id}?tab=projects`} className="hover:text-mist-200">
                    {whole.name}
                  </Link>
                  {' · '}
                  {t('client.tabProjects', { count: whole.projects.length })}
                </>
              )}
              {!project && whole.sector && <> · {whole.sector}</>}
              {!project && whole.links.find((l) => l.kind === 'website') && (
                <>
                  {' · '}
                  <a href={whole.links.find((l) => l.kind === 'website')!.url} target="_blank" rel="noreferrer noopener" className="hover:text-mist-200 hover:underline">
                    {whole.links.find((l) => l.kind === 'website')!.url.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                  </a>
                </>
              )}
            </div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              {project?.name ?? whole.name}
              {!project && (
              <button
                type="button"
                aria-pressed={whole.favorite}
                aria-label={t('client.favorite')}
                onClick={() => void clientsApi.change(whole.id, { favorite: !whole.favorite }).then((info) => (brands.put(info), load()))}
                className={'rounded-full p-1 ' + (whole.favorite ? 'text-accent-400' : 'text-mist-600 hover:text-mist-200')}
              >
                <Star className="h-5 w-5" fill={whole.favorite ? 'currentColor' : 'none'} />
              </button>
              )}
            </h1>
            {project?.note && <p className="mt-0.5 text-sm text-mist-400">{project.note}</p>}
            {!project && whole.dropped && (
              <p className="mt-2 max-w-2xl rounded-lg border border-accent-500/30 bg-accent-500/8 px-3 py-2 text-xs text-mist-300" data-testid="client-dropped-hint">
                {t('suite.droppedHint')}
              </p>
            )}
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            {canWrite && (
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setDialog('edit')}>
                <Pencil className="h-4 w-4" aria-hidden /> {project ? t('projects.rename') : t('client.edit')}
              </button>
            )}
            {space && !project && <AccessButtons space={space} />}
            <button type="button" className="nc-btn nc-btn-accent" onClick={() => setDialog('export')}>
              <Download className="h-4 w-4" /> {t('client.export')}
            </button>
          </div>
        </div>

        <section className="rounded-2xl border border-ink-700 bg-ink-900 p-4" aria-label={t('client.timeline')}>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 text-sm font-semibold">
              <History className="h-4 w-4 text-accent-400" /> {t('client.timeline')}
            </h2>
            <div className="flex flex-wrap items-center gap-2 text-xs text-mist-500">
              {/* Looking back only where there is something to see, said in the page, not in a browser alert. */}
              {published.length > 0 && (
                <>
                  <CalendarClock className="h-3.5 w-3.5" />
                  <label className="flex items-center gap-2">
                    {t('client.asOf')}
                    <input type="date" className="h-8 rounded-lg border border-ink-700 bg-ink-850 px-2 text-xs text-mist-100" onChange={(e) => setNoneThen(e.target.value && !asOf(e.target.value) ? e.target.value : null)} />
                  </label>
                  {published.some((v) => v.valid_from <= threeYears) && (
                    <button type="button" className="rounded-full border border-ink-700 px-2.5 py-1 text-mist-300 hover:text-mist-100" title={t('client.threeYearsTitle', { date: new Date(threeYears).toLocaleDateString(i18n.language) })} onClick={() => (asOf(threeYears), setNoneThen(null))}>
                      {t('client.threeYears')}
                    </button>
                  )}
                </>
              )}
              {canWrite && (
                <button type="button" className="rounded-full border border-accent-500/50 px-2.5 py-1 text-accent-400 hover:bg-accent-500/10" onClick={() => setDialog('version')}>
                  <Plus className="mr-1 inline h-3 w-3" />
                  {t('client.newVersion')}
                </button>
              )}
            </div>
          </div>
          {noneThen && (
            <p role="status" className="mt-2 text-xs text-mist-400" data-testid="none-then">
              {t('client.noneThen', { date: new Date(noneThen).toLocaleDateString(i18n.language), first: new Date(published[0].valid_from).toLocaleDateString(i18n.language) })}
            </p>
          )}
          <ol className="mt-4 flex items-stretch overflow-x-auto pb-1">
            {versions.map((v, i) => {
              const on = v.id === shown.id
              const isDraft = v.status === 'draft'
              return (
                <li key={v.id} className="flex min-w-40 flex-1 items-center">
                  {i > 0 && <span className={'h-0.5 w-4 shrink-0 ' + (isDraft ? 'border-t-2 border-dashed border-magenta-500/60' : 'bg-ink-600')} />}
                  <button type="button" onClick={() => choose(v.id)} aria-current={on} className={'w-full rounded-xl border px-3 py-2 text-left transition-colors ' + (on ? 'border-accent-500 bg-accent-500/12' : isDraft ? 'border-dashed border-magenta-500/50 hover:bg-ink-850' : 'border-ink-700 hover:bg-ink-850')}>
                    <div className="flex items-center gap-1.5">
                      <span className="truncate font-semibold">{v.label}</span>
                      {v === current && <span className="rounded-full border border-accent-500/40 px-1.5 text-[10px] text-accent-400">{t('client.current')}</span>}
                      {upcoming(v) && <span className="rounded-full border border-gelb-500/50 px-1.5 text-[10px] text-gelb-text">{t('client.upcoming')}</span>}
                      {isDraft && <span className="rounded-full border border-magenta-500/50 px-1.5 text-[10px] text-magenta-text">{t('client.draft')}</span>}
                    </div>
                    <div className="mt-1 flex gap-0.5">
                      {v.data.colors.slice(0, 7).map((c, j) => (
                        <span key={j} className="h-3 flex-1 rounded-sm border border-black/10" style={{ background: c.hex }} />
                      ))}
                    </div>
                    <div className="mt-1 text-[11px] text-mist-500">{isDraft ? t('client.since', { date: new Date(v.created_at).toLocaleDateString(i18n.language) }) : t('client.from', { date: new Date(v.valid_from).toLocaleDateString(i18n.language) })}</div>
                    {project && <div className="text-[11px] text-mist-500">{t('projects.standsOn', { client: whole.name, label: project.versions.find((x) => x.id === v.id)?.base_label ?? '?' })}</div>}
                  </button>
                </li>
              )
            })}
          </ol>
          {project && own && (
            <div className={'mt-3 space-y-2 rounded-xl px-3 py-2.5 text-sm ' + (behind ? 'border border-gelb-500/40 bg-gelb-500/8' : 'bg-ink-850')} data-testid="project-base">
              {/* The sentence over the whole width, the parts and the button below: in one row the sentence was
                  squeezed into a narrow column (04.10.2026). */}
              <p className="text-mist-300">
                {t('projects.base', { client: whole.name, label: own.base_label ?? '?' })}{' '}
                {behind && clientCurrent && t('projects.newer', { label: clientCurrent.label })}
                {base?.status === 'draft' && t('projects.onDraftText', { label: base.label })}
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <span className="mr-auto flex flex-wrap gap-1 text-[11px]">
                {INHERIT_PARTS.map((part) => {
                  const m = modesOf(own.data)[part]
                  return (
                    <span key={part} className={'rounded-full border px-2 py-0.5 ' + (m === 'inherit' ? 'border-ink-700 text-mist-500' : m === 'extend' ? 'border-accent-500/50 text-accent-400' : 'border-magenta-500/50 text-magenta-text')} title={t(`inherit.mode.${m}`, { from: whole.name })}>
                      {t(`inherit.part.${part}`)}: {t(`inherit.short.${m}`)}
                    </span>
                  )
                })}
              </span>
              {canWrite && behind && clientCurrent && (
                <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setDialog('lift')}>
                  <ArrowUpCircle className="h-4 w-4" /> {t('projects.liftTo', { label: clientCurrent.label })}
                </button>
              )}
              </div>
            </div>
          )}
        </section>

        {shown.status === 'draft' ? (
          <div className="space-y-3 rounded-xl border border-magenta-500/40 bg-magenta-500/8 px-4 py-3 text-sm" data-testid="draft-bar">
            {/* The words over the whole width, the actions in one row below: five buttons beside a sentence squeezed it
                into a narrow column (04.10.2026). */}
            <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-mist-200">
              <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + ORIGIN_TONE[shown.origin]}>{t(`origin.${shown.origin}`)}</span>
              <span className="min-w-0 flex-1">
                {t('client.draftBanner', { author: shown.author })} <DerivedFrom version={shown} versions={versions} /> {shown.note} {current ? t('client.draftHolds', { label: current.label }) : project ? t('projects.draftOnly', { project: project.name }) : t('client.draftOnly')}
              </span>
            </p>
            <div className="flex flex-wrap items-center gap-2">
              {canWrite && !editing && (
                <button type="button" className="nc-btn nc-btn-ghost" onClick={() => choose(shown.id, { edit: '1' })}>
                  <Pencil className="h-4 w-4" /> {t('client.editDraft')}
                </button>
              )}
              {current && (
                <button type="button" className="nc-btn nc-btn-ghost" onClick={() => openTab('history')} title={t('client.compareWith', { label: current.label })}>
                  <GitCompare className="h-4 w-4" /> {t('client.compare')}
                </button>
              )}
              {canWrite && !openReview && (
                <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setDialog('review')}>
                  <Send className="h-4 w-4" /> {t('client.toClient')}
                </button>
              )}
              <span className="flex-1" />
              {canWrite && (
                <button type="button" className="rounded-full px-2 py-1 text-xs text-mist-500 hover:text-bad-500" onClick={() => setDialog('deleteDraft')}>
                  <Trash2 className="mr-1 inline h-3.5 w-3.5 align-[-2px]" /> {t('client.deleteDraft')}
                </button>
              )}
              {canWrite && (
                <button type="button" className="nc-btn nc-btn-accent" disabled={dirty} title={dirty ? t('client.saveFirst') : undefined} onClick={() => setDialog('publish')}>
                  <Upload className="h-4 w-4" /> {t('client.publish')}
                </button>
              )}
            </div>
          </div>
        ) : shown !== current ? (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-gelb-500/40 bg-gelb-500/8 px-4 py-3 text-sm text-mist-200" data-testid="other-version">
            <span className="flex-1">{upcoming(shown) ? (current ? t('client.upcomingText', { label: shown.label, from: new Date(shown.valid_from).toLocaleDateString(i18n.language), current: current.label }) : t('client.upcomingNone', { label: shown.label, from: new Date(shown.valid_from).toLocaleDateString(i18n.language) })) : next ? t('client.olderUntil', { label: shown.label, from: new Date(shown.valid_from).toLocaleDateString(i18n.language), until: new Date(next.valid_from).toLocaleDateString(i18n.language), current: current?.label }) : t('client.older', { label: shown.label })}</span>
            {current && (
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => choose(current.id)}>
                {t('client.toCurrent')} <ArrowRight className="h-4 w-4" />
              </button>
            )}
          </div>
        ) : null}

        {whole.news > 0 && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-magenta-500/50 bg-magenta-500/10 px-4 py-3 text-sm" role="status" data-testid="review-news">
            <MessagesSquare className="h-4 w-4 text-magenta-text" />
            <span className="flex-1 font-semibold">{t('client.reviewNews', { count: whole.news })}</span>
            <button type="button" className="nc-btn nc-btn-accent" onClick={() => openTab('reviews')}>
              {t('client.seeReview')}
            </button>
          </div>
        )}

        {openReview && whole.news === 0 && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 bg-ink-900 px-4 py-3 text-sm">
            <MessagesSquare className="h-4 w-4 text-magenta-text" />
            <span className="flex-1">{t('client.inReview')}</span>
            <button type="button" className="nc-btn nc-btn-ghost" onClick={() => openTab('reviews')}>
              {t('client.seeReview')}
            </button>
          </div>
        )}

        {editing && draft ? (
          <>
            <SetEditor
              value={draft}
              onChange={(value) => {
                setDraft(value)
                setDirty(true)
              }}
              name={project?.name ?? whole.name}
              ctx={{ space: whole.space_id, files, addFile, fileUrl }}
              inherit={project && modes ? { base: base?.data ?? emptySet(), modes, from: whole.name, onModes: (m) => (setModes(m), setDirty(true)) } : undefined}
            />
            <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-end gap-3 rounded-2xl border border-ink-700 bg-ink-900/95 px-4 py-3 shadow-lg backdrop-blur">
              <span className="mr-auto text-sm text-mist-400">{dirty ? t('client.unsaved') : t('client.allSaved')}</span>
              {save.problem === 'invalid_set' && refused ? (
                <p role="alert" className="text-sm text-bad-500" data-testid="save-refused">
                  {placeText(t, refused)}
                </p>
              ) : (
                <Feedback problem={save.problem} />
              )}
              {/* Unsaved changes: asked with the family's dialog, not the browser's. */}
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => (dirty ? setDialog('leave') : choose(shown.id))}>
                {t('client.doneEditing')}
              </button>
              <Button accent busy={save.busy} disabled={!dirty} onClick={() => void saveDraft()}>
                {t('common.save')}
              </Button>
            </div>
          </>
        ) : (
          <div id="set-view" className="scroll-mt-4">
          <SetView
            key={shown.id}
            set={shown.data}
            colors={own ? shown.data.colors.map((c, i) => ({ ...c, from: own.parts.colors?.[i] !== 'project' ? 'inherited' : base?.data.colors.some((x) => x.name.toLowerCase() === c.name.toLowerCase()) ? 'replaced' : 'own' })) : undefined}
            fileUrl={fileUrl}
            files={files}
            tab={params.get('tab') ?? 'colors'}
            onTab={(tab) => choose(shown.id, { tab })}
            extra={[
              { value: 'ui', label: t('ui.tab'), icon: Copy, content: <UiElements set={shown.data} name={project?.name ?? whole.name} fileUrl={fileUrl} /> },
              ...(project ? [] : [{ value: 'projects', label: t('client.tabProjects', { count: whole.projects.length }), icon: FolderKanban, content: <Projects whole={whole} canWrite={canWrite} reload={load} /> }]),
              { value: 'history', label: t('client.tabHistory'), icon: History, content: <HistoryPanel versions={versions} start={shown} canWrite={canWrite} onDelete={() => setDialog('deleteDraft')} /> },
              { value: 'pages', label: t('client.tabPages'), icon: Globe, content: <SharesPanel client={whole.id} versions={versions} role={whole.role} project={project?.id} /> },
              { value: 'reviews', label: whole.news ? t('client.tabReviewsNews', { count: whole.news }) : t('client.tabReviews'), icon: MessagesSquare, content: <ReviewsPanel client={whole.id} versions={versions} only={[...mine]} role={whole.role} onChange={load} /> },
            ]}
          />
          </div>
        )}

        {canWrite && (project || !whole.managed || whole.dropped) && (
          <div className="flex justify-end pt-4">
            <button type="button" className="nc-btn nc-btn-ghost text-mist-500" onClick={() => setDialog('trash')}>
              <Trash2 className="h-4 w-4" /> {project ? t('projects.delete') : t('client.trash')}
            </button>
          </div>
        )}
      </div>

      {dialog === 'edit' && !project && <EditClient whole={whole} onClose={() => setDialog(null)} onSaved={() => (setDialog(null), void load().then((c) => c && brands.refresh()))} />}
      {dialog === 'edit' && project && <RenameProject whole={whole} project={project} onClose={() => setDialog(null)} onSaved={() => (setDialog(null), void load())} />}
      {dialog === 'version' && <NewVersion whole={whole} versions={versions} project={project?.id} start={shown} onClose={() => setDialog(null)} onMade={(v) => (setDialog(null), void load().then(() => choose(v.id, { edit: '1' })))} />}
      {dialog === 'lift' && project && clientCurrent && own && (
        <LiftProject whole={whole} project={project} from={own} to={clientCurrent} onClose={() => setDialog(null)} onMade={(v) => (setDialog(null), void load().then(() => choose(v.id)))} />
      )}
      {dialog === 'publish' && <Publish whole={whole} version={shown} onClose={() => setDialog(null)} onDone={() => (setDialog(null), void load().then(() => (brands.refresh(), choose(shown.id))))} />}
      {dialog === 'export' && <ExportDialog source={{ client: whole.id, version: shown.id }} title={`${project ? `${whole.name}, ${project.name}` : whole.name} ${shown.label}`} onClose={() => setDialog(null)} />}
      {dialog === 'review' && <NewReview whole={whole} version={own ?? shown} versions={project ? project.versions : undefined} onClose={() => setDialog(null)} onMade={() => (setDialog(null), void load().then(() => choose(shown.id, { tab: 'reviews' })))} />}
      {dialog === 'leave' && (
        <Confirm
          title={t('client.leaveTitle')}
          text={t('client.leaveText')}
          confirm={t('client.leave')}
          danger
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            setDialog(null)
            setDirty(false)
            choose(shown.id)
          }}
        />
      )}
      {dialog === 'trash' && project && (
        <Confirm title={t('projects.delete')} text={t('projects.deleteText', { name: project.name })} confirm={t('projects.delete')} danger onCancel={() => setDialog(null)} onConfirm={async () => (await clientsApi.deleteProject(whole.id, project.id), navigate(`/c/${whole.id}?tab=projects`))} />
      )}
      {dialog === 'trash' && !project && (
        <Confirm title={t('client.trash')} text={t('client.trashText', { name: whole.name })} confirm={t('client.trash')} danger onCancel={() => setDialog(null)} onConfirm={async () => (await clientsApi.trash(whole.id), await brands.refresh(), navigate('/'))} />
      )}
      {dialog === 'deleteDraft' && (
        <Confirm
          title={t('client.deleteDraft')}
          text={[t('client.deleteDraftText', { label: shown.label }), deleteDraftWarning(whole.reviews, shown.id, t)].filter(Boolean).join(' ')}
          confirm={t('client.deleteDraft')}
          danger
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            await clientsApi.deleteDraft(whole.id, shown.id, !!openReview)
            setDialog(null)
            setParams({})
            await load()
          }}
        />
      )}
    </main>
  )
}

/** What goes with a draft that is or was before the client: an open review closes, the client's comments go. */
function deleteDraftWarning(reviews: ClientWhole['reviews'], version: string, t: TFunction): string {
  const own = reviews.filter((r) => r.version_id === version)
  const said = own.reduce((sum, r) => sum + r.comments, 0)
  if (own.some((r) => r.status === 'open')) return said ? t('client.deleteDraftOpen', { count: said }) : t('client.deleteDraftOpenQuiet')
  return said ? t('client.deleteDraftComments', { count: said }) : ''
}

/** Who has access: the people (with invitations) and the teams. A client the directory service keeps shows them, changed there. */
export function AccessButtons({ space }: { space: NonNullable<ReturnType<ReturnType<typeof useBrands>['space']>> }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState<'people' | 'teams' | null>(null)
  const manage = space.role === 'manage' && !space.managed
  return (
    <>
      <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setOpen('people')} title={space.managed ? t('suite.fromSuite') : undefined}>
        <Users className="h-4 w-4" /> {t('client.access')}
        <span className="text-xs text-mist-500 tabular-nums" data-testid="access-count">{space.people ?? space.members.length}</span>
      </button>
      {manage && (
        <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setOpen('teams')}>
          <UsersRound className="h-4 w-4" /> {t('settings.tabs.teams')}
        </button>
      )}
      {open === 'people' && <MembersDialog space={space} onClose={() => setOpen(null)} />}
      {open === 'teams' && <TeamRightsDialog space={space} onClose={() => setOpen(null)} />}
    </>
  )
}

/** A client the directory service brought, or one made without a design set: three ways to its first version. */
function NoDesignYet({ whole, reload, onMade }: { whole: ClientWhole; reload: () => Promise<unknown>; onMade: (v: VersionInfo) => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const brands = useBrands()
  const space = brands.space(whole.space_id)
  const canWrite = whole.role === 'write' || whole.role === 'manage'
  const { busy, problem, run } = useAction()
  const [trashing, setTrashing] = useState(false)
  return (
    <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-wrap items-center gap-4">
          <span className="grid h-16 w-16 shrink-0 place-items-center rounded-2xl text-2xl font-bold" style={{ background: whole.color, color: textOn(whole.color) }} aria-hidden>
            {whole.name.slice(0, 1).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-xs text-mist-500">
              <Link to="/" className="hover:text-mist-200">
                {t('clients.title')}
              </Link>
              {whole.sector && <> · {whole.sector}</>}
            </div>
            <h1 className="text-2xl font-bold tracking-tight">{whole.name}</h1>
            {whole.dropped && (
              <p className="mt-2 max-w-2xl rounded-lg border border-accent-500/30 bg-accent-500/8 px-3 py-2 text-xs text-mist-300" data-testid="client-dropped-hint">
                {t('suite.droppedHint')}
              </p>
            )}
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">{space && <AccessButtons space={space} />}</div>
        </div>
        <section className="rounded-2xl border border-dashed border-ink-700 p-6" data-testid="no-design-yet">
          <h2 className="text-lg font-semibold">{t('client.noCiTitle')}</h2>
          <p className="mt-1 max-w-2xl text-sm text-mist-500">{whole.managed ? t('client.noCiSuite') : t('client.noCiText')}</p>
          {canWrite ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <button type="button" className="rounded-xl border border-ink-700 p-4 text-left hover:bg-ink-850" onClick={() => navigate(`/new?client=${whole.id}`)}>
                <Sparkles className="h-5 w-5 text-accent-400" />
                <span className="mt-2 block font-medium">{t('client.noCiWizard')}</span>
                <span className="block text-xs text-mist-500">{t('client.noCiWizardText')}</span>
              </button>
              <button type="button" className="rounded-xl border border-ink-700 p-4 text-left hover:bg-ink-850" onClick={() => navigate(`/collect?client=${whole.id}`)}>
                <Wand2 className="h-5 w-5 text-accent-400" />
                <span className="mt-2 block font-medium">{t('client.noCiCollect')}</span>
                <span className="block text-xs text-mist-500">{t('client.noCiCollectText')}</span>
              </button>
              <button
                type="button"
                disabled={busy}
                className="rounded-xl border border-ink-700 p-4 text-left hover:bg-ink-850 disabled:opacity-50"
                onClick={() =>
                  void run(async () => {
                    const made = await clientsApi.newVersion(whole.id, { label: '1.0' })
                    await reload()
                    await brands.refresh()
                    onMade(made)
                  })
                }
              >
                <FilePlus2 className="h-5 w-5 text-accent-400" />
                <span className="mt-2 block font-medium">{t('client.noCiEmpty')}</span>
                <span className="block text-xs text-mist-500">{t('client.noCiEmptyText')}</span>
              </button>
            </div>
          ) : (
            <p className="mt-3 text-sm text-mist-500">{t('client.noCiRead')}</p>
          )}
          <Feedback problem={problem} />
        </section>
        {canWrite && (!whole.managed || whole.dropped) && (
          <div className="flex justify-end">
            <button type="button" className="nc-btn nc-btn-ghost text-mist-500" onClick={() => setTrashing(true)}>
              <Trash2 className="h-4 w-4" /> {t('client.trash')}
            </button>
          </div>
        )}
      </div>
      {trashing && (
        <Confirm title={t('client.trash')} text={t('client.trashText', { name: whole.name })} confirm={t('client.trash')} danger onCancel={() => setTrashing(false)} onConfirm={async () => (await clientsApi.trash(whole.id), await brands.refresh(), navigate('/'))} />
      )}
    </main>
  )
}

function EditClient({ whole, onClose, onSaved }: { whole: ClientWhole; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState(whole.name)
  const [sector, setSector] = useState(whole.sector)
  const [contact, setContact] = useState(whole.contact)
  const [color, setColor] = useState(whole.color)
  const [note, setNote] = useState(whole.note)
  const [links, setLinks] = useState<ClientLink[]>(whole.links)
  const { busy, problem, run } = useAction()
  // Kept in the directory service: name, sector, contact and colour are changed there; the note and the addresses are nexbrand's.
  const kept = whole.managed
  const usable = links.filter((l) => l.url.trim())
  const change = kept ? { note, links: usable } : { name, sector, contact, note, links: usable, ...(CLIENT_COLORS.includes(color) ? { color } : {}) }
  return (
    <Dialog title={t('client.edit')} onClose={onClose} medium>
      <div className="space-y-3">
        {kept && <p className="rounded-lg border border-accent-500/30 bg-accent-500/8 px-3 py-2 text-xs text-mist-300">{t('client.keptInSuite')}</p>}
        {kept ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-mist-500">{t('client.name')}</dt>
            <dd>{whole.name}</dd>
            <dt className="text-mist-500">{t('client.sector')}</dt>
            <dd>{whole.sector || t('suite.notSet')}</dd>
            <dt className="text-mist-500">{t('client.contact')}</dt>
            <dd>{whole.contact || t('suite.notSet')}</dd>
          </dl>
        ) : (
          <>
            <Input label={t('client.name')} value={name} onChange={setName} />
            <Input label={t('client.sector')} value={sector} onChange={setSector} />
            <Input label={t('client.contact')} value={contact} onChange={setContact} />
            <div className="text-sm">
              <span className="text-xs font-medium text-mist-400">{t('client.color')}</span>
              <div className="mt-1 flex flex-wrap gap-2" role="radiogroup" aria-label={t('client.color')}>
                {CLIENT_COLORS.map((c) => (
                  <button key={c} type="button" role="radio" aria-checked={color === c} aria-label={c} onClick={() => setColor(c)} className={'h-7 w-7 rounded-full border-2 ' + (color === c ? 'border-mist-100' : 'border-transparent')} style={{ background: c }} />
                ))}
              </div>
            </div>
          </>
        )}
        <div className="text-sm">
          <span className="text-xs font-medium text-mist-400">{t('client.links')}</span>
          <p className="text-xs text-mist-500">{t('client.linksHint')}</p>
          <div className="mt-1 space-y-2">
            {links.map((link, index) => (
              <div key={index} className="flex flex-wrap items-center gap-2">
                <select
                  value={link.kind}
                  onChange={(e) => setLinks((all) => all.map((l, i) => (i === index ? { ...l, kind: e.target.value as ClientLink['kind'] } : l)))}
                  aria-label={t('collect.kind')}
                  className="h-9 rounded-lg border border-ink-700 bg-ink-850 px-2 text-sm"
                >
                  <option value="website">{t('collect.kinds.website')}</option>
                  <option value="repo">{t('collect.kinds.repo')}</option>
                </select>
                <input
                  value={link.url}
                  onChange={(e) => setLinks((all) => all.map((l, i) => (i === index ? { ...l, url: e.target.value } : l)))}
                  placeholder={link.kind === 'repo' ? 'https://github.com/example/site' : 'https://www.example.com'}
                  aria-label={t('client.linkUrl')}
                  className="h-9 min-w-0 flex-1 rounded-lg border border-ink-700 bg-ink-850 px-2 font-mono text-xs"
                />
                <button type="button" onClick={() => setLinks((all) => all.filter((_, i) => i !== index))} aria-label={t('collect.remove')} className="rounded-full p-1.5 text-mist-500 hover:text-bad-500">
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            {links.length < 10 && (
              <button type="button" onClick={() => setLinks((all) => [...all, { kind: 'website', url: '', label: '' }])} className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs">
                <Plus className="h-3.5 w-3.5" /> {t('client.linkAdd')}
              </button>
            )}
          </div>
        </div>
        <label className="block text-sm">
          <span className="text-xs font-medium text-mist-400">{t('client.note')}</span>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={4} className="mt-1 w-full rounded-lg border border-ink-700 bg-ink-850 px-3 py-2 text-sm" />
        </label>
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} onClick={() => void run(async () => (await clientsApi.change(whole.id, change), onSaved()))}>
            {t('common.save')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

function NewVersion({ whole, versions, project, start, onClose, onMade }: { whole: ClientWhole; versions: VersionInfo[]; project?: string; start: VersionInfo; onClose: () => void; onMade: (v: VersionInfo) => void }) {
  const { t } = useTranslation()
  const [label, setLabel] = useState('')
  const [source, setSource] = useState(start.id)
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('client.newVersion')} onClose={onClose} medium>
      <div className="space-y-3">
        <p className="text-sm text-mist-400">{t('client.newVersionText')}</p>
        <Input label={t('client.versionName')} value={label} onChange={setLabel} placeholder={t('client.versionNameHint')} />
        <Select label={t('client.startFrom')} value={source} onChange={setSource} options={[...versions.map((v) => ({ value: v.id, label: v.label })), { value: '', label: project ? t('projects.allFromClient', { client: whole.name }) : t('client.empty') }]} />
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} disabled={!label.trim()} onClick={() => void run(async () => onMade(await clientsApi.newVersion(whole.id, { label, source: source || undefined, ...(project ? { project_id: project, ...(source ? {} : { data: {} }) } : {}) })))}>
            {t('client.makeDraft')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

function Publish({ whole, version, onClose, onDone }: { whole: ClientWhole; version: VersionInfo; onClose: () => void; onDone: () => void }) {
  const { t } = useTranslation()
  const [label, setLabel] = useState(version.label)
  const [day, setDay] = useState(new Date().toISOString().slice(0, 10))
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('client.publish')} onClose={onClose} medium>
      <div className="space-y-3">
        <p className="text-sm text-mist-300">{t('client.publishText')}</p>
        <Input label={t('client.versionName')} value={label} onChange={setLabel} />
        <Input label={t('client.validFrom')} value={day} onChange={setDay} type="date" hint={t('client.validFromHint')} />
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} disabled={!label.trim()} onClick={() => void run(async () => (await clientsApi.publish(whole.id, version.id, { label, valid_from: day }), onDone()))}>
            <Upload className="h-4 w-4" /> {t('client.publishNow')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

function Projects({ whole, canWrite, reload }: { whole: ClientWhole; canWrite: boolean; reload: () => Promise<unknown> }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [making, setMaking] = useState(false)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-sm text-mist-500">{t('projects.text', { client: whole.name })}</p>
        {canWrite && (
          <button type="button" className="nc-btn nc-btn-accent" onClick={() => setMaking(true)}>
            <Plus className="h-4 w-4" /> {t('projects.new')}
          </button>
        )}
      </div>
      {!whole.projects.length && <p className="text-sm text-mist-500">{t('projects.none')}</p>}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3" data-testid="project-cards">
        {whole.projects.map((p) => {
          const own = INHERIT_PARTS.filter((part) => p.inherit[part] !== 'inherit')
          return (
            <Link key={p.id} to={`/c/${whole.id}/p/${p.id}`} className="group overflow-hidden rounded-2xl border border-ink-700 bg-ink-900 hover:border-ink-600">
              <div className="relative grid h-32 place-items-center overflow-hidden bg-ink-850">
                {p.face.sample ? (
                  <img src={mediaUrl(p.face.sample, true)} alt="" className="h-full w-full object-cover object-top transition-transform group-hover:scale-[1.02]" />
                ) : (
                  <ClientMark name={p.name} logo={p.face.mark ?? p.face.logo} colors={p.face.colors} fileUrl={(m) => mediaUrl(m, true)} className="h-14 w-14" />
                )}
                <span className="absolute inset-x-0 bottom-0 flex h-1.5">
                  {p.face.colors.slice(0, 8).map((c, i) => (
                    <span key={i} className="flex-1" style={{ background: c }} />
                  ))}
                </span>
              </div>
              <div className="space-y-2 p-4">
                <div className="flex items-center gap-2.5">
                  {p.face.sample && <ClientMark name={p.name} logo={p.face.mark ?? p.face.logo} colors={p.face.colors} fileUrl={(m) => mediaUrl(m, true)} className="h-9 w-9" />}
                  <div className="mr-auto min-w-0">
                    <div className="truncate font-semibold">{p.name}</div>
                    {p.note && <div className="truncate text-xs text-mist-500">{p.note}</div>}
                  </div>
                  {p.behind ? (
                    <span className="shrink-0 rounded-full border border-gelb-500/50 px-2 py-0.5 text-[11px] text-gelb-text">{t('projects.on', { label: p.base_label })}</span>
                  ) : p.current ? (
                    <span className="shrink-0 rounded-full border border-accent-500/40 px-2 py-0.5 text-[11px] text-accent-400">{p.current}</span>
                  ) : (
                    <span className="shrink-0 rounded-full border border-magenta-500/50 px-2 py-0.5 text-[11px] text-magenta-text">{t('client.draft')}</span>
                  )}
                </div>
                <p className="text-xs text-mist-500">{own.length ? t('projects.ownParts', { parts: own.map((part) => t(`inherit.part.${part}`)).join(', ') }) : t('projects.allInherited', { client: whole.name })}</p>
              </div>
            </Link>
          )
        })}
      </div>
      {making && <NewProject whole={whole} onClose={() => setMaking(false)} onMade={(made) => (setMaking(false), void reload(), navigate(`/c/${whole.id}/p/${made.id}?v=${made.versions[0]?.id ?? ''}&edit=1`))} />}
    </div>
  )
}

function NewProject({ whole, onClose, onMade }: { whole: ClientWhole; onClose: () => void; onMade: (made: ProjectWhole) => void }) {
  const { t } = useTranslation()
  const published = whole.versions.filter((v) => v.status === 'published')
  const [name, setName] = useState('')
  // The version that holds today first; one that holds only from a later day is chosen on purpose.
  const [version, setVersion] = useState((whole.versions.find((v) => v.id === whole.current_id) ?? published[published.length - 1] ?? whole.versions[0]).id)
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('projects.new')} onClose={onClose} medium>
      <div className="space-y-3">
        <p className="text-sm text-mist-400">{t('projects.newText', { client: whole.name })}</p>
        <Input label={t('projects.name')} value={name} onChange={setName} placeholder={t('projects.nameHint')} />
        <Select label={t('projects.version')} value={version} onChange={setVersion} options={whole.versions.map((v) => ({ value: v.id, label: v.status === 'draft' ? `${v.label} (${t('client.draft')})` : v.label }))} />
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} disabled={!name.trim()} onClick={() => void run(async () => onMade(await clientsApi.newProject(whole.id, { name, version_id: version })))}>
            {t('projects.make')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

function RenameProject({ whole, project, onClose, onSaved }: { whole: ClientWhole; project: ProjectWhole; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const [name, setName] = useState(project.name)
  const [note, setNote] = useState(project.note)
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('projects.rename')} onClose={onClose} medium>
      <div className="space-y-3">
        <Input label={t('projects.name')} value={name} onChange={setName} />
        <Input label={t('projects.note')} value={note} onChange={setNote} />
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} disabled={!name.trim()} onClick={() => void run(async () => (await clientsApi.changeProject(whole.id, project.id, { name, note }), onSaved()))}>
            {t('common.save')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}

/** Lifting a project to the client's newer version: what changes in the parts it takes from the client, then a draft. */
function LiftProject({ whole, project, from, to, onClose, onMade }: { whole: ClientWhole; project: ProjectWhole; from: ProjectWhole['versions'][number]; to: VersionInfo; onClose: () => void; onMade: (v: VersionInfo) => void }) {
  const { t } = useTranslation()
  const older = whole.versions.find((v) => v.id === from.base_id)
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('projects.liftTitle', { from: older?.label ?? '?', to: to.label })} onClose={onClose} wide>
      <p className="mb-3 text-sm text-mist-400">{t('projects.liftText', { client: whole.name, project: project.name })}</p>
      {older && <DiffView a={older} b={to} />}
      <Feedback problem={problem} />
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>{t('projects.stay', { label: older?.label ?? '' })}</Button>
        <Button accent busy={busy} onClick={() => void run(async () => onMade(await clientsApi.newVersion(whole.id, { label: t('projects.liftLabel', { label: to.label }), source: from.id, project_id: project.id, base_id: to.id })))}>
          <ArrowUpCircle className="h-4 w-4" /> {t('projects.lift', { label: to.label })}
        </Button>
      </div>
    </Dialog>
  )
}

/** "Made from 1.0": the version a draft started as a copy of, by its name now, or by its name then when it is gone. */
function DerivedFrom({ version, versions }: { version: VersionInfo; versions: VersionInfo[] }) {
  const { t } = useTranslation()
  if (!version.source_id) return null
  const source = versions.find((v) => v.id === version.source_id)
  return <>{source ? t('client.derivedFrom', { label: source.label }) : t('client.derivedFromGone', { label: version.source_label })}</>
}

function HistoryPanel({ versions, start, canWrite, onDelete }: { versions: VersionInfo[]; start: VersionInfo; canWrite: boolean; onDelete: () => void }) {
  const { t, i18n } = useTranslation()
  const index = versions.indexOf(start)
  const [aId, setA] = useState((index > 0 ? versions[index - 1] : versions[0]).id)
  const [bId, setB] = useState(start.id)
  const a = versions.find((v) => v.id === aId) ?? versions[0]
  const b = versions.find((v) => v.id === bId) ?? start
  return (
    <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
      <ol className="space-y-2">
        {[...versions].reverse().map((v) => (
          <li key={v.id} className="rounded-xl border border-ink-700 bg-ink-900 p-3 text-sm">
            <div className="flex items-center gap-1.5">
              <span className="mr-auto font-semibold">{v.label}</span>
              <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + ORIGIN_TONE[v.origin]}>{t(`origin.${v.origin}`)}</span>
            </div>
            <div className="text-xs text-mist-500">
              {v.status === 'published' ? t('client.from', { date: new Date(v.valid_from).toLocaleDateString(i18n.language) }) : t('client.draft')} · {v.published_by || v.author}
            </div>
            {v.source_id && (
              <p className="mt-1 text-xs text-mist-400">
                <DerivedFrom version={v} versions={versions} />
              </p>
            )}
            {v.note && <p className="mt-1 text-xs text-mist-400">{v.note}</p>}
            {v === start && v.status === 'draft' && canWrite && (
              <button type="button" className="mt-2 text-xs text-mist-500 hover:text-bad-500" onClick={onDelete}>
                {t('client.deleteDraft')}
              </button>
            )}
          </li>
        ))}
      </ol>
      <section className="rounded-2xl border border-ink-700 bg-ink-900 p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
          <GitCompare className="h-4 w-4 text-accent-400" />
          <select value={aId} onChange={(e) => setA(e.target.value)} aria-label={t('diff.from')} className="h-8 rounded-lg border border-ink-700 bg-ink-850 px-2">
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
          <ArrowRight className="h-4 w-4 text-mist-600" />
          <select value={bId} onChange={(e) => setB(e.target.value)} aria-label={t('diff.to')} className="h-8 rounded-lg border border-ink-700 bg-ink-850 px-2">
            {versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </select>
        </div>
        <DiffView a={a} b={b} />
      </section>
    </div>
  )
}

