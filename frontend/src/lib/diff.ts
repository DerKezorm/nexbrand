/**
 * What changed from one design set to another, in every part: colours, fonts, logos, the type scale, rules, examples and
 * the dark mode. The same as `backend/app/services/diff.py`; `diff.test.ts` holds both to `diff_cases.json`.
 *
 * Items are matched by what names them: a colour, a font and a step by their name, a logo by its id, an example by its
 * file. A rule has no name: one reworded counts as one removed and one added.
 */

export const DIFF_PARTS = ['colors', 'fonts', 'logos', 'scale', 'rules', 'samples', 'dark'] as const
export type DiffPart = (typeof DIFF_PARTS)[number]

export const DIFF_FIELDS: Record<Exclude<DiffPart, 'rules'>, string[]> = {
  colors: ['hex', 'role', 'pantone', 'cmyk', 'note'],
  fonts: ['role', 'weights', 'italic', 'license', 'license_note', 'source', 'catalog', 'files', 'fallback'],
  logos: ['name', 'media', 'files', 'wordmark', 'fg', 'accent', 'ground', 'compact', 'min_width', 'clear_space'],
  scale: ['use', 'size', 'weight', 'font', 'line_height'],
  samples: ['name'],
  dark: ['ground', 'surface', 'text', 'muted', 'primary', 'on_primary'],
}

type Listed = Exclude<DiffPart, 'rules' | 'dark'>
const NAME: Record<Listed, string> = { colors: 'name', fonts: 'family', logos: 'name', scale: 'name', samples: 'name' }
const KEY: Record<Listed, string> = { colors: 'name', fonts: 'family', logos: 'id', scale: 'name', samples: 'media' }

export type FieldChange = { field: string; from: unknown; to: unknown }
export type Change = { part: DiffPart; change: 'added' | 'removed' | 'changed'; name: string; fields: FieldChange[]; rule?: unknown }

type Obj = Record<string, unknown>

/** A value as compared: empty (nothing, "", [], {}, false) is nothing, colours in capitals, objects without their
 * empty fields and with their keys in order. */
export function canon(value: unknown): unknown {
  if (Array.isArray(value)) return value.length ? value.map(canon) : null
  if (value && typeof value === 'object') {
    const out: Obj = {}
    for (const key of Object.keys(value).sort()) {
      const item = canon((value as Obj)[key])
      if (item !== null) out[key] = item
    }
    return Object.keys(out).length ? out : null
  }
  if (value === false || value === '' || value === null || value === undefined) return null
  if (typeof value === 'string' && value.startsWith('#') && (value.length === 4 || value.length === 7)) return value.toUpperCase()
  return value
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

function keyed(part: Listed, items: unknown[]): [string, Obj][] {
  const seen = new Map<string, number>()
  const out: [string, Obj][] = []
  for (const item of items) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue
    const key = String((item as Obj)[KEY[part]] ?? '').toLowerCase()
    const n = (seen.get(key) ?? 0) + 1
    seen.set(key, n)
    out.push([n === 1 ? key : `${key}#${n}`, item as Obj])
  }
  return out
}

function fields(part: Exclude<DiffPart, 'rules'>, a: Obj, b: Obj): FieldChange[] {
  return DIFF_FIELDS[part].filter((field) => !same(canon(a[field]), canon(b[field]))).map((field) => ({ field, from: canon(a[field]), to: canon(b[field]) }))
}

/** Every change from the set `a` to the set `b`, part by part in the order of `DIFF_PARTS`: within a part the items of
 * `a` in their order (changed or removed), then the items only `b` has. */
export function diffSets(aIn: unknown, bIn: unknown): Change[] {
  const a = (aIn && typeof aIn === 'object' ? aIn : {}) as Obj
  const b = (bIn && typeof bIn === 'object' ? bIn : {}) as Obj
  const out: Change[] = []
  for (const part of DIFF_PARTS) {
    if (part === 'dark') {
      const before = (a.dark || null) as Obj | null
      const after = (b.dark || null) as Obj | null
      if (!before && after) out.push({ part, change: 'added', name: '', fields: [] })
      else if (before && !after) out.push({ part, change: 'removed', name: '', fields: [] })
      else if (before && after) {
        const changed = fields(part, before, after)
        if (changed.length) out.push({ part, change: 'changed', name: '', fields: changed })
      }
      continue
    }
    if (part === 'rules') {
      const left = ((a.rules as unknown[]) ?? []).map(canon)
      const right = ((b.rules as unknown[]) ?? []).map(canon)
      const rest = [...right]
      const take = (rule: unknown) => {
        const at = rest.findIndex((x) => same(x, rule))
        if (at < 0) return false
        rest.splice(at, 1)
        return true
      }
      for (const rule of left) if (!take(rule)) out.push({ part, change: 'removed', name: '', rule, fields: [] })
      for (const rule of right) if (take(rule)) out.push({ part, change: 'added', name: '', rule, fields: [] })
      continue
    }
    const before = keyed(part, (a[part] as unknown[]) ?? [])
    const after = new Map(keyed(part, (b[part] as unknown[]) ?? []))
    const known = new Set<string>()
    for (const [key, item] of before) {
      known.add(key)
      const other = after.get(key)
      if (!other) {
        out.push({ part, change: 'removed', name: String(item[NAME[part]] ?? ''), fields: [] })
        continue
      }
      const changed = fields(part, item, other)
      if (changed.length) out.push({ part, change: 'changed', name: String(other[NAME[part]] ?? ''), fields: changed })
    }
    for (const [key, item] of after) if (!known.has(key)) out.push({ part, change: 'added', name: String(item[NAME[part]] ?? ''), fields: [] })
  }
  return out
}
