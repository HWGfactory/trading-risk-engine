import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './fonts.css'
import './index.css'
import App from './App.tsx'

/*
  한글은 unicode-range로 92조각으로 나뉜 배포판이라 @font-face 선언만 184개다.
  이걸 첫 스타일시트에 넣으면 렌더를 막는 CSS가 그만큼 커진다.
  동적 임포트로 분리해 첫 그리기를 막지 않게 한다. font-display: swap이라
  도착 전에는 시스템 한글 글꼴로 먼저 그려지고 조용히 교체된다.
*/
void import('@fontsource/ibm-plex-sans-kr/400.css')
void import('@fontsource/ibm-plex-sans-kr/600.css')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
