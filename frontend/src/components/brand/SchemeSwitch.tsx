/** Light or dark for a sample page: only there when the set has a dark mode. */
import { Moon, Sun } from 'lucide-react'
import { useTranslation } from 'react-i18next'

export function SchemeSwitch({ dark, onChange }: { dark: boolean; onChange: (dark: boolean) => void }) {
  const { t } = useTranslation()
  return (
    <div className="inline-flex rounded-full border border-ink-700 bg-ink-900 p-0.5 text-xs" role="group" aria-label={t('dark.switch')}>
      {([false, true] as const).map((on) => (
        <button
          key={String(on)}
          type="button"
          aria-pressed={dark === on}
          aria-label={on ? t('dark.showDark') : t('dark.showLight')}
          onClick={() => onChange(on)}
          className={'inline-flex items-center gap-1 rounded-full px-2.5 py-1 ' + (dark === on ? 'bg-accent-500/20 text-mist-100' : 'text-mist-400 hover:text-mist-100')}
        >
          {on ? <Moon className="h-3.5 w-3.5" /> : <Sun className="h-3.5 w-3.5" />} {on ? t('dark.dark') : t('dark.light')}
        </button>
      ))}
    </div>
  )
}
