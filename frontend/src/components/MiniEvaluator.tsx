import { motion, useReducedMotion } from 'motion/react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import { formatRatio, formatWon, isNumeric, tone } from '../format'
import type { ValuationResponse } from '../types'
import AnimatedWon from './AnimatedWon'

/**
 * 홈 히어로의 실제 평가기.
 *
 * div로 흉내 낸 화면이 아니라 같은 /api/valuation/linear를 호출하는 진짜 컴포넌트다.
 * 값을 바꾸면 순손익과 계산 근거가 즉시 바뀐다. 시세 조회는 수 초가 걸려서 하지 않고,
 * 예시값을 채워 둔다.
 */
const EXAMPLE = { quantity: '100', entryPrice: '250000', markPrice: '277500' }

export default function MiniEvaluator() {
  const [form, setForm] = useState(EXAMPLE)
  const [direction, setDirection] = useState<'LONG' | 'SHORT'>('LONG')
  const [result, setResult] = useState<ValuationResponse | null>(null)
  const [offline, setOffline] = useState(false)
  const reduce = useReducedMotion()

  useEffect(() => {
    const qty = Number(form.quantity)
    if (!Number.isInteger(qty) || qty <= 0) return
    if (!isNumeric(form.entryPrice) || !isNumeric(form.markPrice)) return
    let cancelled = false
    const id = setTimeout(() => {
      api.value({
        asset_class: 'EQUITY', direction, quantity: qty, market: 'KOSPI', contract_code: null,
        entry_price: form.entryPrice.trim(), mark_price: form.markPrice.trim(),
        commission_rate: '0.00015', margin_rate: null,
      }).then((r) => { if (!cancelled) { setResult(r); setOffline(false) } })
        .catch(() => { if (!cancelled) setOffline(true) })
    }, 300)
    return () => { cancelled = true; clearTimeout(id) }
  }, [form, direction])

  const v = result?.valuation
  const netTone = tone(v?.net_pnl)
  const visible = v?.trace.slice(0, 4) ?? []

  return (
    <div>
      <p className="demo-label">
        <span className="demo-tag">예시</span>
        삼성전자 코스피 매수. 값을 바꾸면 근거가 함께 바뀝니다.
      </p>

      <div className="panel mini">
        <div className="mini-head">
          <span className="mini-symbol">삼성전자 <span className="cell-sub">주식 005930</span></span>
          <div className="segmented mini-side" role="radiogroup" aria-label="방향">
            {(['LONG', 'SHORT'] as const).map((d) => (
              <button key={d} type="button" role="radio" aria-checked={direction === d}
                tabIndex={direction === d ? 0 : -1}
                className={`seg seg-${d === 'LONG' ? 'buy' : 'sell'}`}
                onClick={() => setDirection(d)}>
                {d === 'LONG' ? '매수' : '매도'}
              </button>
            ))}
          </div>
        </div>

        <div className="mini-inputs">
          {([
            ['quantity', '수량 (주)', 'numeric'],
            ['entryPrice', '진입가', 'decimal'],
            ['markPrice', '평가가격', 'decimal'],
          ] as const).map(([key, label, mode]) => (
            <div className="field" key={key}>
              <label htmlFor={`mini-${key}`}>{label}</label>
              <input id={`mini-${key}`} inputMode={mode} value={form[key]}
                onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))} />
            </div>
          ))}
        </div>

        <div className="mini-result">
          <span className="headline-label">순손익</span>
          <span className={`headline-value tone-${netTone}`}>
            {offline ? '-' : <AnimatedWon value={v?.net_pnl} />}<small>원</small>
          </span>
          <span className={`headline-sub tone-${netTone}`}>
            {offline ? '백엔드에 연결되면 계산됩니다' : `명목 대비 ${formatRatio(v?.return_on_notional)}`}
          </span>
        </div>

        <div className="mini-trace">
          <table className="ledger" role="table">
            <tbody role="rowgroup">
              {visible.map((s, i) => (
                <motion.tr key={s.key} role="row"
                  initial={reduce ? false : { opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.26, delay: i * 0.08, ease: [0.16, 1, 0.3, 1] }}>
                  <th scope="row" role="rowheader">{s.label}</th>
                  <td className="ledger-formula" role="cell">{s.formula}</td>
                  <td className="ledger-value" role="cell">{formatWon(s.value)}</td>
                </motion.tr>
              ))}
              {visible.length === 0 && (
                <tr><td className="ledger-formula">계산 근거를 불러오는 중입니다.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
