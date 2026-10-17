import { Eye, Globe, Lock, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { sharesApi, type ShareInfo, type VersionInfo } from '../../api/client'
import { linkRights } from '../../lib/review'
import { Button, Confirm, CopyLink, Feedback, Input, Select, useAction } from '../../pages/settings/ui'
import { useAuth } from '../../state/auth'
import { Dialog } from '../Dialog'

/** Public pages and reviews are off: says so, and where they are switched on (a link for the operator). */
export function SharesOff() {
  const { t } = useTranslation()
  const { me } = useAuth()
  return (
    <p className="rounded-xl border border-warn-500/40 bg-warn-500/8 px-3 py-2 text-sm text-mist-200">
      {me?.role === 'operator' ? (
        <>
          {t('shares.offYou')}{' '}
          <Link to="/settings?tab=server&sub=shares" className="text-accent-400 hover:underline">
            {t('shares.offWhere')}
          </Link>
        </>
      ) : (
        t('shares.offAsk')
      )}
    </p>
  )
}

/** The public pages of a client: for a printer, a photographer, a developer, the client. From write up a person makes
 *  one and sees the links; readers see that there are pages, not their addresses. */
/** `project`: the pages of one project; none: of the client's own design set. */
export function SharesPanel({ client, versions, role, project }: { client: string; versions: VersionInfo[]; role: 'read' | 'write' | 'manage' | null; project?: string }) {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [shares, setShares] = useState<ShareInfo[]>([])
  const [making, setMaking] = useState(false)
  // Ending a page asks first, with the family's dialog: whoever has the link sees nothing there afterwards.
  const [ending, setEnding] = useState<ShareInfo | null>(null)
  const load = useCallback(() => void sharesApi.list(client).then((all) => setShares(all.filter((s) => (s.project_id ?? undefined) === project))).catch(() => setShares([])), [client, project])
  useEffect(load, [load])
  const published = versions.filter((v) => v.status === 'published')
  const allowed = me?.shares_allowed !== false
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-sm text-mist-500">{t('shares.text')}</p>
        {linkRights(role, false).make && allowed && published.length > 0 && (
          <button type="button" className="nc-btn nc-btn-accent" onClick={() => setMaking(true)}>
            <Plus className="h-4 w-4" /> {t('shares.new')}
          </button>
        )}
      </div>
      {!allowed && <SharesOff />}
      {allowed && !published.length && <p className="text-sm text-mist-500">{t('shares.needPublished')}</p>}
      {shares.map((s) => (
        <article key={s.id} className="space-y-2 rounded-xl border border-ink-700 bg-ink-900 p-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Globe className="h-4 w-4 text-accent-400" />
            <b className="mr-auto">{s.label || t('shares.unnamed')}</b>
            <span className="text-xs text-mist-500">
              {s.version_label ? t('shares.fixed', { label: s.version_label }) : t('shares.current')} · {s.expires_at ? t('shares.until', { date: new Date(s.expires_at).toLocaleDateString(i18n.language) }) : t('shares.forever')} · {t('shares.views', { count: s.views })}
            </span>
            {/* In words, not a small lock alone. */}
            {s.password && (
              <span className="inline-flex items-center gap-1 rounded-full border border-ink-600 px-2 py-0.5 text-[11px] text-mist-400" data-testid="share-guarded" title={t('shares.guardedHint')}>
                <Lock className="h-3 w-3" aria-hidden /> {t('shares.guarded')}
              </span>
            )}
            {s.link && (
              <a href={new URL(s.link).pathname} target="_blank" rel="noreferrer" className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs">
                <Eye className="h-3.5 w-3.5" /> {t('shares.look')}
              </a>
            )}
            {linkRights(role, s.mine).end && (
              <button type="button" aria-label={t('shares.removeThis', { name: s.label || t('shares.unnamed') })} title={t('shares.remove')} className="rounded-full p-1.5 text-mist-500 hover:text-bad-500" onClick={() => setEnding(s)}>
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
          {s.link ? <CopyLink value={s.link} label={t('shares.link')} /> : <p className="text-xs text-mist-500">{t('shares.linkWriters')}</p>}
        </article>
      ))}
      {ending && (
        <Confirm
          title={t('shares.removeTitle', { name: ending.label || t('shares.unnamed') })}
          text={t('shares.removeText')}
          confirm={t('shares.remove')}
          danger
          onCancel={() => setEnding(null)}
          onConfirm={async () => {
            await sharesApi.remove(ending.id)
            setEnding(null)
            load()
          }}
        />
      )}
      {making && <NewShare client={client} project={project} versions={published} onClose={() => setMaking(false)} onMade={() => (setMaking(false), load())} />}
    </div>
  )
}

function NewShare({ client, project, versions, onClose, onMade }: { client: string; project?: string; versions: VersionInfo[]; onClose: () => void; onMade: () => void }) {
  const { t } = useTranslation()
  const [label, setLabel] = useState('')
  const [fixed, setFixed] = useState('')
  const [days, setDays] = useState('30')
  const [password, setPassword] = useState('')
  const { busy, problem, run } = useAction()
  return (
    <Dialog title={t('shares.new')} onClose={onClose} medium>
      <div className="space-y-3">
        <Input label={t('shares.for')} value={label} onChange={setLabel} placeholder={t('shares.forHint')} />
        <Select
          label={t('shares.which')}
          value={fixed}
          onChange={setFixed}
          options={[{ value: '', label: t('shares.alwaysCurrent') }, ...versions.map((v) => ({ value: v.id, label: t('shares.fixedOn', { label: v.label }) }))]}
        />
        <Select
          label={t('shares.runs')}
          value={days}
          onChange={setDays}
          options={[
            { value: '7', label: t('shares.days', { count: 7 }) },
            { value: '30', label: t('shares.days', { count: 30 }) },
            { value: '90', label: t('shares.days', { count: 90 }) },
            { value: '365', label: t('shares.days', { count: 365 }) },
            { value: '', label: t('shares.forever') },
          ]}
        />
        <Input label={t('shares.password')} value={password} onChange={setPassword} type="password" hint={t('shares.passwordHint')} autoComplete="new-password" />
        <p className="flex items-center gap-2 text-xs text-mist-500">
          <Lock className="h-3.5 w-3.5" /> {t('shares.internalHidden')}
        </p>
        <Feedback problem={problem} />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button accent busy={busy} onClick={() => void run(async () => (await sharesApi.create(client, { label, version_id: fixed || null, project_id: project ?? null, days: days ? Number(days) : null, password }), onMade()))}>
            {t('shares.make')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
