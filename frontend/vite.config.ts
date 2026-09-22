import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import type { Plugin } from 'vite'

/*
  @fontsource는 조각마다 woff2와 woff를 함께 선언한다.
  한글은 조각이 92개라 두 벌을 다 싣으면 @font-face URL이 수백 개가 되어
  렌더를 막는 스타일시트가 그만큼 커진다. woff2는 2017년 이후 모든 대상 브라우저가
  지원하므로 woff 대체 선언만 걷어낸다. 글꼴 파일 자체는 그대로다.
*/
function woff2Only(): Plugin {
  return {
    name: 'woff2-only',
    // Vite의 CSS 변환보다 먼저 돌아야 원본 CSS 문자열을 손볼 수 있다.
    enforce: 'pre',
    transform(code, id) {
      if (!id.includes('@fontsource') || !id.split('?')[0].endsWith('.css')) return null
      return { code: code.replace(/,\s*url\([^)]*\.woff\)\s*format\("?'?woff'?"?\)/g, ''), map: null }
    },
  }
}

// 백엔드(FastAPI)는 127.0.0.1:8000. Windows에서 localhost가 IPv6(::1)로 풀려
// 프록시가 실패하는 경우가 있어 IP로 고정한다.
export default defineConfig({
  plugins: [react(), woff2Only()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
