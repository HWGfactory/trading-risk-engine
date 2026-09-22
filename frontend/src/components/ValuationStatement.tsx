import { ListMagnifyingGlassIcon } from '@phosphor-icons/react'
import {
  RATIO_KEYS, formatRate, formatRatio, formatSignedWon, formatWon, tone,
} from '../format'
import { tracedClass } from '../trace'
import type { TraceApi } from '../trace'
import type { ValuationResponse } from '../types'
import AnimatedWon from './AnimatedWon'

interface Props {
  result: ValuationResponse | null
  trace: TraceApi
  busy?: boolean
}

export default function ValuationStatement({ result, trace, busy = false }: Props) {
  if (!result) {
    return (
      <section className="panel statement-empty" aria-live="polite">
        <ListMagnifyingGlassIcon size={26} weight="light" aria-hidden />
        <p>
          전표에 수량과 진입가, 평가가격을 넣으면 순손익과 그 계산 근거가 여기에 나옵니다.
        </p>
      </section>
    )
  }

  const { valuation: v, applied } = result
  const netTone = tone(v.net_pnl)

  return (
    <section className={`panel statement${busy ? ' is-busy' : ''}`}>
      <div className="headline">
        <span className="headline-label">순손익</span>
        <span className={`headline-value tone-${netTone}`}>
          <AnimatedWon value={v.net_pnl} /><small>원</small>
        </span>
        <span className={`headline-sub tone-${netTone}`}>
          명목 대비 {formatRatio(v.return_on_notional)}
        </span>
      </div>

      <dl className="figures">
        <div><dt>평가 명목금액</dt><dd>{formatWon(v.mark_notional)}</dd></div>
        <div>
          <dt>평가손익 (비용 전)</dt>
          <dd className={`tone-${tone(v.gross_pnl)}`}>{formatSignedWon(v.gross_pnl)}</dd>
        </div>
        <div><dt>거래비용</dt><dd>{formatWon(v.total_costs)}</dd></div>
        {v.initial_margin !== null ? (
          <div>
            <dt>증거금 대비</dt>
            <dd className={`tone-${netTone}`}>{formatRatio(v.return_on_margin)}</dd>
          </div>
        ) : (
          <div><dt>거래세</dt><dd>{formatWon(v.transaction_tax)}</dd></div>
        )}
      </dl>

      <h2 className="ledger-title">계산 근거</h2>
      {/*
        좁은 화면에서 행을 세로로 쌓으려면 display를 바꿔야 하는데, 그러면 브라우저가
        표 의미를 잃는다. role을 명시해 두면 넓은 화면에서는 기본 의미와 같고
        좁은 화면에서도 행·머리글 관계가 보조기기에 그대로 전달된다.
      */}
      <table className="ledger" role="table">
        <tbody role="rowgroup">
          {v.trace.map((s) => (
            <tr key={s.key} role="row"
              className={[
                s.key === 'net_pnl' ? 'ledger-total' : '',
                'is-traceable',
                tracedClass(trace.isStepTraced(s.key)).trim(),
              ].filter(Boolean).join(' ')}
              tabIndex={0}
              aria-label={`${s.label}. 이 줄에 쓰인 입력을 전표에서 강조합니다.`}
              onMouseEnter={() => trace.focusStep(s.key)}
              onMouseLeave={trace.clear}
              onFocus={() => trace.focusStep(s.key)}
              onBlur={trace.clear}>
              <th scope="row" role="rowheader">{s.label}</th>
              <td className="ledger-formula" role="cell">{s.formula}</td>
              <td className="ledger-value" role="cell">
                {RATIO_KEYS.has(s.key) ? formatRatio(s.value, 4) : formatWon(s.value)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="basis">
        <p>
          거래승수 {formatWon(applied.multiplier)}
          {applied.contract_name && ` (${applied.contract_name})`}
          {applied.tax_rate_total && `, ${applied.tax_market} 거래세 합계 ${formatRate(applied.tax_rate_total)}`}
        </p>
        {applied.tax_source && <p>세율 근거: {applied.tax_source}</p>}
        {applied.contract_source && <p>계약명세 근거: {applied.contract_source}</p>}
        <p>
          설정 확인일 {applied.verified_as_of}.{' '}
          {applied.tax_market
            ? '청산 수수료와 매수 포지션의 거래세는 평가가격으로 청산한다고 가정한 추정치입니다.'
            : '청산 수수료는 평가가격으로 청산한다고 가정한 추정치입니다.'}
        </p>
      </div>
    </section>
  )
}
