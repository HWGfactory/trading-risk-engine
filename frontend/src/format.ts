// 표시 전용 포맷터. 계산은 모두 백엔드(Decimal)에서 끝난 값이다.
// 한국 시장 관행: 이익·상승·매수는 빨강, 손실·하락·매도는 파랑.

import type { Dec, Direction } from './types'

export type Tone = 'gain' | 'loss' | 'flat'

const MINUS = '−'          // U+2212 수학 마이너스. 하이픈이 아니다.
const EMPTY = '-'          // 값이 없을 때. 엠대시는 쓰지 않는다.
const won = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 })
const price = new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 4 })

export function tone(v: Dec | null | undefined): Tone {
  const n = Number(v ?? 0)
  if (n > 0) return 'gain'
  if (n < 0) return 'loss'
  return 'flat'
}

export function formatWon(v: Dec | null | undefined): string {
  if (v === null || v === undefined) return EMPTY
  const n = Number(v)
  return n < 0 ? `${MINUS}${won.format(-n)}` : won.format(n)
}

export function formatSignedWon(v: Dec | null | undefined): string {
  if (v === null || v === undefined) return EMPTY
  const n = Number(v)
  if (n > 0) return `+${won.format(n)}`
  return formatWon(v)
}

export function formatPrice(v: Dec | null | undefined): string {
  if (v === null || v === undefined) return EMPTY
  return price.format(Number(v))
}

export function formatRatio(v: Dec | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return EMPTY
  const pct = Number(v) * 100
  const body = Math.abs(pct).toFixed(digits)
  if (pct > 0) return `+${body}%`
  if (pct < 0) return `${MINUS}${body}%`
  return `${body}%`
}

export function formatRate(v: Dec | null | undefined): string {
  if (v === null || v === undefined) return EMPTY
  return `${Number((Number(v) * 100).toPrecision(10))}%`
}

export const directionLabel = (d: Direction) => (d === 'LONG' ? '매수' : '매도')
export const assetLabel = (a: string) => (a === 'EQUITY' ? '주식' : a === 'FUTURE' ? '선물' : a)

// 계산 근거 줄에서 금액이 아닌 비율 항목
export const RATIO_KEYS = new Set(['return_on_notional', 'return_on_margin'])

// 퍼센트 입력(예: "0.015")을 비율 문자열("0.00015")로 바꾼다.
// float 나눗셈(0.015 / 100)의 오차를 피하려고 소수점 위치만 문자열로 옮긴다.

const NUMERIC = /^\d*(\.\d*)?$/

export function isNumeric(value: string): boolean {
  const v = value.trim()
  return v !== '' && v !== '.' && NUMERIC.test(v)
}

export function shiftDecimal(value: string, places: number): string {
  const v = value.trim()
  if (!isNumeric(v)) throw new Error(`숫자가 아닙니다: ${value}`)
  const [intPart = '', fracPart = ''] = v.split('.')
  const digits = intPart + fracPart
  const point = intPart.length + places

  let out: string
  if (point <= 0) out = `0.${'0'.repeat(-point)}${digits}`
  else if (point >= digits.length) out = digits + '0'.repeat(point - digits.length)
  else out = `${digits.slice(0, point)}.${digits.slice(point)}`

  if (out.includes('.')) out = out.replace(/0+$/, '').replace(/\.$/, '')
  out = out.replace(/^0+(?=\d)/, '')
  return out === '' ? '0' : out
}

export const percentToRate = (percent: string) => shiftDecimal(percent, -2)
export const rateToPercent = (rate: string) => shiftDecimal(rate, 2)

// 마지막 평가 시각을 "4분 전" 같은 상대 표기로. 표시 전용이다.
export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '아직 평가하지 않음'
  // 백엔드는 UTC 기준 "YYYY-MM-DD HH:MM:SS" 형식으로 준다.
  const ms = Date.parse(iso.replace(' ', 'T') + (iso.endsWith('Z') ? '' : 'Z'))
  if (Number.isNaN(ms)) return iso
  const sec = Math.max(0, Math.round((now - ms) / 1000))
  if (sec < 60) return '방금 전'
  if (sec < 3600) return `${Math.floor(sec / 60)}분 전`
  if (sec < 86400) return `${Math.floor(sec / 3600)}시간 전`
  return `${Math.floor(sec / 86400)}일 전`
}

// 한도 사용률을 막대 길이(px)로. 계산이 아니라 표시 치수 변환이다.
export const usageBarWidth = (ratio: Dec, max = 72): number =>
  Math.max(2, Math.min(max, Math.round(Number(ratio) * max)))
