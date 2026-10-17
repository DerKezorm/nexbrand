/** Where in a design set a value the server refused sits (`where` of `invalid_set`, such as `colors.1.hex`), told
 * with the name of the item: "colour “Accent”, field value" instead of "a value of this CI is wrong". */
import type { BrandSet } from './brand'

export type Place = { part: string; index: number | null; name: string; field: string; twice: boolean }

const NAME_OF: Record<string, string> = { colors: 'name', fonts: 'family', logos: 'name', scale: 'name', samples: 'name' }

export function placeOf(where: string, set: BrandSet): Place | null {
  const [part, second, ...rest] = where.split('.')
  if (!part) return null
  const index = second !== undefined && /^\d+$/.test(second) ? Number(second) : null
  const field = index === null ? (second ?? '') : (rest[0] ?? '')
  const items = (set as unknown as Record<string, unknown>)[part]
  const item = index !== null && Array.isArray(items) ? (items[index] as Record<string, unknown> | undefined) : undefined
  const name = item && NAME_OF[part] ? String(item[NAME_OF[part]] ?? '').trim() : ''
  // Two colours of the same name: the server names the second.
  const twice = part === 'colors' && field === 'name' && !!name && (items as { name?: string }[]).filter((c) => (c.name ?? '').trim().toLowerCase() === name.toLowerCase()).length > 1
  return { part, index, name, field, twice }
}
