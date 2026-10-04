/** One client: its versions on a time line, the one chosen shown or (a draft) edited, projects, history, public
 * pages and reviews. */
import { ArrowRight, CalendarClock, Download, FilePlus2, FolderKanban, GitCompare, Globe, History, MessagesSquare, Pencil, Plus, Send, Sparkles, Star, Trash2, Upload, Users, UsersRound, Wand2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { ApiError, clientsApi, mediaUrl, type ClientWhole, type MediaInfo, type VersionInfo } from '../api/client'
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
import { CLIENT_COLORS } from '../lib/palette'
import type { BrandSet } from '../lib/brand'
import { Button, Confirm, Feedback, Input, Select, useAction } from './settings/ui'
import { useBrands } from '../state/brands'

const ORIGIN_TONE = { hand: 'border-ink-700 text-mist-500', collect: 'border-gelb-500/50 text-gelb-text', mcp: 'border-magenta-500/50 text-magenta-text', review: 'border-ok-500/40 text-ok-500' }

export function ClientPage() {
  const { id = '' } = useParams()
  const { t, i18n } = useTranslation()
  const navigate = useNavigate()
  const brands = useBrands()
  const [params, setParams] = useSearchParams()
  const [whole, setWhole] = useState<ClientWhole | null>(null)
  const [missing, setMissing] = useState(false)
  const [files, setFiles] = useState<FileMap>({})
  const [draft, setDraft] = useState<BrandSet | null>(null)
  const [dirty, setDirty] = useState(false)
  const [dialog, setDialog] = useState<'edit' | 'version' | 'publish' | 'export' | 'review' | 'trash' | 'deleteDraft' | null>(null)
  const save = useAction()

  const load = useCallback(async () => {
    try {
      const [client, known] = await Promise.all([clientsApi.read(id), clientsApi.files(id)])
      setWhole(client)
      setFiles((before) => ({ ...before, ...known }))
      return client
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) setMissing(true)
      return null
    }
  }, [id])

  useEffect(() => {
    setWhole(null)
    setMissing(false)
    setDraft(null)
    setDirty(false)
    void load()
    void clientsApi.visit(id).catch(() => undefined)
  }, [id, load])

  const versions = whole?.versions ?? []
  const published = versions.filter((v) => v.status === 'published')
  const current = published[published.length - 1]
  const chosenId = params.get('v')
  const shown = versions.find((v) => v.id === chosenId) ?? current ?? versions[0]
  const editing = shown?.status === 'draft' && params.get('edit') === '1' && (whole?.role === 'write' || whole?.role === 'manage')
  const canWrite = whole?.role === 'write' || whole?.role === 'manage'
  const canManage = whole?.role === 'manage'

  // A draft opened for editing starts from what the server holds.
  useEffect(() => {
    if (editing && shown && !dirty) setDraft(shown.data)
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
  const fileUrl = useCallback((media: string) => mediaUrl(media), [])
  const addFile = useCallback((m: MediaInfo) => setFiles((f) => ({ ...f, [m.id]: { name: m.name, kind: m.kind, size: m.size } })), [])

  const saveDraft = async () => {
    if (!whole || !shown || !draft) return
    const ok = await save.run(async () => {
      await clientsApi.saveDraft(whole.id, shown.id, { data: draft })
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
  if (!whole) return <main className="flex-1" aria-busy="true" />
  if (!shown) return <NoDesignYet whole={whole} reload={load} onMade={(v) => choose(v.id, { edit: '1' })} />

  const space = brands.space(whole.space_id)
  const openReview = whole.reviews.find((r) => r.version_id === shown.id && r.status === 'open')
  const next = published.find((v) => v.valid_from > shown.valid_from)
  const face = whole.face

  return (
    <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-wrap items-center gap-4">
          <ClientMark name={whole.name} logo={face.mark ?? face.logo} colors={face.colors} fileUrl={(m) => mediaUrl(m, true)} className="h-16 w-16" />
          <div className="min-w-0 flex-1">
            <div className="text-xs text-mist-500">
              <Link to="/" className="hover:text-mist-200">
                {t('clients.title')}
              </Link>
              {whole.sector && <> · {whole.sector}</>}
            </div>
            <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
              {whole.name}
              <button
                type="button"
                aria-pressed={whole.favorite}
                aria-label={t('client.favorite')}
                onClick={() => void clientsApi.change(whole.id, { favorite: !whole.favorite }).then((info) => (brands.put(info), load()))}
                className={'rounded-full p-1 ' + (whole.favorite ? 'text-accent-400' : 'text-mist-600 hover:text-mist-200')}
              >
                <Star className="h-5 w-5" fill={whole.favorite ? 'currentColor' : 'none'} />
              </button>
            </h1>
          </div>
          <div className="flex w-full flex-wrap gap-2 sm:w-auto">
            {canWrite && (
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setDialog('edit')}>
                <Pencil className="h-4 w-4" /> {t('client.edit')}
              </button>
            )}
            {space && <AccessButtons space={space} />}
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
              <CalendarClock className="h-3.5 w-3.5" />
              <label className="flex items-center gap-2">
                {t('client.asOf')}
                <input type="date" className="h-8 rounded-lg border border-ink-700 bg-ink-850 px-2 text-xs text-mist-100" onChange={(e) => e.target.value && !asOf(e.target.value) && window.alert(t('client.noneThen'))} />
              </label>
              <button type="button" className="rounded-full border border-ink-700 px-2.5 py-1 text-mist-300 hover:text-mist-100" onClick={() => !asOf(threeYears) && window.alert(t('client.noneThen'))}>
                {t('client.threeYears')}
              </button>
              {canWrite && (
                <button type="button" className="rounded-full border border-accent-500/50 px-2.5 py-1 text-accent-400 hover:bg-accent-500/10" onClick={() => setDialog('version')}>
                  <Plus className="mr-1 inline h-3 w-3" />
                  {t('client.newVersion')}
                </button>
              )}
            </div>
          </div>
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
                      {isDraft && <span className="rounded-full border border-magenta-500/50 px-1.5 text-[10px] text-magenta-text">{t('client.draft')}</span>}
                    </div>
                    <div className="mt-1 flex gap-0.5">
                      {v.data.colors.slice(0, 7).map((c, j) => (
                        <span key={j} className="h-3 flex-1 rounded-sm border border-black/10" style={{ background: c.hex }} />
                      ))}
                    </div>
                    <div className="mt-1 text-[11px] text-mist-500">{isDraft ? t('client.since', { date: new Date(v.created_at).toLocaleDateString(i18n.language) }) : t('client.from', { date: new Date(v.valid_from).toLocaleDateString(i18n.language) })}</div>
                  </button>
                </li>
              )
            })}
          </ol>
        </section>

        {shown.status === 'draft' ? (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-magenta-500/40 bg-magenta-500/8 px-4 py-3 text-sm">
            <span className={'rounded-full border px-2 py-0.5 text-[11px] ' + ORIGIN_TONE[shown.origin]}>{t(`origin.${shown.origin}`)}</span>
            <span className="min-w-0 flex-1 text-mist-200">
              {t('client.draftBanner', { author: shown.author })} {shown.note} {current ? t('client.draftHolds', { label: current.label }) : t('client.draftOnly')}
            </span>
            {canWrite && !editing && (
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => choose(shown.id, { edit: '1' })}>
                <Pencil className="h-4 w-4" /> {t('client.editDraft')}
              </button>
            )}
            {current && (
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => choose(shown.id, { tab: 'history' })}>
                <GitCompare className="h-4 w-4" /> {t('client.compareWith', { label: current.label })}
              </button>
            )}
            {canManage && !openReview && (
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setDialog('review')}>
                <Send className="h-4 w-4" /> {t('client.toClient')}
              </button>
            )}
            {canWrite && (
              <button type="button" className="nc-btn nc-btn-accent" disabled={dirty} title={dirty ? t('client.saveFirst') : undefined} onClick={() => setDialog('publish')}>
                <Upload className="h-4 w-4" /> {t('client.publish')}
              </button>
            )}
          </div>
        ) : shown !== current ? (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-gelb-500/40 bg-gelb-500/8 px-4 py-3 text-sm text-mist-200">
            <span className="flex-1">{next ? t('client.olderUntil', { label: shown.label, from: new Date(shown.valid_from).toLocaleDateString(i18n.language), until: new Date(next.valid_from).toLocaleDateString(i18n.language), current: current?.label }) : t('client.older', { label: shown.label })}</span>
            {current && (
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => choose(current.id)}>
                {t('client.toCurrent')} <ArrowRight className="h-4 w-4" />
              </button>
            )}
          </div>
        ) : null}

        {openReview && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-ink-700 bg-ink-900 px-4 py-3 text-sm">
            <MessagesSquare className="h-4 w-4 text-magenta-text" />
            <span className="flex-1">{t('client.inReview')}</span>
            <button type="button" className="nc-btn nc-btn-ghost" onClick={() => choose(shown.id, { tab: 'reviews' })}>
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
              name={whole.name}
              ctx={{ space: whole.space_id, files, addFile, fileUrl }}
            />
            <div className="sticky bottom-3 z-10 flex flex-wrap items-center justify-end gap-3 rounded-2xl border border-ink-700 bg-ink-900/95 px-4 py-3 shadow-lg backdrop-blur">
              <span className="mr-auto text-sm text-mist-400">{dirty ? t('client.unsaved') : t('client.allSaved')}</span>
              <Feedback problem={save.problem} />
              <button type="button" className="nc-btn nc-btn-ghost" onClick={() => (!dirty || window.confirm(t('client.leaveText'))) && (setDirty(false), choose(shown.id))}>
                {t('client.doneEditing')}
              </button>
              <Button accent busy={save.busy} disabled={!dirty} onClick={() => void saveDraft()}>
                {t('common.save')}
              </Button>
            </div>
          </>
        ) : (
          <SetView
            key={shown.id + (params.get('tab') ?? '')}
            set={shown.data}
            fileUrl={fileUrl}
            files={files}
            initialTab={params.get('tab') ?? 'colors'}
            extra={[
              { value: 'projects', label: t('client.tabProjects', { count: whole.projects.length }), icon: FolderKanban, content: <Projects whole={whole} canWrite={canWrite} reload={load} /> },
              { value: 'history', label: t('client.tabHistory'), icon: History, content: <HistoryPanel versions={versions} start={shown} canWrite={canWrite} onDelete={() => setDialog('deleteDraft')} /> },
              { value: 'pages', label: t('client.tabPages'), icon: Globe, content: <SharesPanel client={whole.id} versions={versions} canManage={canManage} /> },
              { value: 'reviews', label: t('client.tabReviews'), icon: MessagesSquare, content: <ReviewsPanel client={whole.id} versions={versions} canWrite={canWrite} canManage={canManage} onChange={load} /> },
            ]}
          />
        )}

        {canWrite && !whole.managed && (
          <div className="flex justify-end pt-4">
            <button type="button" className="nc-btn nc-btn-ghost text-mist-500" onClick={() => setDialog('trash')}>
              <Trash2 className="h-4 w-4" /> {t('client.trash')}
            </button>
          </div>
        )}
      </div>

      {dialog === 'edit' && <EditClient whole={whole} onClose={() => setDialog(null)} onSaved={() => (setDialog(null), void load().then((c) => c && brands.refresh()))} />}
      {dialog === 'version' && <NewVersion whole={whole} start={shown} onClose={() => setDialog(null)} onMade={(v) => (setDialog(null), void load().then(() => choose(v.id, { edit: '1' })))} />}
      {dialog === 'publish' && <Publish whole={whole} version={shown} onClose={() => setDialog(null)} onDone={() => (setDialog(null), void load().then(() => (brands.refresh(), choose(shown.id))))} />}
      {dialog === 'export' && <ExportDialog client={whole.id} version={shown.id} title={`${whole.name} ${shown.label}`} onClose={() => setDialog(null)} />}
      {dialog === 'review' && <NewReview whole={whole} version={shown} onClose={() => setDialog(null)} onMade={() => (setDialog(null), void load().then(() => choose(shown.id, { tab: 'reviews' })))} />}
      {dialog === 'trash' && (
        <Confirm title={t('client.trash')} text={t('client.trashText', { name: whole.name })} confirm={t('client.trash')} danger onCancel={() => setDialog(null)} onConfirm={async () => (await clientsApi.trash(whole.id), await brands.refresh(), navigate('/'))} />
      )}
      {dialog === 'deleteDraft' && (
        <Confirm
          title={t('client.deleteDraft')}
          text={t('client.deleteDraftText', { label: shown.label })}
          confirm={t('client.deleteDraft')}
          danger
          onCancel={() => setDialog(null)}
          onConfirm={async () => {
            await clientsApi.deleteDraft(whole.id, shown.id)
            setDialog(null)
            setParams({})
            await load()
          }}
        />
      )}
    </main>
  )
}

/** Who has access: the people (with invitations) and the teams. A client nexsuite keeps shows them, changed there. */
function AccessButtons({ space }: { space: NonNullable<ReturnType<ReturnType<typeof useBrands>['space']>> }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState<'people' | 'teams' | null>(null)
  const manage = space.role === 'manage' && !space.managed
  return (
    <>
      <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setOpen('people')} title={space.managed ? t('suite.fromSuite') : undefined}>
        <Users className="h-4 w-4" /> {t('client.access')}
        <span className="text-xs text-mist-500 tabular-nums">{space.members.length + space.teams.length}</span>
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

/** A client nexsuite brought, or one made without a design set: three ways to its first version. */
function NoDesignYet({ whole, reload, onMade }: { whole: ClientWhole; reload: () => Promise<unknown>; onMade: (v: VersionInfo) => void }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const brands = useBrands()
  const space = brands.space(whole.space_id)
  const canWrite = whole.role === 'write' || whole.role === 'manage'
  const { busy, problem, run } = useAction()
  return (
    <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-4xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-wrap items-center gap-4">
          <span className="grid h-16 w-16 shrink-0 place-items-center rounded-2xl text-2xl font-bold text-white" style={{ background: whole.color }} aria-hidden>
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
      </div>
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
  const { busy, problem, run } = useAction()
  // Kept in nexsuite: name, sector, contact and colour are changed there; the note is nexbrand's.
  const kept = whole.managed
  const change = kept ? { note } : { name, sector, contact, note, ...(CLIENT_COLORS.includes(color) ? { color } : {}) }
  return (
    <Dialog title={t('client.edit')} onClose={onClose} medium>
      <div className="space-y-3">
        {kept && <p className="rounded-lg border border-accent-500/30 bg-accent-500/8 px-3 py-2 text-xs text-mist-300">{t('client.keptInSuite')}</p>}
        {kept ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-mist-500">{t('client.name')}</dt>
            <dd>{whole.name}</dd>
            <dt className="text-mist-500">{t('client.sector')}</dt>
            <dd>{whole.sector || '–'}</dd>
            <dt className="text-mist-500">{t('client.contact')}</dt>
            <dd>{whole.contact || '–'}</dd>
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

function NewVersion({ whole, start, onClose, onMade }: { whole: ClientWhole; start: VersionInfo; onClose: () => void; onMade: (v: VersionInfo) => void }) {
  const { t } = useTranslation()
  const [label, setLabel] = useState('')
  const [source, setSource] = useState(start.id)
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('client.newVersion')} onClose={onClose} medium>
      <div className="space-y-3">
        <p className="text-sm text-mist-400">{t('client.newVersionText')}</p>
        <Input label={t('client.versionName')} value={label} onChange={setLabel} placeholder={t('client.versionNameHint')} />
        <Select label={t('client.startFrom')} value={source} onChange={setSource} options={[...whole.versions.map((v) => ({ value: v.id, label: v.label })), { value: '', label: t('client.empty') }]} />
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} disabled={!label.trim()} onClick={() => void run(async () => onMade(await clientsApi.newVersion(whole.id, { label, source: source || undefined })))}>
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
  const [making, setMaking] = useState(false)
  const published = whole.versions.filter((v) => v.status === 'published')
  const current = published[published.length - 1]
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-sm text-mist-500">{t('projects.text')}</p>
        {canWrite && (
          <button type="button" className="nc-btn nc-btn-accent" onClick={() => setMaking(true)}>
            <Plus className="h-4 w-4" /> {t('projects.new')}
          </button>
        )}
      </div>
      {!whole.projects.length && <p className="text-sm text-mist-500">{t('projects.none')}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {whole.projects.map((p) => {
          const base = whole.versions.find((v) => v.id === p.version_id)
          const behind = base?.status === 'published' && current && base.valid_from < current.valid_from
          return (
            <Link key={p.id} to={`/c/${whole.id}/p/${p.id}`} className="rounded-2xl border border-ink-700 bg-ink-900 p-4 hover:border-ink-600">
              <div className="flex items-center gap-2">
                <FolderKanban className="h-4 w-4 text-accent-400" />
                <span className="mr-auto font-semibold">{p.name}</span>
                {base?.status === 'draft' ? (
                  <span className="rounded-full border border-magenta-500/50 px-2 py-0.5 text-[11px] text-magenta-text">{t('projects.onDraft')}</span>
                ) : behind ? (
                  <span className="rounded-full border border-gelb-500/50 px-2 py-0.5 text-[11px] text-gelb-text">{t('projects.on', { label: base?.label })}</span>
                ) : (
                  <span className="rounded-full border border-ok-500/40 px-2 py-0.5 text-[11px] text-ok-500">{t('projects.upToDate')}</span>
                )}
              </div>
              <p className="mt-1 text-sm text-mist-500">
                {t('projects.builds', { label: base?.label ?? '?' })} {p.own.length ? t('projects.own', { count: p.own.length }) : t('projects.noOwn')}
              </p>
            </Link>
          )
        })}
      </div>
      {making && <NewProject whole={whole} onClose={() => setMaking(false)} onMade={() => (setMaking(false), void reload())} />}
    </div>
  )
}

function NewProject({ whole, onClose, onMade }: { whole: ClientWhole; onClose: () => void; onMade: () => void }) {
  const { t } = useTranslation()
  const published = whole.versions.filter((v) => v.status === 'published')
  const [name, setName] = useState('')
  const [version, setVersion] = useState((published[published.length - 1] ?? whole.versions[0]).id)
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('projects.new')} onClose={onClose} medium>
      <div className="space-y-3">
        <Input label={t('projects.name')} value={name} onChange={setName} placeholder={t('projects.nameHint')} />
        <Select label={t('projects.version')} value={version} onChange={setVersion} options={whole.versions.map((v) => ({ value: v.id, label: v.status === 'draft' ? `${v.label} (${t('client.draft')})` : v.label }))} />
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} disabled={!name.trim()} onClick={() => void run(async () => (await clientsApi.newProject(whole.id, { name, version_id: version }), onMade()))}>
            {t('projects.make')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
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

