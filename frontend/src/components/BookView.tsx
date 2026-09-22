import { useEffect, useState } from 'react'
import { api, messagesOf } from '../api'
import {
  assetLabel, directionLabel, formatPrice, formatSignedWon, formatWon, isNumeric, tone,
} from '../format'
import type { BookResponse, BookSummary, Position, Totals } from '../types'

interface Props {
  refreshKey: number
}

interface Row {
  mark: string | null
  netPnl: string | null
  costs: string | null
  basis: string
  stale: boolean
}

export default function BookView({ refreshKey }: Props) {
  const [positions, setPositions] = useState<Position[]>([])
  const [summary, setSummary] = useState<BookSummary | null>(null)
  const [run, setRun] = useState<BookResponse | null>(null)
  const [marks, setMarks] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])

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
    return () => {
      cancelled = true
    }
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
      setRun(await api.revalue(payload))
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

  return (
    <section className="book">
      <div className="book-bar">
        <p className="book-note">
          주식은 저장된 종목코드로 종가를 조회하고, 선물은 평가가격 칸에 입력한 값으로 평가합니다.
        </p>
        <button type="button" className="btn-primary" onClick={revalue} disabled={busy || positions.length === 0}>
          {busy ? '평가 중' : '전체 재평가'}
        </button>
      </div>

      {totals && (
        <dl className="strip">
          <div><dt>총노출</dt><dd>{formatWon(totals.gross_exposure)}</dd></div>
          <div><dt>순노출</dt><dd>{formatSignedWon(totals.net_exposure)}</dd></div>
          <div><dt>순손익</dt><dd className={`tone-${tone(totals.net_pnl)}`}>{formatSignedWon(totals.net_pnl)}</dd></div>
          <div>
            <dt>엔진·SQL 대사</dt>
            <dd className={run?.reconciliation.status === 'MISMATCHED' ? 'tone-warn' : undefined}
              title={run?.reconciliation.detail}>
              {run ? { MATCHED: '일치', MISMATCHED: '불일치', SKIPPED: '건너뜀' }[run.reconciliation.status] : '재평가 후 표시'}
            </dd>
          </div>
        </dl>
      )}

      {breaches.length > 0 && (
        <ul className="alerts alerts-limit" role="alert">
          {breaches.map((b) => <li key={b.code + b.message}>한도 초과: {b.message}</li>)}
        </ul>
      )}
      {allErrors.length > 0 && (
        <ul className="alerts" role="alert">
          {allErrors.map((m) => <li key={m}>{m}</li>)}
        </ul>
      )}

      {positions.length === 0 ? (
        <p className="empty">북이 비어 있습니다. 포지션 평가 화면에서 북에 추가를 누르세요.</p>
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
                return (
                  <tr key={p.id}>
                    <td>
                      <span className="cell-main">{p.name ?? p.symbol}</span>
                      <span className="cell-sub">{assetLabel(p.asset_class)} {p.symbol}</span>
                    </td>
                    <td className={p.direction === 'LONG' ? 'tone-gain' : 'tone-loss'}>{directionLabel(p.direction)}</td>
                    <td className="num">{formatWon(String(p.quantity))}</td>
                    <td className="num">{formatPrice(p.entry_price)}</td>
                    <td className="num">
                      {p.asset_class === 'FUTURE' ? (
                        <input className="mark-input" inputMode="decimal" aria-label={`${p.symbol} 평가가격`}
                          placeholder={r.mark ?? '입력'} value={marks[p.id] ?? ''}
                          onChange={(e) => setMarks((m) => ({ ...m, [p.id]: e.target.value }))} />
                      ) : formatPrice(r.mark)}
                    </td>
                    <td className={`num tone-${tone(r.netPnl)}`}>{formatSignedWon(r.netPnl)}</td>
                    <td className="num">{formatWon(r.costs)}</td>
                    <td className={r.stale ? 'cell-basis is-stale' : 'cell-basis'}>{r.basis}</td>
                    <td>
                      <button type="button" className="btn-text" onClick={() => close(p.id)} disabled={busy}>
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
