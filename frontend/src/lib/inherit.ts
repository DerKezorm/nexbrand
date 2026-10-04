/**
 * A project's design set on top of its client's, part by part: inherited, inherited plus its own, or its own.
 *
 * The same as the server (`backend/app/services/inherit.py`); `inherit.test.ts` holds both to the same answers.
 */

import type { BrandSet } from './brand'

export type InheritPart = 'colors' | 'fonts' | 'logos' | 'scale' | 'rules' | 'samples' | 'dark'
export const INHERIT_PARTS: InheritPart[] = ['colors', 'fonts', 'logos', 'scale', 'rules', 'samples', 'dark']
export type Mode = 'inherit' | 'extend' | 'own'
export const MODES: Mode[] = ['inherit', 'extend', 'own']
export type Modes = Record<InheritPart, Mode>

/** A project version as stored: only what is its own, and where each part comes from. */
export type OwnSet = Partial<BrandSet> & { inherit?: Partial<Modes> }

type ListPart = Exclude<InheritPart, 'dark'>
const KEYS: Record<ListPart, string | null> = { colors: 'name', fonts: 'family', logos: 'id', scale: 'name', rules: null, samples: 'media' }

export function modesOf(own: OwnSet): Modes {
  const given = own.inherit ?? {}
  return Object.fromEntries(INHERIT_PARTS.map((part) => [part, given[part] ?? 'inherit'])) as Modes
}

function merge(part: ListPart, base: unknown[], own: unknown[]): unknown[] {
  const key = KEYS[part]
  if (key === null) return [...base, ...own]
  const name = (item: unknown) => String((item as Record<string, unknown>)[key] ?? '').toLowerCase()
  const mine = new Map(own.map((item) => [name(item), item] as const))
  const out = base.map((item) => {
    const replaced = mine.get(name(item))
    if (replaced === undefined) return item
    mine.delete(name(item))
    return replaced
  })
  return [...out, ...own.filter((item) => mine.has(name(item)))]
}

/** The design set a project version shows: its client's `base` with its `own` parts. */
export function resolve(base: Partial<BrandSet>, own: OwnSet): BrandSet {
  const how = modesOf(own)
  const out: Record<string, unknown> = {}
  for (const part of INHERIT_PARTS) {
    const mode = how[part]
    if (part === 'dark') {
      const dark = mode === 'inherit' ? base.dark : own.dark
      if (dark) out.dark = dark
      continue
    }
    const b = (base[part] ?? []) as unknown[]
    const o = (own[part] ?? []) as unknown[]
    out[part] = mode === 'inherit' ? [...b] : mode === 'own' ? [...o] : merge(part, b, o)
  }
  return out as BrandSet
}

const same = (a: unknown, b: unknown) => a === b || JSON.stringify(a) === JSON.stringify(b)

/** For each list part, where each item of the resolved set comes from: `client` or `project`. */
export function origin(base: Partial<BrandSet>, own: OwnSet): Record<ListPart, ('client' | 'project')[]> {
  const how = modesOf(own)
  const out = {} as Record<ListPart, ('client' | 'project')[]>
  for (const part of INHERIT_PARTS) {
    if (part === 'dark') continue
    const resolved = (resolve(base, { ...own, inherit: { [part]: how[part] } })[part] ?? []) as unknown[]
    const mine = how[part] !== 'inherit' ? ((own[part] ?? []) as unknown[]) : []
    out[part] = resolved.map((item) => (mine.some((m) => same(item, m)) ? 'project' : 'client'))
  }
  return out
}
