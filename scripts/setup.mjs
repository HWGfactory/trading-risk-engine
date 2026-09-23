/**
 * 최초 1회 준비. 이미 되어 있는 단계는 건너뛴다(여러 번 실행해도 안전하다).
 *
 * 하는 일
 *   1. backend/.venv 생성
 *   2. pip install -r requirements.txt
 *   3. frontend 의존성 설치
 *   4. 기존 DB가 구조가 다르면 이전(migrate)
 *   5. 예시 북이 없으면 시드
 *
 * 경로에 공백이 있어도(이 프로젝트 경로가 그렇다) 안전하도록, 셸을 거치지 않고
 * spawnSync에 인자 배열을 그대로 넘긴다. 문자열을 조립해 셸에 넘기지 않는다.
 */
import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const BACKEND = join(ROOT, 'backend')
const VENV_PY = join(BACKEND, '.venv', 'Scripts', 'python.exe')
const IS_WINDOWS = process.platform === 'win32'

let step = 0
const say = (msg) => process.stdout.write(`\n[${++step}] ${msg}\n`)
const skip = (msg) => process.stdout.write(`    건너뜀: ${msg}\n`)

/** 셸을 거치지 않고 실행한다. 공백이 든 경로가 그대로 하나의 인자로 전달된다. */
function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    stdio: 'inherit',
    cwd: opts.cwd || ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    // npm은 Windows에서 npm.cmd라 셸이 필요하다. 그 외에는 셸을 쓰지 않는다.
    shell: opts.shell ?? false,
  })
  if (r.error) throw new Error(`${cmd} 실행 실패: ${r.error.message}`)
  if (r.status !== 0) throw new Error(`${cmd} 가 ${r.status} 로 끝났습니다.`)
}

/** venv를 만들 파이썬을 찾는다. Windows의 python/python3는 Microsoft Store 스텁일 수 있다. */
function findPython() {
  const candidates = IS_WINDOWS
    ? [['py', ['-3']], ['python', []], ['python3', []]]
    : [['python3', []], ['python', []]]
  for (const [cmd, prefix] of candidates) {
    const probe = spawnSync(cmd, [...prefix, '-c', 'import sys; print(sys.version_info[0])'], {
      encoding: 'utf-8',
      shell: false,
    })
    // Store 스텁은 종료 코드가 0이 아니거나 아무것도 출력하지 않는다.
    if (probe.status === 0 && probe.stdout.trim() === '3') return [cmd, prefix]
  }
  throw new Error(
    'Python 3을 찾지 못했습니다.\n' +
      'Windows라면 python.org에서 설치하거나 py 런처를 쓸 수 있는지 확인하세요.\n' +
      '(python / python3 가 Microsoft Store 스텁이면 실행은 되지만 아무 일도 하지 않습니다.)',
  )
}

function main() {
  process.stdout.write('PI 데스크 포지션 평가 엔진 준비를 시작합니다.\n')

  say('백엔드 가상환경')
  if (existsSync(VENV_PY)) {
    skip('backend/.venv 가 이미 있습니다.')
  } else {
    const [cmd, prefix] = findPython()
    process.stdout.write(`    ${cmd} ${prefix.join(' ')} 로 만듭니다.\n`)
    run(cmd, [...prefix, '-m', 'venv', '.venv'], { cwd: BACKEND })
  }

  say('백엔드 의존성')
  run(VENV_PY, ['-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
    '-r', join(BACKEND, 'requirements.txt')])
  process.stdout.write('    requirements.txt 반영 완료\n')

  say('프론트 의존성')
  if (existsSync(join(ROOT, 'frontend', 'node_modules'))) {
    skip('frontend/node_modules 가 이미 있습니다.')
  } else {
    run('npm', ['--prefix', join(ROOT, 'frontend'), 'install'], { shell: IS_WINDOWS })
  }

  say('기존 DB 이전')
  run(VENV_PY, [join(BACKEND, 'scripts', 'migrate_to_trades.py')])

  say('예시 북')
  run(VENV_PY, [join(BACKEND, 'scripts', 'seed_demo.py')])

  process.stdout.write('\n준비가 끝났습니다. 이제 `npm run dev` 로 실행하세요.\n')
}

try {
  main()
} catch (err) {
  process.stderr.write(`\n[실패] ${err.message}\n`)
  process.exit(1)
}
