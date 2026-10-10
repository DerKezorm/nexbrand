import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useAuth } from '../state/auth'

/**
 * Beside an API token (and so an MCP key): a password account without a second factor of its own, signed in at a
 * provider that checks it, is let in without one, but a token has no provider behind it and waits until the account
 * sets one up. Making one stays possible (module 1.0.10).
 */
export function KeysWait({ className = '' }: { className?: string }) {
  const { t } = useTranslation()
  const { me } = useAuth()
  if (!me?.keys_wait_for_second_factor) return null
  return (
    <p role="note" data-testid="keys-wait" className={'text-xs text-warn-500 ' + className}>
      {t('me.keysWait')}{' '}
      <Link to="/account?tab=security" className="underline">
        {t('me.keysWaitLink')}
      </Link>
    </p>
  )
}
