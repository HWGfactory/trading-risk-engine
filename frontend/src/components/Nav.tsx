import { MoonIcon, SunIcon } from '@phosphor-icons/react'
import { motion } from 'motion/react'
import type { Route } from '../router'
import type { ThemeChoice } from '../theme'

interface Props {
  route: Route
  onNavigate: (r: Route) => void
  themeChoice: ThemeChoice
  resolved: 'light' | 'dark'
  onToggleTheme: (c: ThemeChoice) => void
}

const LINKS: { route: Route; label: string }[] = [
  { route: 'home', label: '홈' },
  { route: 'valuation', label: '포지션 평가' },
  { route: 'book', label: '북 현황' },
]

export default function Nav({ route, onNavigate, resolved, onToggleTheme }: Props) {
  const next = resolved === 'dark' ? 'light' : 'dark'

  return (
    <header className="nav">
      <div className="wrap nav-inner">
        <button type="button" className="wordmark" onClick={() => onNavigate('home')}>
          PI DESK
        </button>

        <nav className="nav-links" aria-label="화면">
          {LINKS.map((l) => (
            <button key={l.route} type="button" className="nav-link"
              aria-current={route === l.route ? 'page' : undefined}
              onClick={() => onNavigate(l.route)}>
              {l.label}
              {route === l.route && (
                // 현재 위치를 알려주는 표시. 화면을 옮기면 같은 요소가 미끄러져 이동한다.
                <motion.span className="nav-marker" layoutId="nav-marker"
                  transition={{ type: 'spring', stiffness: 100, damping: 20 }} />
              )}
            </button>
          ))}
        </nav>

        <button type="button" className="theme-toggle" onClick={() => onToggleTheme(next)}
          aria-label={next === 'dark' ? '어두운 화면으로 바꾸기' : '밝은 화면으로 바꾸기'}>
          {resolved === 'dark'
            ? <SunIcon size={17} weight="regular" />
            : <MoonIcon size={17} weight="regular" />}
        </button>
      </div>
    </header>
  )
}
