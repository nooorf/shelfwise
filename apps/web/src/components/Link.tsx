// An in-app link: a real <a> (new tab, copy link and modifier clicks still work), but a plain
// click moves between pages without reloading.
import type { AnchorHTMLAttributes } from 'react'

import { navigate } from '../router'

export function Link({ href, onClick, ...rest }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) {
  return (
    <a
      href={href}
      onClick={(e) => {
        onClick?.(e)
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
        e.preventDefault()
        navigate(href)
      }}
      {...rest}
    />
  )
}
