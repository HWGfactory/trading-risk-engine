/**
 * 개발 서버가 쓸 포트를 비운다. `npm run dev` 직전에 돌아간다(predev).
 *
 * 왜 필요한가
 *   uvicorn --reload 는 감시 프로세스와 작업 프로세스를 따로 띄운다.
 *   터미널이 강제로 닫히거나 감시 쪽만 죽으면 작업 프로세스가 포트를 쥔 채 남는다.
 *   그 상태로 다시 실행하면 "address already in use" 로 백엔드가 뜨지 않는데,
 *   원인이 화면에 드러나지 않아 한참 헤매게 된다. 실제로 이 프로젝트에서 반복됐다.
 *
 * 안전장치
 *   아무 프로세스나 죽이지 않는다. 명령줄이 이 프로젝트의 것으로 보일 때만 정리하고,
 *   그렇지 않으면 무엇이 물고 있는지 알려주고 그대로 둔다.
 */
import { execFileSync } from 'node:child_process'

const PORTS = [Number(process.env.TRE_API_PORT || 8000), 5173]
// 이 프로젝트가 띄우는 것으로 볼 수 있는 흔적
const OURS = /uvicorn|app\.main:app|vite|multiprocessing\.spawn|run-python\.mjs/i

if (process.platform !== 'win32') process.exit(0)

const sh = (cmd, args) => {
  try {
    return execFileSync(cmd, args, { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'] })
  } catch {
    return ''
  }
}

/** 해당 포트를 LISTENING 상태로 물고 있는 PID들 */
function listenersOn(port) {
  const out = sh('netstat', ['-ano', '-p', 'TCP'])
  const pids = new Set()
  for (const line of out.split('\n')) {
    if (!line.includes('LISTENING')) continue
    const cols = line.trim().split(/\s+/)
    const local = cols[1] || ''
    if (local.endsWith(`:${port}`)) pids.add(cols[cols.length - 1])
  }
  return [...pids].filter((p) => p && p !== '0')
}

function commandLineOf(pid) {
  const out = sh('powershell', [
    '-NoProfile', '-Command',
    `(Get-CimInstance Win32_Process -Filter "ProcessId=${pid}").CommandLine`,
  ])
  return out.trim()
}

let cleaned = 0
for (const port of PORTS) {
  for (const pid of listenersOn(port)) {
    const cmd = commandLineOf(pid)
    // 명령줄을 못 읽으면 이미 죽고 소켓만 남은 것이다. 그때도 정리를 시도한다.
    if (cmd && !OURS.test(cmd)) {
      process.stdout.write(
        `포트 ${port}을(를) 다른 프로그램이 쓰고 있습니다 (pid ${pid}).\n` +
          `  ${cmd.slice(0, 120)}\n` +
          '  이 프로세스는 건드리지 않았습니다. 직접 정리하거나 포트를 바꾸세요.\n',
      )
      continue
    }
    sh('taskkill', ['/PID', pid, '/T', '/F'])
    process.stdout.write(`포트 ${port}에 남아 있던 이전 개발 서버를 정리했습니다 (pid ${pid}).\n`)
    cleaned += 1
  }
}

if (cleaned) {
  // 소켓이 완전히 풀릴 때까지 잠깐 기다린다.
  const until = Date.now() + 1500
  while (Date.now() < until) { /* busy wait, 짧다 */ }
}
