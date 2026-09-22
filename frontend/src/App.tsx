import { useEffect, useState } from 'react'
import { api, messagesOf } from './api'
import BookView from './components/BookView'
import DealTicket from './components/DealTicket'
import ValuationStatement from './components/ValuationStatement'
import type { PositionCreate, Reference, ValuationRequest, ValuationResponse } from './types'

type Tab = 'valuation' | 'book'

export default function App() {
  const [tab, setTab] = useState<Tab>('valuation')
  const [reference, setReference] = useState<Reference | null>(null)
  const [bootError, setBootError] = useState<string[]>([])
  const [result, setResult] = useState<ValuationResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const [bookKey, setBookKey] = useState(0)

  useEffect(() => {
    api.reference().then(setReference).catch((err) => setBootError(messagesOf(err)))
  }, [])

  async function evaluate(req: ValuationRequest) {
    setBusy(true)
    setErrors([])
    setNotice(null)
    try {
      setResult(await api.value(req))
    } catch (err) {
      setErrors(messagesOf(err))
    } finally {
      setBusy(false)
    }
  }

  async function addToBook(req: PositionCreate) {
    setBusy(true)
    setErrors([])
    setNotice(null)
    try {
      const p = await api.createPosition(req)
      setNotice(`${p.name ?? p.symbol} 포지션을 북에 추가했습니다. 북 현황에서 재평가하세요.`)
      setBookKey((k) => k + 1)
    } catch (err) {
      setErrors(messagesOf(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app">
      <header className="masthead">
        <div className="brand">
          <h1>PI 데스크 포지션 평가</h1>
          <p>자기매매 포지션의 시가평가·손익·한도를 근거와 함께 계산합니다</p>
        </div>
        <nav className="tabs" aria-label="화면">
          <button type="button" aria-current={tab === 'valuation' ? 'page' : undefined}
            onClick={() => setTab('valuation')}>포지션 평가</button>
          <button type="button" aria-current={tab === 'book' ? 'page' : undefined}
            onClick={() => setTab('book')}>북 현황</button>
        </nav>
      </header>

      <main>
        {bootError.length > 0 && (
          <ul className="alerts" role="alert">{bootError.map((m) => <li key={m}>{m}</li>)}</ul>
        )}

        {tab === 'valuation' && reference && (
          <div className="desk">
            <div>
              <DealTicket reference={reference} busy={busy} onEvaluate={evaluate} onAddToBook={addToBook} />
              {errors.length > 0 && (
                <ul className="alerts" role="alert">{errors.map((m) => <li key={m}>{m}</li>)}</ul>
              )}
              {notice && <p className="notice" role="status">{notice}</p>}
            </div>
            <ValuationStatement result={result} />
          </div>
        )}

        {tab === 'book' && <BookView refreshKey={bookKey} />}
      </main>
    </div>
  )
}
