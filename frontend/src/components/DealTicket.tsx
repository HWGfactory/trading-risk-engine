import { useState } from 'react'
import type { FormEvent } from 'react'
import { api, messagesOf } from '../api'
import { formatPrice, isNumeric, percentToRate, rateToPercent } from '../format'
import type {
  AssetClass, Direction, Market, PositionCreate, Quote, Reference, TradeTerms, ValuationRequest,
} from '../types'

interface Props {
  reference: Reference
  busy: boolean
  onEvaluate: (req: ValuationRequest) => void
  onAddToBook: (req: PositionCreate) => void
}

interface TicketForm {
  assetClass: AssetClass
  direction: Direction
  ticker: string
  name: string
  market: Market
  contractCode: string
  futureSymbol: string
  quantity: string
  entryPrice: string
  markPrice: string
  commissionPct: string
  marginPct: string
}

type Built<T> = { ok: true; value: T } | { ok: false; errors: string[] }

export default function DealTicket({ reference, busy, onEvaluate, onAddToBook }: Props) {
  const [form, setForm] = useState<TicketForm>(() => ({
    assetClass: 'EQUITY',
    direction: 'LONG',
    ticker: '',
    name: '',
    market: 'KOSPI',
    contractCode: reference.contracts[0]?.code ?? '',
    futureSymbol: '',
    quantity: '',
    entryPrice: '',
    markPrice: '',
    commissionPct: rateToPercent(reference.default_commission_rate),
    marginPct: '',
  }))
  const [quote, setQuote] = useState<Quote | null>(null)
  const [quoteBusy, setQuoteBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])

  const set = <K extends keyof TicketForm>(key: K, value: TicketForm[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const isEquity = form.assetClass === 'EQUITY'
  const contract = reference.contracts.find((c) => c.code === form.contractCode)

  async function loadQuote() {
    setErrors([])
    setQuoteBusy(true)
    try {
      const q = await api.quote(form.ticker)
      setQuote(q)
      setForm((f) => ({ ...f, ticker: q.ticker, markPrice: q.close, name: q.name ?? f.name }))
    } catch (err) {
      setQuote(null)
      setErrors(messagesOf(err))
    } finally {
      setQuoteBusy(false)
    }
  }

  function buildTerms(): Built<TradeTerms> {
    const errs: string[] = []
    const qty = Number(form.quantity)
    if (!Number.isInteger(qty) || qty <= 0) errs.push('수량은 1 이상의 정수로 입력하세요.')
    if (!isNumeric(form.entryPrice)) errs.push('진입가를 숫자로 입력하세요.')
    if (!isNumeric(form.commissionPct)) errs.push('수수료율을 숫자로 입력하세요. 없으면 0.')
    if (!isEquity && form.marginPct.trim() !== '' && !isNumeric(form.marginPct)) {
      errs.push('증거금률은 숫자로 입력하거나 비워 두세요.')
    }
    if (errs.length) return { ok: false, errors: errs }
    return {
      ok: true,
      value: {
        asset_class: form.assetClass,
        direction: form.direction,
        quantity: qty,
        entry_price: form.entryPrice.trim(),
        market: isEquity ? form.market : null,
        contract_code: isEquity ? null : form.contractCode,
        commission_rate: percentToRate(form.commissionPct),
        margin_rate: !isEquity && form.marginPct.trim() !== '' ? percentToRate(form.marginPct) : null,
      },
    }
  }

  function evaluate(e: FormEvent) {
    e.preventDefault()
    const terms = buildTerms()
    const errs = terms.ok ? [] : terms.errors
    if (!isNumeric(form.markPrice)) errs.push('평가가격을 입력하세요. 주식은 시세 조회로 채울 수 있습니다.')
    setErrors(errs)
    if (terms.ok && errs.length === 0) onEvaluate({ ...terms.value, mark_price: form.markPrice.trim() })
  }

  function addToBook() {
    const terms = buildTerms()
    const errs = terms.ok ? [] : terms.errors
    const symbol = isEquity ? form.ticker.trim() : form.futureSymbol.trim() || (contract?.name ?? '')
    if (isEquity && !/^[0-9A-Za-z]{6}$/.test(symbol)) errs.push('종목코드 6자리를 입력하세요.')
    setErrors(errs)
    if (terms.ok && errs.length === 0) {
      onAddToBook({ ...terms.value, symbol, name: isEquity ? form.name.trim() || null : contract?.name ?? null })
    }
  }

  const sideClass = form.direction === 'LONG' ? 'is-buy' : 'is-sell'

  return (
    <form className={`ticket ${sideClass}`} onSubmit={evaluate} noValidate>
      <div className="segmented" role="radiogroup" aria-label="방향">
        {(['LONG', 'SHORT'] as const).map((d) => (
          <button key={d} type="button" role="radio" aria-checked={form.direction === d}
            className={`seg seg-${d === 'LONG' ? 'buy' : 'sell'}`} onClick={() => set('direction', d)}>
            {d === 'LONG' ? '매수' : '매도'}
          </button>
        ))}
      </div>

      <div className="segmented segmented-quiet" role="radiogroup" aria-label="상품">
        {(['EQUITY', 'FUTURE'] as const).map((a) => (
          <button key={a} type="button" role="radio" aria-checked={form.assetClass === a}
            className="seg" onClick={() => { set('assetClass', a); setQuote(null) }}>
            {a === 'EQUITY' ? '주식' : '선물'}
          </button>
        ))}
      </div>

      {isEquity ? (
        <>
          <div className="field">
            <label htmlFor="ticker">종목코드</label>
            <div className="field-row">
              <input id="ticker" inputMode="text" maxLength={6} placeholder="005930" value={form.ticker}
                onChange={(e) => set('ticker', e.target.value.toUpperCase())} />
              <button type="button" className="btn-secondary" onClick={loadQuote}
                disabled={quoteBusy || form.ticker.trim().length !== 6}>
                {quoteBusy ? '조회 중' : '시세 조회'}
              </button>
            </div>
            {quote && (
              <p className={`hint ${quote.is_stale ? 'hint-warn' : ''}`}>
                {quote.name ?? quote.ticker} 종가 {formatPrice(quote.close)}원, {quote.as_of} 기준, 출처 {quote.source}
                {quote.is_stale && '. 최근 거래일 종가가 아닙니다. 거래정지 여부를 확인하세요.'}
              </p>
            )}
          </div>
          <div className="field-pair">
            <div className="field">
              <label htmlFor="name">종목명</label>
              <input id="name" placeholder="선택 입력" value={form.name} onChange={(e) => set('name', e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="market">시장</label>
              <select id="market" value={form.market} onChange={(e) => set('market', e.target.value as Market)}>
                <option value="KOSPI">코스피</option>
                <option value="KOSDAQ">코스닥</option>
              </select>
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="field">
            <label htmlFor="contract">계약</label>
            <select id="contract" value={form.contractCode} onChange={(e) => set('contractCode', e.target.value)}>
              {reference.contracts.map((c) => (
                <option key={c.code} value={c.code}>{c.name}</option>
              ))}
            </select>
            {contract && (
              <p className="hint">
                거래승수 {formatPrice(contract.multiplier)}
                {Number(contract.tick_size) > 0 && `, 호가단위 ${contract.tick_size}`}
              </p>
            )}
          </div>
          <div className="field">
            <label htmlFor="futureSymbol">월물 표기</label>
            <input id="futureSymbol" placeholder="예: K200 2026-12" value={form.futureSymbol}
              onChange={(e) => set('futureSymbol', e.target.value)} />
          </div>
        </>
      )}

      <div className="field-pair">
        <div className="field">
          <label htmlFor="quantity">{isEquity ? '수량 (주)' : '수량 (계약)'}</label>
          <input id="quantity" inputMode="numeric" value={form.quantity} onChange={(e) => set('quantity', e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="entry">진입가</label>
          <input id="entry" inputMode="decimal" value={form.entryPrice} onChange={(e) => set('entryPrice', e.target.value)} />
        </div>
      </div>

      <div className="field">
        <label htmlFor="mark">평가가격</label>
        <input id="mark" inputMode="decimal" value={form.markPrice} onChange={(e) => set('markPrice', e.target.value)} />
      </div>

      <div className="field-pair">
        <div className="field">
          <label htmlFor="commission">수수료율 (%)</label>
          <input id="commission" inputMode="decimal" value={form.commissionPct}
            onChange={(e) => set('commissionPct', e.target.value)} />
        </div>
        {!isEquity && (
          <div className="field">
            <label htmlFor="margin">증거금률 (%)</label>
            <input id="margin" inputMode="decimal" placeholder="선택 입력" value={form.marginPct}
              onChange={(e) => set('marginPct', e.target.value)} />
          </div>
        )}
      </div>

      {errors.length > 0 && (
        <ul className="form-errors" role="alert">
          {errors.map((m) => <li key={m}>{m}</li>)}
        </ul>
      )}

      <div className="ticket-actions">
        <button type="submit" className="btn-primary" disabled={busy}>평가하기</button>
        <button type="button" className="btn-secondary" disabled={busy} onClick={addToBook}>북에 추가</button>
      </div>
    </form>
  )
}
