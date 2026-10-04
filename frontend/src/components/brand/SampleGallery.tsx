/** The agency's own designs of a direction, large, one at a time: what a client really judges. */
import { ChevronLeft, ChevronRight, ExternalLink, FileText } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { FileInfo } from '../../api/client'
import type { Sample } from '../../lib/brand'

const PICTURES = new Set(['svg', 'png', 'jpeg', 'webp', 'gif', 'avif'])

export function SampleGallery({
  samples,
  files,
  fileUrl,
  index,
  onIndex,
  counts = {},
}: {
  samples: Sample[]
  files: Record<string, FileInfo>
  fileUrl: (id: string) => string
  index: number
  onIndex: (i: number) => void
  /** Comments per example (media id), shown on its thumbnail. */
  counts?: Record<string, number>
}) {
  const { t } = useTranslation()
  const shown = samples[Math.min(index, samples.length - 1)]
  if (!shown) return null
  const info = files[shown.media]
  const picture = !!info && PICTURES.has(info.kind)
  const step = (by: number) => onIndex((index + by + samples.length) % samples.length)
  return (
    <div className="space-y-2" data-testid="sample-gallery">
      <div className="relative grid min-h-64 place-items-center overflow-hidden rounded-xl border border-ink-700 bg-ink-950">
        {picture ? (
          <img src={fileUrl(shown.media)} alt={shown.name} className="max-h-[75vh] w-full object-contain" />
        ) : (
          <a href={fileUrl(shown.media)} target="_blank" rel="noreferrer" className="flex flex-col items-center gap-2 p-10 text-mist-300 hover:text-mist-100">
            <FileText className="h-12 w-12" />
            <span className="inline-flex items-center gap-1.5 text-sm font-semibold">
              <ExternalLink className="h-4 w-4" /> {t('gallery.open', { kind: (info?.kind ?? '').toUpperCase() })}
            </span>
          </a>
        )}
        {samples.length > 1 && (
          <>
            <button type="button" onClick={() => step(-1)} aria-label={t('gallery.previous')} className="absolute top-1/2 left-2 -translate-y-1/2 rounded-full bg-black/55 p-2 text-white hover:bg-black/75">
              <ChevronLeft className="h-5 w-5" />
            </button>
            <button type="button" onClick={() => step(1)} aria-label={t('gallery.next')} className="absolute top-1/2 right-2 -translate-y-1/2 rounded-full bg-black/55 p-2 text-white hover:bg-black/75">
              <ChevronRight className="h-5 w-5" />
            </button>
          </>
        )}
      </div>
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="font-semibold text-mist-100">{shown.name}</span>
        {samples.length > 1 && <span className="text-xs text-mist-500">{t('gallery.of', { at: index + 1, count: samples.length })}</span>}
      </div>
      {samples.length > 1 && (
        <div className="flex gap-2 overflow-x-auto pb-1" role="tablist" aria-label={t('gallery.all')}>
          {samples.map((s, i) => {
            const kind = files[s.media]?.kind ?? ''
            return (
              <button
                key={s.media + i}
                type="button"
                role="tab"
                aria-selected={i === index}
                aria-label={s.name}
                onClick={() => onIndex(i)}
                className={'relative h-16 w-24 shrink-0 overflow-hidden rounded-lg border bg-ink-900 ' + (i === index ? 'border-accent-400 ring-1 ring-accent-400' : 'border-ink-700 opacity-75 hover:opacity-100')}
              >
                {PICTURES.has(kind) ? <img src={fileUrl(s.media)} alt="" className="h-full w-full object-cover" /> : <FileText className="mx-auto h-6 w-6 text-mist-500" />}
                {(counts[s.media] ?? 0) > 0 && <span className="absolute top-1 right-1 rounded-full bg-magenta-500 px-1.5 text-[10px] font-semibold text-white">{counts[s.media]}</span>}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
