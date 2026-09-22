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

export interface PositionCreate extends TradeTerms {
  symbol: string
  name: string | null
}

export interface TraceStep {
  key: string
  label: string
  formula: string
  value: Dec
}

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
  symbol: string
  name: string | null
  asset_class: AssetClass
  market: Market | null
  contract_code: string | null
  multiplier: Dec
  direction: Direction
  quantity: number
  entry_price: Dec
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

export interface BookSummary {
  totals: Totals
  by_asset_class: Record<string, Totals>
  breaches: Breach[]
}
