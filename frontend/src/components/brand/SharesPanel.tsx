import { Eye, Globe, Lock, Plus, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { sharesApi, type ShareInfo, type VersionInfo } from '../../api/client'
import { Button, CopyLink, Feedback, Input, Select, useAction } from '../../pages/settings/ui'
import { useAuth } from '../../state/auth'
import { Dialog } from '../Dialog'

/** The public pages of a client: for a printer, a photographer, the client. Managers make them. */
export function SharesPanel({ client, versions, canManage }: { client: string; versions: VersionInfo[]; canManage: boolean }) {
  const { t, i18n } = useTranslation()
  const { me } = useAuth()
  const [shares, setShares] = useState<ShareInfo[]>([])
  const [making, setMaking] = useState(false)
  const load = useCallback(() => void sharesApi.list(client).then(setShares).catch(() => setShares([])), [client])
  useEffect(load, [load])
  const published = versions.filter((v) => v.status === 'published')
  const allowed = me?.shares_allowed !== false
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-2xl text-sm text-mist-500">{t('shares.text')}</p>
        {canManage && allowed && published.length > 0 && (
          <button type="button" className="nc-btn nc-btn-accent" onClick={() => setMaking(true)}>
            <Plus className="h-4 w-4" /> {t('shares.new')}
          </button>
        )}
      </div>
      {!allowed && <p className="rounded-xl border border-warn-500/40 bg-warn-500/8 px-3 py-2 text-sm text-mist-200">{t('shares.off')}</p>}
      {allowed && !published.length && <p className="text-sm text-mist-500">{t('shares.needPublished')}</p>}
      {shares.map((s) => (
        <article key={s.id} className="space-y-2 rounded-xl border border-ink-700 bg-ink-900 p-3">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Globe className="h-4 w-4 text-accent-400" />
            <b className="mr-auto">{s.label || t('shares.unnamed')}</b>
            <span className="text-xs text-mist-500">
              {s.version_label ? t('shares.fixed', { label: s.version_label }) : t('shares.current')} · {s.expires_at ? t('shares.until', { date: new Date(s.expires_at).toLocaleDateString(i18n.language) }) : t('shares.forever')} · {t('shares.views', { count: s.views })}
            </span>
            {s.password && <Lock className="h-3.5 w-3.5 text-mist-500" aria-label={t('shares.guarded')} />}
            <a href={new URL(s.link).pathname} target="_blank" rel="noreferrer" className="nc-btn nc-btn-ghost !px-2.5 !py-0.5 !text-xs">
              <Eye className="h-3.5 w-3.5" /> {t('shares.look')}
            </a>
            {canManage && (
              <button type="button" aria-label={t('shares.remove')} className="rounded-full p-1.5 text-mist-500 hover:text-bad-500" onClick={() => void sharesApi.remove(s.id).then(load)}>
                <Trash2 className="h-4 w-4" />
              </button>
            )}
          </div>
          <CopyLink value={s.link} label={t('shares.link')} />
        </article>
      ))}
      {making && <NewShare client={client} versions={published} onClose={() => setMaking(false)} onMade={() => (setMaking(false), load())} />}
    </div>
  )
}

function NewShare({ client, versions, onClose, onMade }: { client: string; versions: VersionInfo[]; onClose: () => void; onMade: () => void }) {
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
          <Button accent busy={busy} onClick={() => void run(async () => (await sharesApi.create(client, { label, version_id: fixed || null, days: days ? Number(days) : null, password }), onMade()))}>
            {t('shares.make')}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
