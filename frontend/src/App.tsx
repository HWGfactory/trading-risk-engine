import { WarningCircleIcon } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { api, messagesOf } from './api'
import BookView from './components/BookView'
import DealTicket from './components/DealTicket'
import Home from './components/Home'
import Nav from './components/Nav'
import ValuationStatement from './components/ValuationStatement'
import { useRoute } from './router'
import { useTheme } from './theme'
import { useTrace } from './trace'
import PositionDetail from './components/PositionDetail'
import type { Position, Reference, TradeCreate, ValuationRequest, ValuationResponse } from './types'

const REPO = 'https://github.com/HWGfactory/trading-risk-engine'

export default function App() {
  const [route, go] = useRoute()
  const { choice, resolved, setChoice } = useTheme()

  return (
    <div className="shell">
      <Nav route={route} onNavigate={go} themeChoice={choice} resolved={resolved}
        onToggleTheme={setChoice} />

      <main>
        {route === 'home' && <Home onNavigate={go} />}
        {route === 'valuation' && <ValuationPage />}
        {route === 'book' && <BookPage onGoToValuation={() => go('valuation')} />}
      </main>

      <footer className="wrap foot">
        <a href={`${REPO}#readme`} target="_blank" rel="noreferrer">저장소</a>
        <a href={`${REPO}/blob/main/METHODOLOGY.md`} target="_blank" rel="noreferrer">
          계산 방법론
        </a>
      </footer>
    </div>
  )
}

function ValuationPage() {
  const [reference, setReference] = useState<Reference | null>(null)
  const [bootError, setBootError] = useState<string[]>([])
  const [result, setResult] = useState<ValuationResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [added, setAdded] = useState<string | null>(null)

  const trace = useTrace(result?.valuation.trace)

  useEffect(() => {
    api.reference().then(setReference).catch((err) => setBootError(messagesOf(err)))
  }, [])

  async function evaluate(req: ValuationRequest, live: boolean) {
    // 자동 평가는 버튼을 "평가 중"으로 바꾸지 않는다. 입력 중에 깜빡이면 방해가 된다.
    if (!live) setBusy(true)
    setErrors([])
    try {
      setResult(await api.value(req))
    } catch (err) {
      if (!live) setErrors(messagesOf(err))
    } finally {
      if (!live) setBusy(false)
    }
  }

  async function bookTrade(req: TradeCreate) {
    setBusy(true)
    setErrors([])
    setAdded(null)
    try {
      const r = await api.createTrade(req)
      // 체결 결과 문구는 백엔드가 만든다. 부분 청산인지 방향 전환인지 엔진이 안다.
      setAdded(`${r.position.name ?? r.position.symbol} ${r.message}`)
    } catch (err) {
      setErrors(messagesOf(err))
    } finally {
      setBusy(false)
    }
  }

  if (bootError.length > 0) {
    return (
      <div className="wrap page">
        <ul className="alerts">
          {bootError.map((m) => (
            <li className="alert" key={m} role="alert">
              <WarningCircleIcon size={15} weight="fill" aria-hidden />
              <span>{m}</span>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  if (!reference) {
    return (
      <div className="wrap page">
        <div className="desk">
          <div className="panel ticket"><span className="skeleton" style={{ height: 320 }} /></div>
          <div className="panel statement"><span className="skeleton" style={{ height: 320 }} /></div>
        </div>
      </div>
    )
  }

  return (
    <div className="wrap page">
      <h1 className="page-title">포지션 평가</h1>
      <div className="desk">
        <div>
          <DealTicket reference={reference} busy={busy} trace={trace} addedName={added}
            onEvaluate={evaluate} onBookTrade={bookTrade} />
          {errors.length > 0 && (
            <ul className="alerts">
              {errors.map((m) => (
                <li className="alert" key={m} role="alert">
                  <WarningCircleIcon size={15} weight="fill" aria-hidden />
                  <span>{m}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <ValuationStatement result={result} trace={trace} busy={busy} />
      </div>
    </div>
  )
}

function BookPage({ onGoToValuation }: { onGoToValuation: () => void }) {
  const [detail, setDetail] = useState<Position | null>(null)
  return (
    <div className="wrap page">
      <h1 className="page-title">{detail ? '종목 상세' : '북 현황'}</h1>
      {detail
        ? <PositionDetail position={detail} onBack={() => setDetail(null)} />
        : <BookView refreshKey={0} onGoToValuation={onGoToValuation} onOpenDetail={setDetail} />}
    </div>
  )
}
