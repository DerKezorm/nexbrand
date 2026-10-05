import { describe, expect, it } from 'vitest'

import { backupActions } from './backups'

describe('backupActions', () => {
  it('offers everything on its own', () => {
    expect(backupActions({ suite: '' })).toEqual({ download: true, restore: true, upload: true, remove: true, note: '' })
    expect(backupActions({ suite: 'connecting' })).toEqual({ download: true, restore: true, upload: true, remove: true, note: '' })
  })

  it('connected, leaves the restore and the upload out and says why, for the emergency account too', () => {
    expect(backupActions({ suite: 'connected', suite_emergency: true })).toEqual({ download: true, restore: false, upload: false, remove: true, note: 'restore' })
  })

  it('connected, an operator from nexsuite neither downloads nor deletes', () => {
    expect(backupActions({ suite: 'connected', suite_emergency: false })).toEqual({ download: false, restore: false, upload: false, remove: false, note: 'keeper' })
  })
})
