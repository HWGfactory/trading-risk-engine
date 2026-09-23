// 백엔드 app/schemas.py 와 1:1로 맞춘다.
// Decimal 값은 정밀도 보존을 위해 문자열(string)로 온다. 표시 직전에만 숫자로 바꾼다.

export type AssetClass = 'EQUITY' | 'FUTURE'
export type Direction = 'LONG' | 'SHORT'
export type Market = 'KOSPI' | 'KOSDAQ'
export type Dec = string

export interface TradeTerms {
  asset_class: AssetClass
  direction: Direction
  quantity: number
  entry_price: Dec
  market: Market | null
  contract_code: string | null
  commission_rate: Dec
  margin_rate: Dec | null
}

export interface ValuationRequest extends TradeTerms {
  mark_price: Dec
}

export type Side = 'BUY' | 'SELL'

/** 체결 입력. 포지션을 직접 만들지 않고 체결을 쌓는다. */
export interface TradeCreate {
  asset_class: AssetClass
  side: Side
  symbol: string
  name: string | null
  quantity: number
  price: Dec
  market: Market | null
  contract_code: string | null
  commission_rate: Dec
  margin_rate: Dec | null
}

export interface TraceStep {
  key: string
  label: string
  formula: string
  value: Dec
  /** 이 값이 의존하는 입력·설정값. 엔진이 알려주므로 프론트는 추측하지 않는다. */
  inputs: TraceInput[]
}

/** 전표 입력 필드명과 설정값 키. backend linear.py의 TraceStep.inputs와 같은 어휘다. */
export type TraceInput =
  | 'entry_price' | 'mark_price' | 'quantity' | 'direction'
  | 'commission_rate' | 'margin_rate' | 'market'
  | 'multiplier' | 'tax_rate' | 'asset_class'

export interface Valuation {
  entry_notional: Dec
  mark_notional: Dec
  signed_exposure: Dec
  gross_pnl: Dec
  entry_commission: Dec
  exit_commission: Dec
  transaction_tax: Dec
  total_costs: Dec
  net_pnl: Dec
  return_on_notional: Dec
  initial_margin: Dec | null
  current_margin: Dec | null
  return_on_margin: Dec | null
  trace: TraceStep[]
}

export interface AppliedConventions {
  multiplier: Dec
  contract_name: string | null
  tax_market: string | null
  tax_rate_total: Dec | null
  tax_source: string | null
  contract_source: string | null
  verified_as_of: string
}

export interface ValuationResponse {
  valuation: Valuation
  applied: AppliedConventions
}

export interface Quote {
  ticker: string
  name: string | null
  close: Dec
  as_of: string
  source: string
  is_stale: boolean
}

export interface Contract {
  code: string
  name: string
  multiplier: Dec
  tick_size: Dec
}

export interface Reference {
  verified_as_of: string
  default_commission_rate: Dec
  contracts: Contract[]
  tax_rules: { market: string; securities_tax: Dec; rural_special_tax: Dec; total: Dec }[]
  tax_source: string
  contract_source: string
  limits: { max_position_notional: Dec; max_gross_exposure: Dec; max_loss: Dec }
}

export interface LatestValuation {
  valued_at: string
  mark_price: Dec
  price_source: string
  price_as_of: string
  signed_exposure: Dec
  gross_pnl: Dec
  total_costs: Dec
  net_pnl: Dec
}

export interface Position {
  id: number
  instrument_id: number
  symbol: string
  name: string | null
  asset_class: AssetClass
  market: Market | null
  contract_code: string | null
  multiplier: Dec
  /** 매수 +, 매도 −. 부호가 방향이다. */
  net_quantity: number
  direction: Direction
  quantity: number
  /** 이동평균 단가. entry_price와 같은 값이며 기존 화면 호환용으로 둘 다 내려온다. */
  avg_price: Dec
  entry_price: Dec
  realized_pnl: Dec
  entry_cost: Dec
  commission_rate: Dec
  margin_rate: Dec | null
  opened_at: string
  latest: LatestValuation | null
}

export interface Totals {
  position_count: number
  gross_exposure: Dec
  net_exposure: Dec
  gross_pnl: Dec
  total_costs: Dec
  net_pnl: Dec
}

export interface Breach {
  code: string
  message: string
  limit: Dec
  actual: Dec
}

export interface RevaluedPosition {
  position_id: number
  symbol: string
  name: string | null
  asset_class: AssetClass
  direction: Direction
  quantity: number
  entry_price: Dec
  mark_price: Dec
  price_source: string
  price_as_of: string
  price_is_stale: boolean
  valuation: Valuation
}

export interface BookResponse {
  run_id: string
  positions: RevaluedPosition[]
  totals: Totals
  by_asset_class: Record<string, Totals>
  breaches: Breach[]
  reconciliation: { status: 'MATCHED' | 'MISMATCHED' | 'SKIPPED'; detail: string }
  errors: string[]
}

export interface LimitUsage {
  code: 'GROSS_EXPOSURE' | 'LOSS_LIMIT' | 'POSITION_NOTIONAL'
  label: string
  used: Dec
  limit: Dec
  /** used ÷ limit. 백엔드가 Decimal로 계산해 내려준다. */
  ratio: Dec
}

export interface BookSummary {
  totals: Totals
  by_asset_class: Record<string, Totals>
  breaches: Breach[]
  limit_usage: LimitUsage[]
  last_valued_at: string | null
}

// ---------- 체결과 스냅샷 (backend schemas.py와 1:1) ----------

export interface Trade {
  id: number
  instrument_id: number
  symbol: string
  name: string | null
  asset_class: AssetClass
  side: Side
  quantity: number
  price: Dec
  commission_rate: Dec
  /** 이 체결 중 청산에 쓰인 수량 */
  closed_quantity: number
  /** 이 체결이 확정한 실현손익 (비용 차감 후) */
  realized_pnl: Dec
  commission: Dec
  transaction_tax: Dec
  /** 이 체결 직후 평균단가 */
  avg_price_after: Dec
  /** 이 체결 직후 순수량 */
  qty_after: number
  traded_at: string
}

export interface TradeResponse {
  trade: Trade
  position: Position
  trace: TraceStep[]
  realized_gross: Dec
  message: string
}

export interface TradePreview {
  holds: boolean
  net_quantity_before: number
  avg_price_before: Dec
  net_quantity_after: number
  avg_price_after: Dec
  closed_quantity: number
  realized_gross: Dec
  /** 방향 전환(규칙 3) 여부. 백엔드가 판단해 내려준다. */
  flips: boolean
  /** 전환 후 새로 생기는 수량. flips가 false면 0. */
  opened_quantity: number
  direction_before: Direction | null
  direction_after: Direction | null
  trace: TraceStep[]
}

export interface SnapshotRow {
  instrument_id: number
  symbol: string
  name: string | null
  net_quantity: number
  avg_price: Dec
  mark_price: Dec
  price_source: string
  unrealized_pnl: Dec
  realized_pnl_cumulative: Dec
  signed_exposure: Dec
}

export interface SnapshotResponse {
  snapshot_date: string
  revision: number
  rows: SnapshotRow[]
  errors: string[]
}

export interface HistoryRow {
  snapshot_date: string
  position_count: number
  unrealized_pnl: Dec
  realized_pnl_cumulative: Dec
  gross_exposure: Dec
  net_exposure: Dec
}

export interface BookHistory {
  rows: HistoryRow[]
}
