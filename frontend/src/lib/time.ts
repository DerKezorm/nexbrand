/** "5 minutes ago", "yesterday" in the language of the app. */
export function ago(time: number, lang: string): string {
  const seconds = Math.round((time - Date.now()) / 1000)
  const format = new Intl.RelativeTimeFormat(lang, { numeric: 'auto' })
  const abs = Math.abs(seconds)
  if (abs < 60) return format.format(0, 'minute')
  if (abs < 3600) return format.format(Math.round(seconds / 60), 'minute')
  if (abs < 86400) return format.format(Math.round(seconds / 3600), 'hour')
  if (abs < 86400 * 30) return format.format(Math.round(seconds / 86400), 'day')
  return new Date(time).toLocaleDateString(lang)
}

/** A moment as the app writes it everywhere: the day as the lists show days (4.10.2026), with hours and minutes, no
 * seconds (G11: three ways to write a moment before, one with seconds). */
export function moment(value: string | number | Date, lang: string): string {
  return new Date(value).toLocaleString(lang, { day: 'numeric', month: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
