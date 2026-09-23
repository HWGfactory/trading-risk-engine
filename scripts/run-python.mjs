/**
 * 가상환경의 파이썬을 실행한다. 가상환경을 활성화하지 않아도 된다.
 *
 * 왜 노드를 한 겹 두는가
 *   npm 스크립트는 Windows에서 `cmd /d /s /c "..."` 로 실행된다. cmd는 따옴표와
 *   슬래시를 특이하게 다뤄서, 스크립트 문자열에 실행 파일 경로를 직접 적으면
 *   파싱이 어긋난다(실제로 'backend'를 명령어로 인식하는 오류가 났다).
 *   여기서는 셸을 거치지 않고 spawn에 인자 배열을 그대로 넘긴다.
 *   그래서 프로젝트 경로에 공백이 있어도("Trading Risk Engine") 안전하다.
 *
 * 사용: node scripts/run-python.mjs -m uvicorn app.main:app --port 8000
 */
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const VENV_PY =
  process.platform === 'win32'
    ? join(ROOT, 'backend', '.venv', 'Scripts', 'python.exe')
    : join(ROOT, 'backend', '.venv', 'bin', 'python')

if (!existsSync(VENV_PY)) {
  process.stderr.write(
    '백엔드 가상환경이 없습니다.\n' +
      '먼저 `npm run setup` 을 실행하세요.\n',
  )
  process.exit(1)
}

const child = spawn(VENV_PY, process.argv.slice(2), {
  cwd: ROOT,
  stdio: 'inherit',
  // 한국어 로그가 깨지지 않도록 고정한다. Windows 기본은 cp949다.
  env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUNBUFFERED: '1' },
})

/*
  Ctrl+C가 오면 자식에게 넘긴다.

  안전망이 필요한 이유: uvicorn --reload 는 감시 프로세스와 작업 프로세스를 따로 띄운다.
  감시 쪽만 죽으면 작업 프로세스가 포트를 쥔 채 남는다(실제로 이 프로젝트에서
  포트 8000을 물고 있는 고아 프로세스가 반복해서 생겼다).
  그래서 정상 종료를 먼저 시도하고, 잠깐 기다려도 안 끝나면 프로세스 트리째 정리한다.
*/
let shuttingDown = false

function killTree() {
  if (process.platform !== 'win32' || child.exitCode !== null) return
  spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {
    stdio: 'ignore',
    shell: false,
  }).on('error', () => {})
}

function shutdown(sig) {
  if (shuttingDown) return
  shuttingDown = true
  child.kill(sig)
  const grace = setTimeout(killTree, 3000)
  grace.unref()
}

for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGBREAK']) {
  process.on(sig, () => shutdown(sig === 'SIGBREAK' ? 'SIGINT' : sig))
}
// 부모(concurrently)가 사라지면 stdin이 닫힌다. 그때도 같이 내려간다.
process.stdin.on('end', () => shutdown('SIGTERM'))

child.on('exit', (code, signal) => {
  process.exit(signal ? 1 : (code ?? 0))
})
