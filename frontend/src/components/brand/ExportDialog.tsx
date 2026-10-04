import { Copy, Download } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { clientsApi, type ExportFormat } from '../../api/client'
import { copyText } from '../../lib/copy'
import { TabRow } from '../../pages/settings/ui'
import { Dialog } from '../Dialog'

/** A version or a project as code to copy or download: CSS, Tailwind 4, SCSS, design tokens. Written by the server,
 * so a program over the API gets the very same text. */
export function ExportDialog({ client, version, project, title, onClose }: { client: string; version?: string; project?: string; title: string; onClose: () => void }) {
  const { t } = useTranslation()
  const [format, setFormat] = useState<ExportFormat>('css')
  const [text, setText] = useState('')
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    let live = true
    clientsApi
      .exportText(client, { format, version, project })
      .then((value) => live && setText(value))
      .catch(() => live && setText(''))
    return () => {
      live = false
    }
  }, [client, format, version, project])
  return (
    <Dialog title={t('export.title', { name: title })} onClose={onClose} wide>
      <TabRow
        tabs={[
          { value: 'css', label: t('export.css') },
          { value: 'tailwind', label: 'Tailwind 4' },
          { value: 'scss', label: 'SCSS' },
          { value: 'json', label: t('export.json') },
        ]}
        active={format}
        onChange={setFormat}
      />
      <pre className="nc-scroll mt-4 max-h-80 overflow-auto rounded-xl border border-ink-700 bg-ink-950 p-4 font-mono text-xs leading-relaxed text-mist-200" aria-label={t('export.code')}>
        {text || '…'}
      </pre>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
        <p className="max-w-sm text-xs text-mist-500">{t('export.note')}</p>
        <div className="flex gap-2">
          <button type="button" className="nc-btn nc-btn-ghost" onClick={() => void copyText(text).then((ok) => (setCopied(ok), window.setTimeout(() => setCopied(false), 1500)))}>
            <Copy className="h-4 w-4" /> {copied ? t('common.copied') : t('common.copy')}
          </button>
          <a className="nc-btn nc-btn-accent" href={clientsApi.exportUrl(client, { format, version, project })}>
            <Download className="h-4 w-4" /> {t('export.download')}
          </a>
        </div>
      </div>
    </Dialog>
  )
}
