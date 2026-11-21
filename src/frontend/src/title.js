import { useEffect } from 'react'

const APP = 'AG FileNet migration workbench'

/** Name the current page in the browser tab. */
export function useTitle(title) {
  useEffect(() => {
    document.title = title ? `${title} – ${APP}` : APP
  }, [title])
}
