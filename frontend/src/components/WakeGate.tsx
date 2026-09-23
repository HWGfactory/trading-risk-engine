import { ArrowClockwiseIcon, WarningCircleIcon } from '@phosphor-icons/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ping } from '../api'

interface Props {
  children: React.ReactNode
}

type Phase = 'checking' | 'waking' | 'ready' | 'failed'

// 잠든 무료 플랜은 첫 응답까지 1분 가까이 걸린다. 그동안 재시도한다.
const TOTAL_MS = 70_000
// 이 시간이 지나도 응답이 없으면 "깨우는 중" 안내를 띄운다.
// 바로 띄우면 정상적인 로컬 개발에서도 깜빡여서 방해가 된다.
const ANNOUNCE_AFTER_MS = 1_200

/**
 * 백엔드가 응답할 때까지 화면을 붙잡아 둔다.
 *
 * 왜 필요한가
 *   배포된 데모는 요청이 없으면 잠든다. 깨어나는 동안 화면이 비어 보이면
 *   사용자는 고장으로 여기고 떠난다. 무슨 일이 일어나는지, 얼마나 걸리는지 알려준다.
 *
 * 로컬 개발에서는 첫 ping이 즉시 성공하므로 이 화면이 보이지 않는다.
 */
export default function WakeGate({ children }: Props) {
  const [phase, setPhase] = useState<Phase>('checking')
  const [elapsed, setElapsed] = useState(0)
  const cancelled = useRef(false)

  const attempt = useCallback(async () => {
    cancelled.current = false
    setPhase('checking')
    setElapsed(0)

    const started = Date.now()
    const announce = setTimeout(() => {
      if (!cancelled.current) setPhase((p) => (p === 'checking' ? 'waking' : p))
    }, ANNOUNCE_AFTER_MS)
    const ticker = setInterval(() => {
      if (!cancelled.current) setElapsed(Math.round((Date.now() - started) / 1000))
    }, 1000)

    try {
      while (!cancelled.current && Date.now() - started < TOTAL_MS) {
        if (await ping()) {
          if (!cancelled.current) setPhase('ready')
          return
        }
        await new Promise((r) => setTimeout(r, 1500))
      }
      if (!cancelled.current) setPhase('failed')
    } finally {
      clearTimeout(announce)
      clearInterval(ticker)
    }
  }, [])

  useEffect(() => {
    void attempt()
    return () => { cancelled.current = true }
  }, [attempt])

  if (phase === 'ready') return <>{children}</>

  return (
    <div className="wrap page">
      <section className="panel statement-empty" aria-live="polite" aria-busy={phase !== 'failed'}>
        {phase === 'failed' ? (
          <>
            <WarningCircleIcon size={26} weight="light" aria-hidden />
            <p>
              백엔드 서버에 연결하지 못했습니다.
              잠시 뒤 다시 시도하거나, 로컬에서 실행 중이라면 백엔드가 떠 있는지 확인하세요.
            </p>
            <button type="button" className="btn btn-secondary" onClick={() => void attempt()}>
              <ArrowClockwiseIcon size={14} weight="bold" aria-hidden />
              다시 시도
            </button>
          </>
        ) : phase === 'waking' ? (
          <>
            <span className="skeleton" style={{ width: 26, height: 26, borderRadius: 13 }} />
            <p>
              데모 서버를 깨우는 중입니다. 최대 1분 걸릴 수 있습니다.
              <br />
              <span className="cell-sub">
                요청이 없으면 잠드는 무료 플랜이라 처음 한 번만 느립니다.
                {elapsed > 0 && ` (${elapsed}초 경과)`}
              </span>
            </p>
          </>
        ) : (
          <span className="skeleton" style={{ width: 200, height: 18 }}>불러오는 중</span>
        )}
      </section>
    </div>
  )
}
