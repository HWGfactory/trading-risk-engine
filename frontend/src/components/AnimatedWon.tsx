import { animate, useMotionValue, useReducedMotion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { formatSignedWon, formatWon } from '../format'
import type { Dec } from '../types'

interface Props {
  value: Dec | null | undefined
  signed?: boolean
}

/**
 * 값이 바뀌었다는 것을 알리는 전환.
 *
 * 중요: 전환 중간값은 표시용 근사치다. 전환이 끝나면 백엔드가 준 문자열을
 * 그대로 렌더링한다. 프론트에서 금액을 계산하지 않는다.
 * 매 프레임 setState 하지 않도록 motion value를 쓴다.
 */
export default function AnimatedWon({ value, signed = true }: Props) {
  const reduce = useReducedMotion()
  const fmt = signed ? formatSignedWon : formatWon
  const target = value === null || value === undefined ? null : Number(value)

  const mv = useMotionValue(target ?? 0)
  const node = useRef<HTMLSpanElement>(null)
  // 전환이 끝났는지. 끝난 뒤에는 백엔드 문자열을 그대로 보여준다.
  const [settled, setSettled] = useState(true)

  useEffect(() => {
    if (target === null) return
    if (reduce || mv.get() === target) {
      mv.set(target)
      setSettled(true)
      return
    }
    setSettled(false)
    const controls = animate(mv, target, {
      duration: 0.32,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (v) => {
        if (node.current) node.current.textContent = fmt(String(Math.round(v)))
      },
      onComplete: () => setSettled(true),
    })
    return () => controls.stop()
  }, [target, reduce, mv, fmt])

  // settled일 때는 백엔드 문자열 그대로. 전환 중에만 ref로 중간값을 쓴다.
  return <span ref={node}>{settled ? fmt(value) : undefined}</span>
}
