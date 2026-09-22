import { useEffect, useState } from 'react'

export type Route = 'home' | 'valuation' | 'book'

const PATHS: Record<Route, string> = {
  home: '#/',
  valuation: '#/valuation',
  book: '#/book',
}

function parse(hash: string): Route {
  const h = hash.replace(/^#/, '')
  if (h === '/valuation') return 'valuation'
  if (h === '/book') return 'book'
  return 'home'
}

/** 라이브러리 없는 해시 라우팅. 새로고침해도 같은 화면에 머문다. */
export function useRoute(): [Route, (r: Route) => void] {
  const [route, setRoute] = useState<Route>(() => parse(location.hash))

  useEffect(() => {
    const onChange = () => setRoute(parse(location.hash))
    addEventListener('hashchange', onChange)
    return () => removeEventListener('hashchange', onChange)
  }, [])

  useEffect(() => {
    // 주소가 비어 있으면 홈으로 정규화해 둔다.
    if (!location.hash) location.replace(PATHS.home)
  }, [])

  const go = (r: Route) => {
    if (location.hash !== PATHS[r]) location.hash = PATHS[r]
    else setRoute(r)
    scrollTo({ top: 0 })
  }

  return [route, go]
}

export const routePath = (r: Route) => PATHS[r]
