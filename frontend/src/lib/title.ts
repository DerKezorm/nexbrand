import { useEffect } from 'react'

/** The browser tab says where one is: "Bäckerei Morgenrot · nexbrand" instead of "nexbrand" on every page.
 * `alone`: the name without the app's, for the pages a client sees (a public page, a review). */
export function pageTitle(text: string | null | undefined, alone = false): string {
  const name = (text ?? '').trim()
  if (!name) return 'nexbrand'
  return alone ? name : `${name} · nexbrand`
}

export function useTitle(text: string | null | undefined, alone = false): void {
  useEffect(() => {
    document.title = pageTitle(text, alone)
  }, [text, alone])
}
