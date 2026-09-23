import { ArrowLeftIcon } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { api, messagesOf } from '../api'
import { assetLabel, formatPrice, formatSignedWon, formatWon, tone } from '../format'
import type { Position, Trade } from '../types'

interface Props {
  position: Position
  onBack: () => void
}

/**
 * 종목 상세. 체결 이력과 평균단가가 어떻게 움직였는지 보여준다.
 *
 * 계산 근거 표와 같은 방식이다. 한 줄이 한 사건이고, 그 사건이 만든 값이 오른쪽에 온다.
 * 값은 전부 체결 시점에 저장된 것이라 지금 다시 계산하지 않는다.
 */
export default function PositionDetail({ position, onBack }: Props) {
  const [trades, setTrades] = useState<Trade[] | null>(null)
  const [errors, setErrors] = useState<string[]>([])

  useEffect(() => {
    let cancelled = false
    api.trades(position.instrument_id)
      .then((t) => { if (!cancelled) setTrades(t) })
      .catch((err) => { if (!cancelled) setErrors(messagesOf(err)) })
    return () => { cancelled = true }
  }, [position.instrument_id])

  return (
    <section className="book">
      <div className="book-bar">
        <button type="button" className="btn btn-secondary" onClick={onBack}>
          <ArrowLeftIcon size={14} weight="bold" aria-hidden />
          북 현황
        </button>
        <p className="book-note">
          {position.name ?? position.symbol} · {assetLabel(position.asset_class)} {position.symbol}
        </p>
      </div>

      <dl className="strip">
        <div>
          <dt>순수량</dt>
          <dd>{position.net_quantity > 0 ? '+' : ''}{formatWon(String(position.net_quantity))}</dd>
        </div>
        <div><dt>평균단가</dt><dd>{formatPrice(position.avg_price)}</dd></div>
        <div>
          <dt>실현손익 누적</dt>
          <dd className={`tone-${tone(position.realized_pnl)}`}>
            {formatSignedWon(position.realized_pnl)}
          </dd>
        </div>
        <div>
          <dt>평가손익</dt>
          <dd className={`tone-${tone(position.latest?.net_pnl)}`}>
            {formatSignedWon(position.latest?.net_pnl)}
          </dd>
        </div>
      </dl>

      {errors.length > 0 && (
        <ul className="alerts">
          {errors.map((m) => <li className="alert" key={m} role="alert"><span>{m}</span></li>)}
        </ul>
      )}

      {trades === null ? (
        <div className="table-wrap">
          <table className="grid">
            <tbody>
              {[0, 1, 2].map((i) => (
                <tr key={i}>
                  <td colSpan={7}>
                    <span className="skeleton" style={{ width: '100%', display: 'inline-block' }}>0</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <caption>
              체결 이력과 평균단가 변화. 각 줄의 값은 그 체결 시점에 저장된 것이다.
            </caption>
            <thead>
              <tr>
                <th scope="col">체결 시각</th>
                <th scope="col">구분</th>
                <th scope="col" className="num">수량</th>
                <th scope="col" className="num">체결가</th>
                <th scope="col" className="num">실현손익</th>
                <th scope="col" className="num">비용</th>
                <th scope="col" className="num">이후 평균단가</th>
                <th scope="col" className="num">이후 수량</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((t) => {
                const cost = Number(t.commission) + Number(t.transaction_tax)
                return (
                  <tr key={t.id}>
                    <td className="cell-basis">{t.traded_at.replace('T', ' ').slice(0, 16)}</td>
                    <td className={t.side === 'BUY' ? 'tone-gain' : 'tone-loss'}>
                      {t.side === 'BUY' ? '매수' : '매도'}
                      {t.closed_quantity > 0 && (
                        <span className="cell-sub">청산 {t.closed_quantity}</span>
                      )}
                    </td>
                    <td className="num">{formatWon(String(t.quantity))}</td>
                    <td className="num">{formatPrice(t.price)}</td>
                    <td className={`num tone-${tone(t.realized_pnl)}`}>
                      {t.closed_quantity > 0 ? formatSignedWon(t.realized_pnl) : '-'}
                    </td>
                    <td className="num">{cost === 0 ? '-' : formatWon(String(cost))}</td>
                    <td className="num">{formatPrice(t.avg_price_after)}</td>
                    <td className="num">
                      {t.qty_after > 0 ? '+' : ''}{formatWon(String(t.qty_after))}
                    </td>
                  </tr>
                )
              })}
              {trades.length === 0 && (
                <tr><td colSpan={8} className="empty">체결 이력이 없습니다.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
