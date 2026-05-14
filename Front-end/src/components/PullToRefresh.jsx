import { useState, useRef, useCallback } from 'react'
import { motion } from 'framer-motion'

/**
 * iOS-style pull-to-refresh wrapper.
 *
 * Modes:
 *  - mode="scroll"  (default): assumes children render a scrollable container.
 *    The wrapper listens on touch events and only engages when the scroll
 *    container is at top (scrollTop === 0).
 *  - mode="static": children have no internal scroll (card stack, empty
 *    state). Engages from any downward drag inside the wrapper. Bails if
 *    the drag turns horizontal, so it never steals card swipes.
 *
 * onRefresh: async () => void. Spinner stays up until the promise resolves.
 */
const THRESHOLD     = 70   // px the user has to pull before release fires refresh
const MAX_PULL      = 110  // visual cap so the indicator doesn't run away
const RESISTANCE    = 2.2  // higher = "stiffer" rubber-band feel
const H_BAIL_RATIO  = 1.4  // |dx| > |dy| * this => treat as a horizontal gesture, abort

export default function PullToRefresh({
  onRefresh,
  mode = 'scroll',
  scrollRef = null,
  children,
}) {
  const [pull,       setPull]       = useState(0)
  const [refreshing, setRefreshing] = useState(false)

  const start  = useRef(null)    // { x, y } | null
  const active = useRef(false)   // are we currently claiming this gesture?

  const atScrollTop = useCallback(() => {
    if (mode !== 'scroll') return true
    const el = scrollRef?.current
    if (!el) return true
    return el.scrollTop <= 0
  }, [mode, scrollRef])

  const onPointerDown = (e) => {
    if (refreshing) return
    if (!atScrollTop()) return
    start.current = { x: e.clientX, y: e.clientY }
    active.current = false
    setPull(0)
  }

  const onPointerMove = (e) => {
    if (!start.current || refreshing) return
    const dy = e.clientY - start.current.y
    const dx = e.clientX - start.current.x

    // Bail if the gesture clearly wants to be horizontal (card swipe).
    if (Math.abs(dx) > Math.abs(dy) * H_BAIL_RATIO) {
      start.current = null
      active.current = false
      setPull(0)
      return
    }

    if (dy <= 0) {
      // Upward — not our gesture.
      if (active.current) {
        active.current = false
        setPull(0)
      }
      return
    }

    // Engage once the user has moved at least a few px downward.
    if (dy > 6) active.current = true
    if (!active.current) return

    const eased = Math.min(MAX_PULL, dy / RESISTANCE)
    setPull(eased)
  }

  const onPointerUp = async () => {
    if (!start.current) return
    const shouldRefresh = active.current && pull >= THRESHOLD * 0.6
    start.current = null
    active.current = false

    if (!shouldRefresh) {
      setPull(0)
      return
    }

    setRefreshing(true)
    setPull(THRESHOLD)
    try {
      await onRefresh?.()
    } finally {
      setRefreshing(false)
      setPull(0)
    }
  }

  // Visual: spinner sits in the pulled-down space above the children.
  const indicatorOpacity = Math.min(1, pull / 50)
  const spinnerRotation  = pull * 4   // degrees, advances with pull distance
  const ready            = pull >= THRESHOLD * 0.85 || refreshing

  return (
    <div
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      style={{ position: 'relative', height: '100%', touchAction: mode === 'scroll' ? 'pan-y' : 'auto' }}
    >
      {/* Indicator strip (overlays top edge, doesn't shift layout). */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0,
        height: pull,
        display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
        paddingBottom: 6,
        pointerEvents: 'none',
        zIndex: 5,
        opacity: indicatorOpacity,
        transition: refreshing ? 'none' : 'opacity 0.15s ease-out',
      }}>
        <motion.div
          animate={refreshing
            ? { rotate: 360 }
            : { rotate: spinnerRotation }
          }
          transition={refreshing
            ? { repeat: Infinity, duration: 0.8, ease: 'linear' }
            : { duration: 0 }
          }
          style={{
            width: 22, height: 22,
            border: '2.5px solid rgba(0,0,0,0.18)',
            borderTopColor: ready ? '#FA2D48' : 'rgba(0,0,0,0.45)',
            borderRadius: '50%',
          }}
        />
      </div>

      {/* Children — translated down by the pull distance. */}
      <motion.div
        animate={{ y: pull }}
        transition={refreshing
          ? { type: 'spring', stiffness: 320, damping: 30 }
          : { duration: 0 }
        }
        style={{ height: '100%' }}
      >
        {children}
      </motion.div>
    </div>
  )
}
