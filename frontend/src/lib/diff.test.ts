import { describe, expect, it } from 'vitest'

import { diffSets } from './diff'

// The server's file, read when the tests run (see color.test.ts for why not a static import).
type Files = { readFileSync: (file: string, encoding: string) => string }
const fsName = 'node:fs'
const files = (await import(/* @vite-ignore */ fsName)) as Files
const cases = JSON.parse(files.readFileSync('../backend/tests/data/diff_cases.json', 'utf-8')) as { cases: { name: string; a: unknown; b: unknown; changes: unknown[] }[] }

/** Comparing two versions finds what the server finds, in every part (F10). */
describe('comparing two versions, as the server does it', () => {
  it.each(cases.cases.map((c) => [c.name, c] as const))('%s', (_name, c) => {
    expect(diffSets(c.a, c.b)).toEqual(c.changes)
  })

  it('has cases with a type scale, rules and a dark mode', () => {
    const parts = new Set(cases.cases.flatMap((c) => (c.changes as { part: string }[]).map((x) => x.part)))
    expect([...parts].sort()).toEqual(['colors', 'dark', 'fonts', 'logos', 'rules', 'samples', 'scale'])
  })
})
