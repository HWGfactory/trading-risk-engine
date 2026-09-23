/**
 * 백엔드가 응답할 때까지 기다린다.
 *
 * 왜 필요한가
 *   vite dev 서버가 먼저 뜨면 /api 요청이 프록시에서 ECONNREFUSED로 떨어진다.
 *   화면은 "백엔드에 연결하지 못했습니다"를 띄우고, 사용자는 새로고침해야 한다.
 *   순서를 보장하면 그 상황 자체가 생기지 않는다.
 *
 * 시간이 지나도 안 뜨면 그냥 진행한다. 백엔드가 실패했더라도 프론트는 띄워 주는 편이
 * 낫다(화면이 오프라인 안내를 보여주고, concurrently 로그에 백엔드 오류가 남는다).
 */
import { connect } from 'node:net'

const PORT = Number(process.env.TRE_API_PORT || 8000)
const HOST = '127.0.0.1'
const TIMEOUT_MS = 40_000
const INTERVAL_MS = 250

const canConnect = () =>
  new Promise((resolve) => {
    const socket = connect({ port: PORT, host: HOST })
    const done = (ok) => {
      socket.destroy()
      resolve(ok)
    }
    socket.setTimeout(1000)
    socket.once('connect', () => done(true))
    socket.once('error', () => done(false))
    socket.once('timeout', () => done(false))
  })

const started = Date.now()
let announced = false

while (Date.now() - started < TIMEOUT_MS) {
  if (await canConnect()) {
    process.stdout.write(`백엔드 준비됨 (${HOST}:${PORT}). 프론트를 시작합니다.\n`)
    process.exit(0)
  }
  if (!announced) {
    process.stdout.write(`백엔드(${HOST}:${PORT})를 기다리는 중입니다.\n`)
    announced = true
  }
  await new Promise((r) => setTimeout(r, INTERVAL_MS))
}

process.stdout.write(
  `백엔드가 ${TIMEOUT_MS / 1000}초 안에 뜨지 않았습니다. 프론트만 먼저 시작합니다.\n` +
    'api 쪽 로그에서 원인을 확인하세요.\n',
)
process.exit(0)
