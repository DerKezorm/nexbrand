/** A project: the version it builds on, kept until somebody lifts it, and the colours that are its own. */
import { ArrowUpCircle, Download, GitCompare, Palette, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { clientsApi, mediaUrl, type ClientWhole } from '../api/client'
import { DiffView } from '../components/brand/DiffView'
import { ExportDialog } from '../components/brand/ExportDialog'
import { ColorsEditor } from '../components/brand/SetEditor'
import { SetView } from '../components/brand/SetView'
import { Dialog } from '../components/Dialog'
import { projectColors, type BrandColor } from '../lib/brand'
import { Button, Confirm, Feedback, Input, useAction } from './settings/ui'

export function ProjectPage() {
  const { id = '', pid = '' } = useParams()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [whole, setWhole] = useState<ClientWhole | null>(null)
  const [files, setFiles] = useState({})
  const [dialog, setDialog] = useState<'lift' | 'own' | 'export' | 'delete' | 'rename' | null>(null)
  const load = useCallback(() => Promise.all([clientsApi.read(id), clientsApi.files(id)]).then(([c, f]) => (setWhole(c), setFiles(f))), [id])
  useEffect(() => void load().catch(() => setWhole(null)), [load])
  const project = whole?.projects.find((p) => p.id === pid)
  if (!whole) return <main className="flex-1" aria-busy="true" />
  if (!project)
    return (
      <main className="mx-auto max-w-xl px-4 py-16 text-center">
        <p className="text-mist-300">{t('projects.missing')}</p>
        <Link to={`/c/${whole.id}`} className="nc-btn nc-btn-ghost mt-4">
          {whole.name}
        </Link>
      </main>
    )
  const base = whole.versions.find((v) => v.id === project.version_id)!
  const published = whole.versions.filter((v) => v.status === 'published')
  const current = published[published.length - 1]
  const behind = base.status === 'published' && current && base.valid_from < current.valid_from
  const canWrite = whole.role === 'write' || whole.role === 'manage'
  const colors = projectColors(base.data, project.own)
  return (
    <main className="nc-scroll min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6 sm:py-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div className="text-xs text-mist-500">
              <Link to="/" className="hover:text-mist-200">
                {t('clients.title')}
              </Link>{' '}
              /{' '}
              <Link to={`/c/${whole.id}?tab=projects`} className="hover:text-mist-200">
                {whole.name}
              </Link>
            </div>
            <h1 className="text-2xl font-bold tracking-tight">{project.name}</h1>
            <p className="mt-1 max-w-2xl text-sm text-mist-500">{t('projects.pageText', { label: base.label })}</p>
            {project.note && <p className="mt-1 text-sm text-mist-400">{project.note}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            {canWrite && (
              <>
                <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setDialog('rename')}>
                  {t('projects.rename')}
                </button>
                <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setDialog('own')}>
                  <Palette className="h-4 w-4" /> {t('projects.ownColors')}
                </button>
              </>
            )}
            <button type="button" className="nc-btn nc-btn-accent" onClick={() => setDialog('export')}>
              <Download className="h-4 w-4" /> {t('client.export')}
            </button>
          </div>
        </div>
        {behind && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-gelb-500/40 bg-gelb-500/8 px-4 py-3 text-sm text-mist-200">
            <span className="flex-1">{t('projects.behind', { label: base.label, current: current.label })}</span>
            <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setDialog('lift')}>
              <GitCompare className="h-4 w-4" /> {t('projects.whatChanges')}
            </button>
          </div>
        )}
        {base.status === 'draft' && <div className="rounded-xl border border-magenta-500/40 bg-magenta-500/8 px-4 py-3 text-sm text-mist-200">{t('projects.onDraftText', { label: base.label })}</div>}
        <SetView set={base.data} colors={colors} fileUrl={(m) => mediaUrl(m)} files={files} />
        {canWrite && (
          <div className="flex justify-end pt-4">
            <button type="button" className="nc-btn nc-btn-ghost text-mist-500" onClick={() => setDialog('delete')}>
              <Trash2 className="h-4 w-4" /> {t('projects.delete')}
            </button>
          </div>
        )}
      </div>
      {dialog === 'export' && <ExportDialog client={whole.id} project={project.id} title={`${whole.name}, ${project.name}`} onClose={() => setDialog(null)} />}
      {dialog === 'lift' && current && (
        <Dialog title={t('projects.liftTitle', { from: base.label, to: current.label })} onClose={() => setDialog(null)} wide>
          <DiffView a={base} b={current} />
          {project.own.length > 0 && <p className="mt-3 text-sm text-mist-400">{t('projects.ownStay', { names: project.own.map((o) => o.name).join(', ') })}</p>}
          <div className="mt-4 flex flex-wrap justify-end gap-2">
            <button type="button" className="nc-btn nc-btn-ghost" onClick={() => setDialog(null)}>
              {t('projects.stay', { label: base.label })}
            </button>
            {canWrite && (
              <button type="button" className="nc-btn nc-btn-accent" onClick={() => void clientsApi.changeProject(whole.id, project.id, { version_id: current.id }).then(() => (setDialog(null), load()))}>
                <ArrowUpCircle className="h-4 w-4" /> {t('projects.lift', { label: current.label })}
              </button>
            )}
          </div>
        </Dialog>
      )}
      {dialog === 'own' && <OwnColors whole={whole} own={project.own} baseColors={base.data.colors} onClose={() => setDialog(null)} onSave={async (own) => (await clientsApi.changeProject(whole.id, project.id, { own }), setDialog(null), await load())} />}
      {dialog === 'rename' && <Rename name={project.name} note={project.note} onClose={() => setDialog(null)} onSave={async (name, note) => (await clientsApi.changeProject(whole.id, project.id, { name, note }), setDialog(null), await load())} />}
      {dialog === 'delete' && (
        <Confirm title={t('projects.delete')} text={t('projects.deleteText', { name: project.name })} confirm={t('projects.delete')} danger onCancel={() => setDialog(null)} onConfirm={async () => (await clientsApi.deleteProject(whole.id, project.id), navigate(`/c/${whole.id}?tab=projects`))} />
      )}
    </main>
  )
}

function OwnColors({ own, baseColors, onClose, onSave }: { whole: ClientWhole; own: BrandColor[]; baseColors: BrandColor[]; onClose: () => void; onSave: (own: BrandColor[]) => Promise<unknown> }) {
  const { t } = useTranslation()
  const [value, setValue] = useState(own)
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('projects.ownColors')} onClose={onClose} wide>
      <p className="mb-3 text-sm text-mist-400">{t('projects.ownText', { names: baseColors.map((c) => c.name).join(', ') })}</p>
      <ColorsEditor colors={value} onChange={setValue} />
      <Feedback problem={problem} />
      <div className="mt-4 flex justify-end gap-2">
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button accent busy={busy} onClick={() => void run(() => onSave(value))}>
          {t('common.save')}
        </Button>
      </div>
    </Dialog>
  )
}

function Rename({ name, note, onClose, onSave }: { name: string; note: string; onClose: () => void; onSave: (name: string, note: string) => Promise<unknown> }) {
  const { t } = useTranslation()
  const [value, setValue] = useState(name)
  const [text, setText] = useState(note)
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('projects.rename')} onClose={onClose} medium>
      <div className="space-y-3">
        <Input label={t('projects.name')} value={value} onChange={setValue} />
        <Input label={t('projects.note')} value={text} onChange={setText} />
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} disabled={!value.trim()} onClick={() => void run(() => onSave(value, text))}>
            {t('common.save')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
