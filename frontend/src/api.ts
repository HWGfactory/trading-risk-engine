import type {
  BookResponse, BookSummary, Position, PositionCreate, Quote, Reference,
  ValuationRequest, ValuationResponse,
} from './types'

export class ApiError extends Error {
  readonly messages: string[]

  constructor(messages: string[]) {
    super(messages.join('\n'))
    this.messages = messages
  }
}

const OFFLINE = '백엔드 서버(127.0.0.1:8000)에 연결하지 못했습니다. backend 폴더에서 uvicorn을 실행했는지 확인하세요.'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
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
  createPosition: (req: PositionCreate) => post<Position>('/api/positions', req),
  closePosition: (id: number) => request<void>(`/api/positions/${id}/close`, { method: 'POST' }),
  revalue: (marks: Record<number, string>) => post<BookResponse>('/api/book/revalue', { marks }),
  bookSummary: () => request<BookSummary>('/api/book/summary'),
}

export function messagesOf(err: unknown): string[] {
  if (err instanceof ApiError) return err.messages
  if (err instanceof Error) return [err.message]
  return ['알 수 없는 오류가 발생했습니다.']
}
