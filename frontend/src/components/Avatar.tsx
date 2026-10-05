import type { CSSProperties } from 'react'

import { avatarUrl } from '../api/client'
import { personColor } from '../lib/person'

/** A person as their picture, or a round letter in their colour, as nexlore shows accounts. */
export function Avatar({
  person,
  className = 'h-8 w-8 text-sm',
  ring = false,
}: {
  person: { id: number; name: string; display_name?: string; avatar: string | null }
  className?: string
  ring?: boolean
}) {
  const shown = person.display_name || person.name
  const url = avatarUrl(person)
  const classes = 'grid shrink-0 place-items-center overflow-hidden rounded-full font-semibold ' + (ring ? 'ring-2 ring-ink-950 ' : '') + className
  if (url) return <img src={url} alt="" title={shown} className={classes + ' object-cover'} />
  const color = personColor(person.name)
  return (
    <span title={shown} className={classes + ' nc-tint'} style={{ '--tint': color } as CSSProperties}>
      {(shown.trim()[0] ?? '?').toUpperCase()}
    </span>
  )
}
