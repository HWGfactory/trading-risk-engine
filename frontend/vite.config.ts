import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 백엔드(FastAPI)는 127.0.0.1:8000. Windows에서 localhost가 IPv6(::1)로 풀려
// 프록시가 실패하는 경우가 있어 IP로 고정한다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
