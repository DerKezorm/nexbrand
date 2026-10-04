import { describe, expect, it } from 'vitest'

import type { BrandSet } from './brand'
import { origin, resolve, type OwnSet } from './inherit'

// The server's file, read when the tests run (as in color.test.ts: a static import would enter the app's type check).
type Files = { readFileSync: (file: string, encoding: string) => string }
const fsName = 'node:fs'
const files = (await import(/* @vite-ignore */ fsName)) as Files
const cases = JSON.parse(files.readFileSync('../backend/tests/data/inherit_cases.json', 'utf-8')) as {
  base: BrandSet
  cases: { own: OwnSet; resolved: BrandSet; origin: Record<string, string[]> }[]
}

describe('a project on its client, as the server puts it together', () => {
  it.each(cases.cases.map((c, i) => [i, c] as const))('case %i', (_, c) => {
    expect(resolve(cases.base, c.own)).toEqual(c.resolved)
    expect(origin(cases.base, c.own)).toEqual(c.origin)
  })
})
