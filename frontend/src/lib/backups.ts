import type { Me } from '../api/client'

/** What the backup list offers this account. Connected to nexsuite, only the emergency account downloads or deletes
 *  a backup (the archive holds its password and second factor), and restoring waits for a disconnect: nexsuite keeps
 *  the accounts then, and the server refuses it anyway; so does an upload, which is only ever brought in to be
 *  restored. */
export function backupActions(me: Pick<Me, 'suite' | 'suite_emergency'> | null | undefined): {
  download: boolean
  restore: boolean
  upload: boolean
  remove: boolean
  /** Which sentence says why something is missing: none, only the restore, or the emergency account as well. */
  note: '' | 'restore' | 'keeper'
} {
  const connected = me?.suite === 'connected'
  const keeper = !connected || Boolean(me?.suite_emergency)
  return { download: keeper, restore: !connected, upload: !connected, remove: keeper, note: !connected ? '' : keeper ? 'restore' : 'keeper' }
}
