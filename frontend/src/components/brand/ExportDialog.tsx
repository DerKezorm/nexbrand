import { Copy, Download } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { clientsApi, sharesApi, type ExportFormat } from '../../api/client'
import { copyText } from '../../lib/copy'
import { TabRow } from '../../pages/settings/ui'
import { Dialog } from '../Dialog'

/** Where the code comes from: a version (or a project) in the app, or a public page by its token. */
export type CodeSource = { client: string; version?: string; project?: string } | { page: string }

function load(source: CodeSource, format: ExportFormat): Promise<string> {
  return 'page' in source ? sharesApi.codeText(source.page, format) : clientsApi.exportText(source.client, { format, version: source.version, project: source.project })
}

function downloadUrl(source: CodeSource, format: ExportFormat): string {
  return 'page' in source ? sharesApi.codeUrl(source.page, format) : clientsApi.exportUrl(source.client, { format, version: source.version, project: source.project })
}

/** A version, a project or a public page as code to copy or download: CSS, Tailwind 4, SCSS, design tokens. Written
 * by the server, so a program over the API and a developer on a public page get the very same text. */
export function ExportDialog({ source, title, onClose }: { source: CodeSource; title: string; onClose: () => void }) {
  const { t } = useTranslation()
  const [format, setFormat] = useState<ExportFormat>('css')
  const [text, setText] = useState('')
  const [copied, setCopied] = useState(false)
  const key = JSON.stringify(source)
  useEffect(() => {
    let live = true
    load(JSON.parse(key) as CodeSource, format)
      .then((value) => live && setText(value))
      .catch(() => live && setText(''))
    return () => {
      live = false
    }
  }, [key, format])
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
          <a className="nc-btn nc-btn-accent" href={downloadUrl(source, format)}>
            <Download className="h-4 w-4" /> {t('export.download')}
          </a>
        </div>
      </div>
    </Dialog>
  )
}
