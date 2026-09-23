/**
 * 개발 서버가 쓸 포트를 비운다. `npm run dev` 직전에 돌아간다(predev).
 *
 * 왜 필요한가
 *   uvicorn --reload 는 감시 프로세스와 작업 프로세스를 따로 띄운다.
 *   터미널이 강제로 닫히거나 감시 쪽만 죽으면 작업 프로세스가 포트를 쥔 채 남는다.
 *   그 상태로 다시 실행하면 "address already in use" 로 백엔드가 뜨지 않는데,
 *   원인이 화면에 드러나지 않아 한참 헤매게 된다. 실제로 이 프로젝트에서 반복됐다.
 *
 * 까다로운 점
 *   Windows는 소켓을 '핸들을 처음 연 프로세스' 소유로 보고한다. 감시 프로세스가 죽고
 *   작업 프로세스가 살아 있으면, netstat은 이미 죽은 PID를 알려준다.
 *   그래서 보고된 PID만 죽이면 포트가 풀리지 않는다. 그 PID의 자식까지 찾아 정리한다.
 *
 * 안전장치
 *   아무 프로세스나 죽이지 않는다. 명령줄이 이 프로젝트의 것으로 보일 때만 정리하고,
 *   그렇지 않으면 무엇이 물고 있는지 알려주고 그대로 둔다.
 */
import { execFileSync } from 'node:child_process'

const PORTS = [Number(process.env.TRE_API_PORT || 8000), 5173]
// 이 프로젝트가 띄우는 것으로 볼 수 있는 흔적
const OURS = /uvicorn|app\.main:app|vite|multiprocessing|spawn_main|run-python\.mjs/i

if (process.platform !== 'win32') process.exit(0)

const sh = (cmd, args) => {
  try {
    return execFileSync(cmd, args, { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'] })
  } catch {
    return ''
  }
}

const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)

/** 해당 포트를 LISTENING 으로 물고 있다고 보고된 PID들 */
function listenersOn(port) {
  const out = sh('netstat', ['-ano', '-p', 'TCP'])
  const pids = new Set()
  for (const line of out.split('\n')) {
    if (!line.includes('LISTENING')) continue
    const cols = line.trim().split(/\s+/)
    if ((cols[1] || '').endsWith(`:${port}`)) pids.add(cols[cols.length - 1])
  }
  return [...pids].filter((p) => p && p !== '0')
}

/** 살아 있는 프로세스 목록 (pid, 부모 pid, 명령줄) */
function processTable() {
  const raw = sh('powershell', [
    '-NoProfile', '-Command',
    'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress',
  ])
  try {
    const parsed = JSON.parse(raw || '[]')
    return (Array.isArray(parsed) ? parsed : [parsed]).map((p) => ({
      pid: String(p.ProcessId),
      parent: String(p.ParentProcessId),
      cmd: p.CommandLine || '',
    }))
  } catch {
    return []
  }
}

const kill = (pid) => sh('taskkill', ['/PID', pid, '/T', '/F'])

let cleaned = 0
let refused = false

for (const port of PORTS) {
  for (const reported of listenersOn(port)) {
    const table = processTable()
    const self = table.find((p) => p.pid === reported)
    // 보고된 PID가 죽어 있으면 그 자식이 진짜 점유자다.
    const children = table.filter((p) => p.parent === reported)
    const targets = [self, ...children].filter(Boolean)

    if (targets.length === 0) {
      // 프로세스는 모두 사라졌고 소켓만 남았다. 곧 풀린다.
      kill(reported)
      cleaned += 1
      continue
    }
    const foreign = targets.filter((p) => p.cmd && !OURS.test(p.cmd))
    if (foreign.length) {
      for (const p of foreign) {
        process.stdout.write(
          `포트 ${port}을(를) 다른 프로그램이 쓰고 있습니다 (pid ${p.pid}).\n` +
            `  ${p.cmd.slice(0, 120)}\n` +
            '  이 프로세스는 건드리지 않았습니다. 직접 정리하거나 포트를 바꾸세요.\n',
        )
      }
      refused = true
      continue
    }
    for (const p of targets) kill(p.pid)
    kill(reported)
    process.stdout.write(
      `포트 ${port}에 남아 있던 이전 개발 서버를 정리했습니다 ` +
        `(pid ${targets.map((p) => p.pid).join(', ')}).\n`,
    )
    cleaned += 1
  }
}

/*
  죽였다고 포트가 바로 풀리지는 않는다. 실제로 풀릴 때까지 확인한다.
  정해진 시간 안에 안 풀리면 알려주고 넘어간다.
*/
if (cleaned && !refused) {
  const deadline = Date.now() + 12_000
  const pending = () => PORTS.filter((p) => listenersOn(p).length > 0)
  let left = pending()
  while (left.length && Date.now() < deadline) {
    sleep(300)
    left = pending()
  }
  if (left.length) {
    process.stdout.write(
      `포트 ${left.join(', ')}이(가) 아직 풀리지 않았습니다. 잠시 뒤 다시 실행해 보세요.\n`,
    )
  }
}
