/**
 * Every shipped text is asked for somewhere, and numbers count right. "Download template" (Settings, General) hands
 * every key to translators: a text no page shows is work for nothing, and a sentence of another app (a vault, a
 * canvas, notes) told them nexbrand had it.
 *
 * A key counts as asked for when the code names it, or names its start in a built key (`notices.${kind}`). The error
 * texts are checked against the server's codes in `backend/tests/test_texts.py`.
 */

import i18n from 'i18next'

import de from './de.json'
import en from './en.json'

type Files = {
  readFileSync: (file: string, encoding: string) => string
  readdirSync: (folder: string, options: { recursive: true }) => string[]
}
const fsName = 'node:fs'
const files = (await import(/* @vite-ignore */ fsName)) as Files

function flat(tree: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(tree).flatMap(([key, value]) =>
    value && typeof value === 'object' ? flat(value as Record<string, unknown>, `${prefix}${key}.`) : [prefix + key],
  )
}

const source = files
  .readdirSync('src', { recursive: true })
  .map((name) => name.replaceAll('\\', '/'))
  .filter((name) => /\.tsx?$/.test(name) && !name.includes('.test.') && !name.startsWith('i18n/'))
  .map((name) => files.readFileSync(`src/${name}`, 'utf-8'))
  .join('\n')

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function askedFor(key: string): boolean {
  const base = key.replace(/_(one|other|zero)$/, '')
  if (source.includes(base)) return true
  const parts = base.split('.')
  for (let end = parts.length - 1; end > 0; end--) {
    const start = parts.slice(0, end).join('.') + '.'
    if (new RegExp(`['\`]${escape(start)}\\$\\{`).test(source)) return true
  }
  return false
}

describe('the shipped texts', () => {
  it('are all asked for by some page', () => {
    const unused = flat(de).filter((key) => !key.startsWith('errors.') && !askedFor(key))
    expect(unused).toEqual([])
  })

  it('count one and many in both languages', async () => {
    await i18n.init({ resources: { de: { translation: de }, en: { translation: en } }, lng: 'de', interpolation: { escapeValue: false } })
    const content = (language: string, clients: number, count: number) => {
      const t = i18n.getFixedT(language)
      return t('server.backupContent', { clients: t('server.backupClients', { count: clients }), files: t('server.backupFiles', { count }) })
    }
    expect(content('de', 1, 1)).toBe('ein Kunde, eine Datei')
    expect(content('de', 4, 0)).toBe('4 Kunden, 0 Dateien')
    expect(content('en', 1, 1)).toBe('one client, one file')
    expect(content('en', 2, 3)).toBe('2 clients, 3 files')
    const managed = i18n.getFixedT('de')
    expect(managed('server.allSpaces.membersNoManager', { count: 1 })).toBe('eine Person mit Zugriff, niemand verwaltet den Kunden')
  })

  it('say "you" when a notice is about the reader', () => {
    for (const tree of [de, en] as unknown as { notices: Record<string, string> }[]) {
      for (const kind of ['operator_added', 'operator_role', 'operator_removed']) {
        expect(tree.notices[`${kind}_self`], kind).toMatch(/\b(dich|dir|dein|you|your)\b/)
        expect(tree.notices[`${kind}_self`], kind).not.toContain('{{subject}}')
      }
    }
  })
})
