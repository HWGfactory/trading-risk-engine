import { useMemo, useState } from 'react'
import type { TraceInput, TraceStep } from './types'

/**
 * 근거 추적.
 *
 * 근거 줄에 포커스하면 그 줄이 쓴 입력 칸들이 강조되고,
 * 입력 칸에 포커스하면 그 값의 영향을 받는 근거 줄들이 강조된다.
 *
 * 의존 관계는 백엔드 TraceStep.inputs에서만 온다. 프론트는 추측하지 않는다.
 */
export type TraceFocus =
  | { kind: 'step'; key: string }
  | { kind: 'input'; name: TraceInput }
  | null

export function useTrace(steps: TraceStep[] | undefined) {
  const [focus, setFocus] = useState<TraceFocus>(null)

  return useMemo(() => {
    const trace = steps ?? []
    let inputs: ReadonlySet<TraceInput> = new Set()
    let keys: ReadonlySet<string> = new Set()

    if (focus?.kind === 'step') {
      const step = trace.find((s) => s.key === focus.key)
      inputs = new Set(step?.inputs ?? [])
      keys = new Set(step ? [step.key] : [])
    } else if (focus?.kind === 'input') {
      inputs = new Set([focus.name])
      keys = new Set(trace.filter((s) => s.inputs.includes(focus.name)).map((s) => s.key))
    }

    return {
      active: focus !== null,
      isInputTraced: (name: TraceInput) => inputs.has(name),
      isStepTraced: (key: string) => keys.has(key),
      focusStep: (key: string) => setFocus({ kind: 'step', key }),
      focusInput: (name: TraceInput) => setFocus({ kind: 'input', name }),
      clear: () => setFocus(null),
    }
  }, [focus, steps])
}

export type TraceApi = ReturnType<typeof useTrace>

/** 강조 중이 아닐 때는 아무 클래스도 붙이지 않는다. */
export const tracedClass = (on: boolean) => (on ? ' is-traced' : '')
