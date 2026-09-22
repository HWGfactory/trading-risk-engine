import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { formatSignedWon, formatWon, relativeTime, tone, usageBarWidth } from '../format'
import type { Route } from '../router'
import type { BookSummary } from '../types'
import MiniEvaluator from './MiniEvaluator'

interface Props {
  onNavigate: (r: Route) => void
}

export default function Home({ onNavigate }: Props) {
  const reduce = useReducedMotion()
  const rise = reduce
    ? {}
    : {
      initial: { opacity: 0, y: 12 },
      whileInView: { opacity: 1, y: 0 },
      viewport: { once: true, amount: 0.2 },
      transition: { duration: 0.3, ease: [0.16, 1, 0.3, 1] as const },
    }

  return (
    <div className="wrap page-home">
      <section className="hero">
        <div className="hero-copy">
          <h1>포지션 손익을 근거까지 계산합니다</h1>
          <p>
            진입가와 수량을 넣으면 세금과 수수료까지 반영한 순손익, 그리고 그 숫자가 나온
            산식이 함께 나옵니다.
          </p>
          <div className="hero-actions">
            <button type="button" className="btn btn-primary" onClick={() => onNavigate('valuation')}>
              포지션 평가하기
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => onNavigate('book')}>
              북 현황 보기
            </button>
          </div>
        </div>
        <MiniEvaluator />
      </section>

      <motion.section className="today" {...rise}>
        <TodayBook />
      </motion.section>

      <motion.section className="evidence" {...rise}>
        <div className="evidence-head">
          <h2>이 숫자를 믿을 수 있는 이유</h2>
        </div>
        <div className="evidence-list">
          <Evidence
            title="금액을 소수점 오차 없이 계산합니다"
            body="모든 금액과 비율은 Python Decimal로 계산합니다. 비용은 원 미만 절사, 명목금액과 손익은 원 단위 반올림으로 시장 관행을 따릅니다. 화면은 계산하지 않고 받은 값을 표시만 합니다."
            proof={<span className="num">7,000,000 × 0.015% = 1,050</span>}
          />
          <Evidence
            title="세율과 계약명세의 출처, 확인한 날짜를 함께 보여줍니다"
            body="거래세율과 거래승수는 코드가 아니라 설정 파일 한 곳에 있고, 값마다 근거 문서와 확인일이 붙어 있습니다. 화면에서 바로 확인할 수 있습니다."
            proof={
              <>증권거래세법 시행령 개정(2025년 세제개편안) · 확인일 2026-09-22</>
            }
          />
          <Evidence
            title="엔진 집계와 DB 집계를 매번 대사합니다"
            body="재평가할 때마다 Python 엔진이 더한 값과 SQL 뷰가 더한 값을 비교합니다. 한 포지션이라도 평가에 실패하면 이전 값이 섞이므로 대사를 건너뛰고 그렇게 표시합니다."
            proof={<span className="badge is-ok">일치</span>}
          />
          <Evidence
            title="평가 이력은 고치거나 지울 수 없습니다"
            body="valuations 테이블은 INSERT만 허용하고 트리거가 UPDATE와 DELETE를 막습니다. 포지션도 삭제하지 않고 청산 처리로 남깁니다. 평가마다 평가가격, 가격 출처, 기준일, 배치 ID가 기록됩니다."
            proof={<span className="num">trg_valuations_no_update · trg_valuations_no_delete</span>}
          />
          <Evidence
            title="손계산 예시를 기대값으로 두고 테스트합니다"
            body="METHODOLOGY 문서에 적은 손계산 결과를 그대로 기대값으로 삼은 테스트가 있습니다. 계산을 바꾸면 테스트가 먼저 깨지므로, 근거 문서를 고치지 않고는 숫자를 바꿀 수 없습니다."
            proof={<span className="num">METHODOLOGY.md 손계산 예시 A ~ E</span>}
          />
        </div>
      </motion.section>
    </div>
  )
}

function Evidence({ title, body, proof }: { title: string; body: string; proof: React.ReactNode }) {
  return (
    <article className="evidence-item">
      <h3>{title}</h3>
      <p>{body}</p>
      <div className="evidence-proof">{proof}</div>
    </article>
  )
}

/** 오늘의 북. 한도 사용률은 백엔드가 계산한 ratio를 그대로 쓴다. */
function TodayBook() {
  const [summary, setSummary] = useState<BookSummary | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'offline'>('loading')

  useEffect(() => {
    let cancelled = false
    api.bookSummary()
      .then((s) => { if (!cancelled) { setSummary(s); setState('ready') } })
      .catch(() => { if (!cancelled) setState('offline') })
    return () => { cancelled = true }
  }, [])

  if (state === 'loading') {
    return (
      <>
        <div className="section-head"><h2>오늘의 북</h2></div>
        <dl className="strip" aria-busy="true">
          {['순손익', '총노출', '한도 사용률', '마지막 평가'].map((l) => (
            <div key={l}>
              <dt>{l}</dt>
              <dd><span className="skeleton" style={{ width: '9ch', display: 'inline-block' }}>0</span></dd>
            </div>
          ))}
        </dl>
      </>
    )
  }

  if (state === 'offline' || !summary) {
    return (
      <>
        <div className="section-head"><h2>오늘의 북</h2></div>
        <p className="book-note">
          백엔드에 연결되면 북 요약이 여기에 나옵니다. backend 폴더에서 uvicorn을 실행하세요.
        </p>
      </>
    )
  }

  if (summary.totals.position_count === 0) {
    return (
      <>
        <div className="section-head"><h2>오늘의 북</h2></div>
        <div className="empty">
          <p>아직 북에 포지션이 없습니다. 첫 포지션을 평가해 추가하면 여기에 요약이 쌓입니다.</p>
        </div>
      </>
    )
  }

  // 백엔드가 구버전이면 한도 사용률 칸만 비우고 나머지는 그대로 보여준다.
  const gross = summary.limit_usage?.find((u) => u.code === 'GROSS_EXPOSURE')
  const netTone = tone(summary.totals.net_pnl)

  return (
    <>
      <div className="section-head">
        <h2>오늘의 북</h2>
        <span className="meta">포지션 {summary.totals.position_count}건</span>
      </div>
      <dl className="strip">
        <div>
          <dt>순손익</dt>
          <dd className={`tone-${netTone}`}>{formatSignedWon(summary.totals.net_pnl)}</dd>
        </div>
        <div><dt>총노출</dt><dd>{formatWon(summary.totals.gross_exposure)}</dd></div>
        <div>
          <dt>{gross?.label ?? '총노출 한도'} 사용률</dt>
          <dd className="is-text">
            <span className="num">{gross ? `${(Number(gross.ratio) * 100).toFixed(2)}%` : '-'}</span>
            {gross && (
              <span className="usage">
                {/* 배경 트랙이 채워진 진행 막대는 쓰지 않는다. 채워진 길이만 그린다. */}
                <span className={`usage-bar${Number(gross.ratio) >= 0.8 ? ' is-warn' : ''}`}
                  style={{ width: usageBarWidth(gross.ratio) }} aria-hidden />
                <span className="usage-label">한도 {formatWon(gross.limit)}</span>
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt>마지막 평가</dt>
          <dd className="is-text">{relativeTime(summary.last_valued_at)}</dd>
        </div>
      </dl>
    </>
  )
}
