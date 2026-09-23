import { CheckCircleIcon, WarningCircleIcon } from '@phosphor-icons/react'
import { useEffect, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { api, messagesOf } from '../api'
import { formatPrice, formatSignedWon, isNumeric, percentToRate, rateToPercent, tone } from '../format'
import { tracedClass } from '../trace'
import type { TraceApi } from '../trace'
import type {
  AssetClass, Direction, Market, Quote, Reference, TraceInput, TradeCreate, TradePreview,
  TradeTerms, ValuationRequest,
} from '../types'

interface Props {
  reference: Reference
  busy: boolean
  trace: TraceApi
  addedName: string | null
  onEvaluate: (req: ValuationRequest, live: boolean) => void
  onBookTrade: (req: TradeCreate) => void
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

type Built<T> = { ok: true; value: T } | { ok: false; errors: Record<string, string> }

/** role="radio"를 쓰면 화살표키로 선택이 옮겨져야 한다. 로빙 tabindex도 함께 둔다. */
function useRadioGroup<T extends string>(values: readonly T[], current: T, set: (v: T) => void) {
  return (e: KeyboardEvent) => {
    const i = values.indexOf(current)
    let next = i
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % values.length
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + values.length) % values.length
    else return
    e.preventDefault()
    set(values[next])
    const group = (e.currentTarget as HTMLElement).closest('[role=radiogroup]')
    group?.querySelectorAll<HTMLButtonElement>('[role=radio]')[next]?.focus()
  }
}

export default function DealTicket({
  reference, busy, trace, addedName, onEvaluate, onBookTrade,
}: Props) {
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
  const [quoteError, setQuoteError] = useState<string[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [markFilled, setMarkFilled] = useState(false)
  const [preview, setPreview] = useState<TradePreview | null>(null)

  const set = <K extends keyof TicketForm>(key: K, value: TicketForm[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const isEquity = form.assetClass === 'EQUITY'
  const contract = reference.contracts.find((c) => c.code === form.contractCode)

  function buildTerms(): Built<TradeTerms> {
    const errs: Record<string, string> = {}
    const qty = Number(form.quantity)
    if (form.quantity.trim() === '') errs.quantity = '수량을 입력하세요.'
    else if (!Number.isInteger(qty) || qty <= 0) errs.quantity = '1 이상의 정수로 입력하세요.'
    if (!isNumeric(form.entryPrice)) errs.entryPrice = '진입가를 숫자로 입력하세요.'
    if (!isNumeric(form.commissionPct)) errs.commissionPct = '숫자로 입력하세요. 없으면 0.'
    if (!isEquity && form.marginPct.trim() !== '' && !isNumeric(form.marginPct)) {
      errs.marginPct = '숫자로 입력하거나 비워 두세요.'
    }
    if (Object.keys(errs).length) return { ok: false, errors: errs }
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

  // 입력이 유효해지면 300ms 뒤 자동 평가한다. 버튼은 명시적 재평가용으로 남는다.
  const liveRef = useRef(onEvaluate)
  liveRef.current = onEvaluate
  useEffect(() => {
    const terms = buildTerms()
    if (!terms.ok || !isNumeric(form.markPrice)) return
    const id = setTimeout(() => {
      liveRef.current({ ...terms.value, mark_price: form.markPrice.trim() }, true)
    }, 300)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.assetClass, form.direction, form.quantity, form.entryPrice, form.markPrice,
      form.commissionPct, form.marginPct, form.market, form.contractCode])

  // 이미 보유 중인 종목이면 이번 체결 후 평균단가가 어떻게 되는지 미리 보여준다.
  // 저장하지 않는 조회라 전표를 고치는 동안 계속 갱신해도 안전하다.
  const symbolKey = isEquity ? form.ticker.trim() : form.futureSymbol.trim() || form.contractCode
  useEffect(() => {
    const terms = buildTerms()
    const ok = terms.ok && (isEquity ? /^[0-9A-Za-z]{6}$/.test(symbolKey) : symbolKey.length > 0)
    if (!ok) { setPreview(null); return }
    let cancelled = false
    const id = setTimeout(() => {
      api.previewTrade({
        asset_class: form.assetClass,
        side: form.direction === 'LONG' ? 'BUY' : 'SELL',
        symbol: symbolKey,
        name: null,
        quantity: terms.value.quantity,
        price: terms.value.entry_price,
        market: terms.value.market,
        contract_code: terms.value.contract_code,
        commission_rate: terms.value.commission_rate,
        margin_rate: terms.value.margin_rate,
      }).then((p) => { if (!cancelled) setPreview(p) })
        .catch(() => { if (!cancelled) setPreview(null) })
    }, 350)
    return () => { cancelled = true; clearTimeout(id) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbolKey, form.assetClass, form.direction, form.quantity, form.entryPrice,
      form.commissionPct, form.marginPct, form.market, form.contractCode])

  async function loadQuote() {
    setQuoteError([])
    setQuoteBusy(true)
    try {
      const q = await api.quote(form.ticker)
      setQuote(q)
      setForm((f) => ({ ...f, ticker: q.ticker, markPrice: q.close, name: q.name ?? f.name }))
      setMarkFilled(true)
      setTimeout(() => setMarkFilled(false), 600)
    } catch (err) {
      setQuote(null)
      setQuoteError(messagesOf(err))
    } finally {
      setQuoteBusy(false)
    }
  }

  function evaluate(e: FormEvent) {
    e.preventDefault()
    const terms = buildTerms()
    const errs = terms.ok ? {} : { ...terms.errors }
    if (!isNumeric(form.markPrice)) {
      errs.markPrice = '평가가격을 입력하세요. 주식은 시세 조회로 채울 수 있습니다.'
    }
    setErrors(errs)
    if (terms.ok && Object.keys(errs).length === 0) {
      onEvaluate({ ...terms.value, mark_price: form.markPrice.trim() }, false)
    } else {
      focusFirstError(errs)
    }
  }

  /** 체결 입력용 요청. 전표의 진입가가 체결가가 된다. */
  function buildTrade(): TradeCreate | null {
    const terms = buildTerms()
    const errs = terms.ok ? {} : { ...terms.errors }
    const symbol = isEquity ? form.ticker.trim() : form.futureSymbol.trim() || (contract?.name ?? '')
    if (isEquity && !/^[0-9A-Za-z]{6}$/.test(symbol)) errs.ticker = '종목코드 6자리를 입력하세요.'
    setErrors(errs)
    if (!terms.ok || Object.keys(errs).length > 0) {
      focusFirstError(errs)
      return null
    }
    return {
      asset_class: form.assetClass,
      side: form.direction === 'LONG' ? 'BUY' : 'SELL',
      symbol,
      name: isEquity ? form.name.trim() || null : contract?.name ?? null,
      quantity: terms.value.quantity,
      price: terms.value.entry_price,
      market: terms.value.market,
      contract_code: terms.value.contract_code,
      commission_rate: terms.value.commission_rate,
      margin_rate: terms.value.margin_rate,
    }
  }

  function bookTrade() {
    const req = buildTrade()
    if (req) onBookTrade(req)
  }

  function focusFirstError(errs: Record<string, string>) {
    const first = Object.keys(errs)[0]
    if (first) document.getElementById(first)?.focus()
  }

  const fieldProps = (id: string, input: TraceInput) => ({
    className: `field${tracedClass(trace.isInputTraced(input))}`,
    onFocusCapture: () => trace.focusInput(input),
    onBlurCapture: trace.clear,
    onMouseEnter: () => trace.focusInput(input),
    onMouseLeave: trace.clear,
    'data-trace': input,
    key: id,
  })

  const errorFor = (id: string) => errors[id]
  const inputA11y = (id: string) => ({
    id,
    'aria-invalid': errorFor(id) ? true : undefined,
    'aria-describedby': errorFor(id) ? `${id}-error` : undefined,
  })
  const ErrorText = ({ id }: { id: string }) =>
    errorFor(id) ? (
      <span className="field-error" id={`${id}-error`}>
        <WarningCircleIcon size={13} weight="fill" aria-hidden />{errorFor(id)}
      </span>
    ) : null

  const onDirKey = useRadioGroup(['LONG', 'SHORT'] as const, form.direction, (d) => set('direction', d))
  const onAssetKey = useRadioGroup(['EQUITY', 'FUTURE'] as const, form.assetClass, (a) => {
    set('assetClass', a); setQuote(null)
  })

  const sideClass = form.direction === 'LONG' ? 'is-buy' : 'is-sell'
  const canQuote = form.ticker.trim().length === 6

  return (
    <form className={`panel ticket ${sideClass}`} onSubmit={evaluate} noValidate>
      <div className={`segmented seg-group${tracedClass(trace.isInputTraced('direction'))}`}
        role="radiogroup" aria-label="방향" onKeyDown={onDirKey}>
        {(['LONG', 'SHORT'] as const).map((d) => (
          <button key={d} type="button" role="radio" aria-checked={form.direction === d}
            tabIndex={form.direction === d ? 0 : -1}
            className={`seg seg-${d === 'LONG' ? 'buy' : 'sell'}`}
            onClick={() => set('direction', d)}>
            {d === 'LONG' ? '매수' : '매도'}
          </button>
        ))}
      </div>

      <div className="segmented segmented-quiet" role="radiogroup" aria-label="상품"
        onKeyDown={onAssetKey}>
        {(['EQUITY', 'FUTURE'] as const).map((a) => (
          <button key={a} type="button" role="radio" aria-checked={form.assetClass === a}
            tabIndex={form.assetClass === a ? 0 : -1}
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
              <input {...inputA11y('ticker')} inputMode="text" maxLength={6} placeholder="005930"
                value={form.ticker} onChange={(e) => set('ticker', e.target.value.toUpperCase())} />
              <button type="button" className="btn btn-secondary" onClick={loadQuote}
                disabled={quoteBusy || !canQuote}>
                {quoteBusy ? '조회 중' : '시세 조회'}
              </button>
            </div>
            <ErrorText id="ticker" />
            {!canQuote && !errorFor('ticker') && (
              <p className="hint">6자리를 넣으면 종가를 조회할 수 있습니다.</p>
            )}
            {quote && (
              <p className={`hint ${quote.is_stale ? 'hint-warn' : ''}`}>
                {quote.name ?? quote.ticker} 종가 {formatPrice(quote.close)}원, {quote.as_of} 기준
                {`, 출처 ${quote.source}`}
                {quote.is_stale && '. 최근 거래일 종가가 아닙니다. 거래정지 여부를 확인하세요.'}
              </p>
            )}
            {quoteError.map((m) => (
              <span className="field-error" key={m}>
                <WarningCircleIcon size={13} weight="fill" aria-hidden />{m}
              </span>
            ))}
          </div>

          <div className="field-pair">
            <div className="field">
              <label htmlFor="name">종목명</label>
              <input id="name" placeholder="선택 입력" value={form.name}
                onChange={(e) => set('name', e.target.value)} />
            </div>
            <div {...fieldProps('market', 'market')}>
              <label htmlFor="market">시장</label>
              <select id="market" value={form.market}
                onChange={(e) => set('market', e.target.value as Market)}>
                <option value="KOSPI">코스피</option>
                <option value="KOSDAQ">코스닥</option>
              </select>
            </div>
          </div>
        </>
      ) : (
        <>
          <div {...fieldProps('contract', 'multiplier')}>
            <label htmlFor="contract">계약</label>
            <select id="contract" value={form.contractCode}
              onChange={(e) => set('contractCode', e.target.value)}>
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
        <div {...fieldProps('quantity', 'quantity')}>
          <label htmlFor="quantity">{isEquity ? '수량 (주)' : '수량 (계약)'}</label>
          <input {...inputA11y('quantity')} inputMode="numeric" required value={form.quantity}
            onChange={(e) => set('quantity', e.target.value)} />
          <ErrorText id="quantity" />
        </div>
        <div {...fieldProps('entryPrice', 'entry_price')}>
          <label htmlFor="entryPrice">진입가</label>
          <input {...inputA11y('entryPrice')} inputMode="decimal" required value={form.entryPrice}
            onChange={(e) => set('entryPrice', e.target.value)} />
          <ErrorText id="entryPrice" />
        </div>
      </div>

      <div {...fieldProps('markPrice', 'mark_price')}>
        <label htmlFor="markPrice">평가가격</label>
        <input {...inputA11y('markPrice')} inputMode="decimal" required value={form.markPrice}
          className={markFilled ? 'row-settled' : undefined}
          onChange={(e) => set('markPrice', e.target.value)} />
        <ErrorText id="markPrice" />
      </div>

      <div className="field-pair">
        <div {...fieldProps('commissionPct', 'commission_rate')}>
          <label htmlFor="commissionPct">수수료율 (%)</label>
          <input {...inputA11y('commissionPct')} inputMode="decimal" value={form.commissionPct}
            onChange={(e) => set('commissionPct', e.target.value)} />
          <ErrorText id="commissionPct" />
        </div>
        {!isEquity && (
          <div {...fieldProps('marginPct', 'margin_rate')}>
            <label htmlFor="marginPct">증거금률 (%)</label>
            <input {...inputA11y('marginPct')} inputMode="decimal" placeholder="선택 입력"
              value={form.marginPct} onChange={(e) => set('marginPct', e.target.value)} />
            <ErrorText id="marginPct" />
          </div>
        )}
      </div>

      <div className="ticket-live" role="status">
        {addedName && (
          <>
            <CheckCircleIcon size={14} weight="fill" aria-hidden />
            {addedName} 북에 추가했습니다
          </>
        )}
      </div>

      {preview && preview.holds && (
        <div className="preview">
          <span className="preview-label">이번 체결 후</span>
          {preview.closed_quantity > 0 ? (
            <>
              <span className="preview-line">
                {preview.closed_quantity}주 청산, 실현손익{' '}
                <span className={`num tone-${tone(preview.realized_gross)}`}>
                  {formatSignedWon(preview.realized_gross)}
                </span>{' '}
                <span className="cell-sub">(비용 전)</span>
              </span>
              <span className="preview-line">
                잔량 <span className="num">{Math.abs(preview.net_quantity_after)}</span>
                {preview.net_quantity_after === 0
                  ? ', 포지션이 닫힙니다'
                  : <>, 평균단가 <span className="num">{formatPrice(preview.avg_price_after)}</span></>}
              </span>
            </>
          ) : (
            <span className="preview-line">
              평균단가 <span className="num">{formatPrice(preview.avg_price_before)}</span>
              {' → '}
              <span className="num">{formatPrice(preview.avg_price_after)}</span>
              , 수량 <span className="num">{Math.abs(preview.net_quantity_before)}</span>
              {' → '}
              <span className="num">{Math.abs(preview.net_quantity_after)}</span>
            </span>
          )}
        </div>
      )}

      <div className="ticket-actions">
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? '평가 중' : '평가하기'}
        </button>
        <button type="button" className="btn btn-secondary" disabled={busy || (isEquity && !canQuote)}
          onClick={bookTrade}>
          체결 입력
        </button>
      </div>
      {isEquity && !canQuote && (
        <p className="btn-reason">체결을 입력하려면 종목코드 6자리가 필요합니다.</p>
      )}
    </form>
  )
}
