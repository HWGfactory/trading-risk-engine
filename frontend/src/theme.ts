import { useEffect, useState } from 'react'

export type ThemeChoice = 'system' | 'light' | 'dark'

const KEY = 'tre-theme'

function read(): ThemeChoice {
  // ?theme=dark 는 스크린샷을 찍을 때 테마를 확실히 고정하기 위한 것이다.
  const forced = new URLSearchParams(location.search).get('theme')
  if (forced === 'light' || forced === 'dark') return forced
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

/**
 * 기본은 시스템 설정을 따르고, 수동 선택만 저장한다.
 * data-theme 속성이 있으면 CSS가 그 값을 우선 적용한다(index.css 참조).
 */
export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>(read)

  useEffect(() => {
    const root = document.documentElement
    if (choice === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', choice)
    try {
      if (choice === 'system') localStorage.removeItem(KEY)
      else localStorage.setItem(KEY, choice)
    } catch {
      // 사생활 보호 모드 등에서 저장이 막혀도 화면은 그대로 동작한다.
    }
  }, [choice])

  const systemDark = typeof matchMedia === 'function'
    && matchMedia('(prefers-color-scheme: dark)').matches
  const resolved: 'light' | 'dark' = choice === 'system' ? (systemDark ? 'dark' : 'light') : choice

  return { choice, resolved, setChoice }
}
