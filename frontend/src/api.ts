import type {
  BookHistory, BookResponse, BookSummary, Position, Quote, Reference, SnapshotResponse,
  Trade, TradeCreate, TradePreview, TradeResponse, ValuationRequest, ValuationResponse,
} from './types'

export class ApiError extends Error {
  readonly messages: string[]

  constructor(messages: string[]) {
    super(messages.join('\n'))
    this.messages = messages
  }
}

/*
  API 주소.

  값이 없으면 상대경로(/api)를 그대로 쓴다. 로컬 개발에서 vite proxy가 받는 경로다.
  배포처럼 프론트와 백엔드 도메인이 다르면 VITE_API_BASE_URL에 백엔드 주소를 넣는다.
  주소를 다루는 곳은 여기 한 곳이다. 컴포넌트는 이 값을 알 필요가 없다.
*/
const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')

export const apiUrl = (path: string) => `${API_BASE}${path}`

const OFFLINE = API_BASE
  ? `백엔드 서버(${API_BASE})에 연결하지 못했습니다. 잠시 뒤 다시 시도해 주세요.`
  : '백엔드 서버(127.0.0.1:8000)에 연결하지 못했습니다. backend 폴더에서 uvicorn을 실행했는지 확인하세요.'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(apiUrl(path), { headers: { 'Content-Type': 'application/json' }, ...init })
  } catch {
    throw new ApiError([OFFLINE])
  }
  if (res.status === 204) return undefined as T

  const body: unknown = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail
    if (Array.isArray(detail)) throw new ApiError(detail.map(String))
    if (typeof detail === 'string') throw new ApiError([detail])
    throw new ApiError([res.status >= 500 && body === null ? OFFLINE : `요청이 실패했습니다 (HTTP ${res.status}).`])
  }
  return body as T
}

const post = <T>(path: string, data: unknown) =>
  request<T>(path, { method: 'POST', body: JSON.stringify(data) })

export const api = {
  reference: () => request<Reference>('/api/reference'),
  quote: (ticker: string) => request<Quote>(`/api/market/quote/${encodeURIComponent(ticker)}`),
  value: (req: ValuationRequest) => post<ValuationResponse>('/api/valuation/linear', req),
  positions: () => request<Position[]>('/api/positions'),
  // 체결을 쌓으면 포지션이 따라 바뀐다. 포지션을 직접 만들지 않는다.
  createTrade: (req: TradeCreate) => post<TradeResponse>('/api/trades', req),
  previewTrade: (req: TradeCreate) => post<TradePreview>('/api/trades/preview', req),
  trades: (instrumentId?: number) =>
    request<Trade[]>(`/api/trades${instrumentId ? `?instrument_id=${instrumentId}` : ''}`),
  // 청산은 반대 방향 전량 체결로 동작한다. 상태만 바꾸지 않는다.
  closePosition: (id: number) => post<TradeResponse>(`/api/positions/${id}/close`, {}),
  snapshot: (revise = false) =>
    post<SnapshotResponse>(`/api/book/snapshot${revise ? '?revise=true' : ''}`, {}),
  history: () => request<BookHistory>('/api/book/history'),
  revalue: (marks: Record<number, string>) => post<BookResponse>('/api/book/revalue', { marks }),
  bookSummary: () => request<BookSummary>('/api/book/summary'),
}

/**
 * 백엔드를 깨운다. 잠든 무료 플랜은 첫 응답까지 1분 가까이 걸릴 수 있다.
 * AbortSignal로 한 번의 시도에 상한을 둔다.
 */
export async function ping(timeoutMs = 8000): Promise<boolean> {
  const control = new AbortController()
  const timer = setTimeout(() => control.abort(), timeoutMs)
  try {
    const res = await fetch(apiUrl('/api/health'), { signal: control.signal })
    return res.ok
  } catch {
    return false
  } finally {
    clearTimeout(timer)
  }
}

export function messagesOf(err: unknown): string[] {
  if (err instanceof ApiError) return err.messages
  if (err instanceof Error) return [err.message]
  return ['알 수 없는 오류가 발생했습니다.']
}
