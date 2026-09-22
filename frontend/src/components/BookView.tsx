import { TrayIcon, WarningCircleIcon } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import { api, messagesOf } from '../api'
import {
  assetLabel, directionLabel, formatPrice, formatSignedWon, formatWon, isNumeric, tone,
} from '../format'
import type { BookResponse, BookSummary, Position, Totals } from '../types'

interface Props {
  refreshKey: number
  onGoToValuation: () => void
}

interface Row {
  mark: string | null
  netPnl: string | null
  costs: string | null
  basis: string
  stale: boolean
}

const RECON_LABEL = { MATCHED: '일치', MISMATCHED: '불일치', SKIPPED: '건너뜀' } as const

export default function BookView({ refreshKey, onGoToValuation }: Props) {
  const [positions, setPositions] = useState<Position[]>([])
  const [summary, setSummary] = useState<BookSummary | null>(null)
  const [run, setRun] = useState<BookResponse | null>(null)
  const [marks, setMarks] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [errors, setErrors] = useState<string[]>([])
  const settledRun = useRef<string | null>(null)

  const [reloadTick, setReloadTick] = useState(0)
  const reload = () => setReloadTick((t) => t + 1)

  // 외부 시스템(백엔드)과 동기화: 부모의 refreshKey 또는 내부 작업 후 다시 읽는다.
  useEffect(() => {
    let cancelled = false
    Promise.all([api.positions(), api.bookSummary()])
      .then(([p, s]) => {
        if (cancelled) return
        setPositions(p)
        setSummary(s)
      })
      .catch((err) => {
        if (!cancelled) setErrors(messagesOf(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [refreshKey, reloadTick])

  async function revalue() {
    const bad = Object.entries(marks).filter(([, v]) => v.trim() !== '' && !isNumeric(v))
    if (bad.length) {
      setErrors(['평가가격은 숫자로 입력하세요.'])
      return
    }
    const payload = Object.fromEntries(Object.entries(marks).filter(([, v]) => v.trim() !== ''))
    setBusy(true)
    setErrors([])
    try {
      const r = await api.revalue(payload)
      setRun(r)
      settledRun.current = r.run_id
      reload()
    } catch (err) {
      setErrors(messagesOf(err))
    } finally {
      setBusy(false)
    }
  }

  async function close(id: number) {
    setBusy(true)
    try {
      await api.closePosition(id)
      setRun(null)
      reload()
    } catch (err) {
      setErrors(messagesOf(err))
    } finally {
      setBusy(false)
    }
  }

  function rowFor(p: Position): Row {
    const r = run?.positions.find((x) => x.position_id === p.id)
    if (r) {
      return {
        mark: r.mark_price, netPnl: r.valuation.net_pnl, costs: r.valuation.total_costs,
        basis: `${r.price_as_of}, ${r.price_source}`, stale: r.price_is_stale,
      }
    }
    if (p.latest) {
      return {
        mark: p.latest.mark_price, netPnl: p.latest.net_pnl, costs: p.latest.total_costs,
        basis: `${p.latest.price_as_of}, ${p.latest.price_source}`, stale: false,
      }
    }
    return { mark: null, netPnl: null, costs: null, basis: '아직 평가하지 않음', stale: false }
  }

  const totals: Totals | undefined = run?.totals ?? summary?.totals
  const byClass = run?.by_asset_class ?? summary?.by_asset_class ?? {}
  const breaches = run?.breaches ?? summary?.breaches ?? []
  const allErrors = [...errors, ...(run?.errors ?? [])]
  const justRevalued = run !== null && settledRun.current === run.run_id

  if (loading) return <BookSkeleton />

  return (
    <section className="book">
      <div className="book-bar">
        <p className="book-note">
          주식은 저장된 종목코드로 종가를 조회하고, 선물은 평가가격 칸에 입력한 값으로 평가합니다.
        </p>
        <button type="button" className="btn btn-primary" onClick={revalue}
          disabled={busy || positions.length === 0}>
          {busy ? '평가 중' : '전체 재평가'}
        </button>
      </div>

      {totals && (
        <dl className="strip">
          <div><dt>총노출</dt><dd>{formatWon(totals.gross_exposure)}</dd></div>
          <div><dt>순노출</dt><dd>{formatSignedWon(totals.net_exposure)}</dd></div>
          <div>
            <dt>순손익</dt>
            <dd className={`tone-${tone(totals.net_pnl)}`}>{formatSignedWon(totals.net_pnl)}</dd>
          </div>
          <div>
            <dt>엔진·SQL 대사</dt>
            <dd className="is-text" title={run?.reconciliation.detail}>
              {busy ? (
                <span className="badge">대사 중</span>
              ) : run ? (
                <span className={`badge ${run.reconciliation.status === 'MATCHED' ? 'is-ok' : 'is-warn'}`}>
                  {RECON_LABEL[run.reconciliation.status]}
                </span>
              ) : (
                <span className="badge">재평가 후 표시</span>
              )}
            </dd>
          </div>
        </dl>
      )}

      {breaches.length > 0 && (
        <ul className="alerts">
          {breaches.map((b) => (
            <li className="alert" key={b.code + b.message} role="alert">
              <WarningCircleIcon size={15} weight="fill" aria-hidden />
              <span>한도 초과: {b.message}</span>
            </li>
          ))}
        </ul>
      )}
      {allErrors.length > 0 && (
        <ul className="alerts">
          {allErrors.map((m) => (
            <li className="alert" key={m} role="alert">
              <WarningCircleIcon size={15} weight="fill" aria-hidden />
              <span>{m}</span>
            </li>
          ))}
        </ul>
      )}

      {positions.length === 0 ? (
        <div className="empty">
          <TrayIcon size={28} weight="light" aria-hidden />
          <p>북이 비어 있습니다. 포지션을 평가한 뒤 북에 추가하면 여기에 쌓입니다.</p>
          <button type="button" className="btn btn-secondary" onClick={onGoToValuation}>
            포지션 평가하기
          </button>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th scope="col">종목</th>
                <th scope="col">방향</th>
                <th scope="col" className="num">수량</th>
                <th scope="col" className="num">진입가</th>
                <th scope="col" className="num">평가가격</th>
                <th scope="col" className="num">순손익</th>
                <th scope="col" className="num">비용</th>
                <th scope="col">평가 기준</th>
                <th scope="col"><span className="sr-only">작업</span></th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const r = rowFor(p)
                const settled = justRevalued
                  && run?.positions.some((x) => x.position_id === p.id)
                return (
                  <tr key={p.id}>
                    <td>
                      <span className="cell-main">{p.name ?? p.symbol}</span>
                      <span className="cell-sub">{assetLabel(p.asset_class)} {p.symbol}</span>
                    </td>
                    <td className={p.direction === 'LONG' ? 'tone-gain' : 'tone-loss'}>
                      {directionLabel(p.direction)}
                    </td>
                    <td className="num">{formatWon(String(p.quantity))}</td>
                    <td className="num">{formatPrice(p.entry_price)}</td>
                    <td className="num">
                      {p.asset_class === 'FUTURE' ? (
                        <input className="mark-input" inputMode="decimal"
                          aria-label={`${p.symbol} 평가가격`}
                          placeholder={r.mark ?? '입력'} value={marks[p.id] ?? ''}
                          onChange={(e) => setMarks((m) => ({ ...m, [p.id]: e.target.value }))} />
                      ) : formatPrice(r.mark)}
                    </td>
                    <td className={`num tone-${tone(r.netPnl)}${settled ? ' row-settled' : ''}`}>
                      {formatSignedWon(r.netPnl)}
                    </td>
                    <td className="num">{formatWon(r.costs)}</td>
                    <td className={r.stale ? 'cell-basis is-stale' : 'cell-basis'}>{r.basis}</td>
                    <td>
                      <button type="button" className="btn-quiet" onClick={() => close(p.id)}
                        disabled={busy}>
                        청산 처리
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(byClass).length > 0 && (
        <div className="table-wrap">
          <table className="grid grid-compact">
            <caption>상품군별 집계 (SQL 뷰 v_book_by_asset_class와 같은 기준)</caption>
            <thead>
              <tr>
                <th scope="col">상품군</th>
                <th scope="col" className="num">포지션</th>
                <th scope="col" className="num">총노출</th>
                <th scope="col" className="num">순노출</th>
                <th scope="col" className="num">순손익</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(byClass).map(([cls, t]) => (
                <tr key={cls}>
                  <td>{assetLabel(cls)}</td>
                  <td className="num">{t.position_count}</td>
                  <td className="num">{formatWon(t.gross_exposure)}</td>
                  <td className="num">{formatSignedWon(t.net_exposure)}</td>
                  <td className={`num tone-${tone(t.net_pnl)}`}>{formatSignedWon(t.net_pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/** 최종 모양과 같은 자리를 차지하는 스켈레톤. 원형 스피너는 쓰지 않는다. */
function BookSkeleton() {
  return (
    <section className="book" aria-busy="true" aria-label="북 현황을 불러오는 중">
      <div className="book-bar">
        <span className="skeleton" style={{ width: '32ch', height: 18 }}>불러오는 중</span>
        <span className="skeleton" style={{ width: 96, height: 36 }} />
      </div>
      <dl className="strip">
        {['총노출', '순노출', '순손익', '엔진·SQL 대사'].map((label) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd><span className="skeleton" style={{ width: '9ch', display: 'inline-block' }}>0</span></dd>
          </div>
        ))}
      </dl>
      <div className="table-wrap">
        <table className="grid">
          <tbody>
            {[0, 1, 2].map((i) => (
              <tr key={i}>
                <td><span className="skeleton" style={{ width: '10ch', display: 'inline-block' }}>0</span></td>
                <td><span className="skeleton" style={{ width: '4ch', display: 'inline-block' }}>0</span></td>
                <td className="num"><span className="skeleton" style={{ width: '8ch', display: 'inline-block' }}>0</span></td>
                <td className="num"><span className="skeleton" style={{ width: '10ch', display: 'inline-block' }}>0</span></td>
                <td className="num"><span className="skeleton" style={{ width: '10ch', display: 'inline-block' }}>0</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
