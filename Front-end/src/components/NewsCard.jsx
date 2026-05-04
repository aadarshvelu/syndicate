import { useState, useEffect, useRef, useCallback } from 'react'

const SWIPE_DIST = 45
const SWIPE_UP   = 50    // px upward to trigger expand
const AXIS_LOCK  = 8     // px before axis is decided
const ADVANCE_MS = 30_000
const KB_NAMES   = ['kb-1', 'kb-2', 'kb-3']

const CAT_LABEL = (c) => (c || 'news').replace(/_/g, ' ')
const CAT_COLORS = {
  ai_research: '#3B82F6', ai_products: '#8B5CF6',
  tech_news:   '#0EA5E9', economics:   '#22C55E',
  policy:      '#F97316', startup:     '#FA2D48',
  world_news:  '#64748B', other:       '#78716C',
}
const catColor = (c) => CAT_COLORS[c] || '#FA2D48'
const NO_IMAGE_BG = {
  ai_research: 'linear-gradient(160deg,#DBEAFE,#EFF6FF)',
  ai_products: 'linear-gradient(160deg,#EDE9FE,#F5F3FF)',
  tech_news:   'linear-gradient(160deg,#E0F2FE,#F0F9FF)',
  economics:   'linear-gradient(160deg,#DCFCE7,#F0FDF4)',
  policy:      'linear-gradient(160deg,#FFEDD5,#FFF7ED)',
  startup:     'linear-gradient(160deg,#FFE4E6,#FFF1F2)',
  world_news:  'linear-gradient(160deg,#F1F5F9,#F8FAFC)',
  other:       'linear-gradient(160deg,#F5F5F4,#FAFAF9)',
}
const noImageBg = (c) => NO_IMAGE_BG[c] || NO_IMAGE_BG.other

const STACK = [
  { scale: 1,     sty: 0,  opacity: 1    },
  { scale: 0.956, sty: 14, opacity: 0.72 },
  { scale: 0.914, sty: 26, opacity: 0.46 },
]

export default function NewsCard({ card, cardIndex, isTop, stackOffset, onNext, onExpand, isExpanded }) {
  const [tx,       setTx]       = useState(0)
  const [ty,       setTy]       = useState(0)
  const [flying,   setFlying]   = useState(false)
  const [dragging, setDragging] = useState(false)
  const [animKey,  setAnimKey]  = useState(0)
  const [playState, setPlayState] = useState('running')

  const onNextRef    = useRef(onNext)
  const dismissedRef = useRef(false)
  // { x0, y0, lastX, lastY, lastT, axis: null|'x'|'y' }
  const dragRef      = useRef(null)

  useEffect(() => { onNextRef.current = onNext }, [onNext])

  const safeNext = useCallback(() => {
    if (dismissedRef.current) return
    dismissedRef.current = true
    onNextRef.current()
  }, [])

  useEffect(() => {
    if (!isTop) return
    dismissedRef.current = false
    dragRef.current = null
    setFlying(false)
    setDragging(false)
    setTx(0)
    setTy(0)
    setAnimKey(k => k + 1)
    setPlayState('running')
  }, [isTop, card.id])

  useEffect(() => {
    if (!isTop) return
    setPlayState(flying || isExpanded ? 'paused' : 'running')
  }, [flying, isExpanded, isTop])

  // ── Pointer handlers ──────────────────────────────────────────────────────

  const onPointerDown = (e) => {
    if (!isTop || flying || isExpanded) return
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = {
      x0: e.clientX, y0: e.clientY,
      lastX: e.clientX, lastY: e.clientY, lastT: Date.now(),
      axis: null,
    }
    setDragging(true)
  }

  const onPointerMove = (e) => {
    const d = dragRef.current
    if (!d) return

    const dx = e.clientX - d.x0
    const dy = e.clientY - d.y0

    // Lock axis once movement exceeds threshold
    if (!d.axis) {
      if (Math.sqrt(dx * dx + dy * dy) < AXIS_LOCK) return
      d.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y'
    }

    d.lastX = e.clientX
    d.lastY = e.clientY
    d.lastT = Date.now()

    if (d.axis === 'x') {
      setTx(dx)
    } else {
      // Only upward movement; resist downward with damping
      setTy(dy < 0 ? dy * 0.55 : dy * 0.12)
    }
  }

  const onPointerUp = (e) => {
    const d = dragRef.current
    if (!d) return

    const axis  = d.axis
    const dx    = d.lastX - d.x0
    const dy    = d.lastY - d.y0
    const dt    = Math.max(1, Date.now() - d.lastT)
    const vx    = dx / dt
    const vy    = dy / dt
    const dist  = Math.sqrt(dx * dx + dy * dy)
    dragRef.current = null
    setDragging(false)

    // Tap (no significant movement) → open article
    if (dist < 10) {
      setTx(0)
      setTy(0)
      if (!flying) onExpand(card)
      return
    }

    if (axis === 'y') {
      const swipedUp = dy < -SWIPE_UP || vy < -0.35
      setTy(0)
      if (swipedUp) onExpand(card)
      return
    }

    // Horizontal
    const swipedLeft  = dx < -SWIPE_DIST || vx < -0.3
    const swipedRight = dx >  SWIPE_DIST || vx >  0.3

    if (swipedLeft || swipedRight) {
      const target = swipedLeft ? -720 : 720
      setFlying(true)
      requestAnimationFrame(() => requestAnimationFrame(() => setTx(target)))
    } else {
      setTx(0)
    }
  }

  // ── Derived style values ──────────────────────────────────────────────────

  const st      = STACK[Math.min(stackOffset, 2)]
  const cc      = catColor(card.category)
  const kb      = KB_NAMES[cardIndex % 3]
  const rotate  = isTop ? (tx / 280) * 7 : 0
  const opacity = isTop ? (tx < 0 ? Math.max(0, 1 + tx / 320) : 1) : st.opacity

  const cssTransition = flying
    ? 'transform 0.26s cubic-bezier(0.4,0,1,1), opacity 0.22s ease'
    : dragging
    ? 'none'
    : 'transform 0.44s cubic-bezier(0.175,0.885,0.32,1.275)'

  const cssTransform = isTop
    ? `translateX(${tx}px) translateY(${ty}px) rotate(${rotate}deg)`
    : `scale(${st.scale}) translateY(${st.sty}px)`

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onTransitionEnd={() => { if (flying) safeNext() }}
      style={{
        transform:  cssTransform,
        opacity,
        transition: cssTransition,
        zIndex:     10 - stackOffset,
        position:   'absolute',
        top: 0, left: 0, right: 0, bottom: 0,
        borderRadius: '0 0 20px 20px',
        overflow:   'hidden',
        background: '#FFFFFF',
        pointerEvents: isTop ? 'auto' : 'none',
        touchAction: 'none',
        userSelect: 'none',
        cursor: isTop ? (dragging ? 'grabbing' : 'grab') : 'default',
        boxShadow:  '0 2px 20px rgba(0,0,0,0.10), 0 1px 4px rgba(0,0,0,0.06)',
        willChange: 'transform',
      }}
    >
      {/* Progress bar */}
      {isTop && (
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0,
          height: 3, zIndex: 40, overflow: 'hidden',
          background: 'rgba(0,0,0,0.07)',
        }}>
          <div
            key={`pb-${animKey}`}
            style={{
              height: '100%', background: '#FA2D48',
              transformOrigin: 'left',
              animation: `progress-run ${ADVANCE_MS}ms linear forwards`,
              animationPlayState: playState,
            }}
            onAnimationEnd={safeNext}
          />
        </div>
      )}

      {/* Hero */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '54%' }}>
        {card.image_url ? (
          <img
            key={`img-${card.id}`}
            src={card.image_url}
            alt=""
            draggable={false}
            style={{
              width: '100%', height: '100%',
              objectFit: 'cover', objectPosition: 'center',
              willChange: 'transform',
              animation: `${kb} ${ADVANCE_MS}ms ease-in-out forwards`,
              animationPlayState: playState,
            }}
          />
        ) : (
          <div style={{
            width: '100%', height: '100%',
            background: noImageBg(card.category),
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <span style={{ fontSize: 72, fontWeight: 900, opacity: 0.12, color: cc, letterSpacing: '-0.05em' }}>
              {(card.source || 'N')[0].toUpperCase()}
            </span>
          </div>
        )}
      </div>

      {/* Content panel */}
      <div style={{
        position: 'absolute', top: '48%', left: 0, right: 0, bottom: 0,
        background: '#FFFFFF', borderRadius: '18px 18px 0 0',
        padding: '14px 18px 16px',
        display: 'flex', flexDirection: 'column', gap: 7,
        boxShadow: '0 -1px 0 rgba(0,0,0,0.04)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', color: cc }}>
            {CAT_LABEL(card.category)}
          </span>
          <span style={{ width: 2, height: 2, borderRadius: '50%', background: '#C7C7CC', flexShrink: 0 }} />
          <span style={{ fontSize: 11, color: '#6C6C70', fontWeight: 500 }}>{card.source}</span>
        </div>

        <h2 style={{
          margin: 0, fontSize: 18, fontWeight: 700,
          lineHeight: 1.25, letterSpacing: '-0.25px', color: '#000000',
          display: '-webkit-box', WebkitLineClamp: 3,
          WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}>
          {card.title}
        </h2>

        <p style={{
          margin: 0, fontSize: 13, lineHeight: 1.5, color: '#6C6C70',
          display: '-webkit-box', WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical', overflow: 'hidden', flex: 1,
        }}>
          {card.teaser}
        </p>

        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          paddingTop: 8, borderTop: '0.5px solid rgba(60,60,67,0.1)',
        }}>
          <span style={{ fontSize: 11, color: '#AEAEB2' }}>
            {new Date(card.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </span>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 5,
            fontSize: 12, fontWeight: 600, color: '#FFFFFF',
            background: '#000000', borderRadius: 20,
            padding: '5px 14px', letterSpacing: '-0.1px',
          }}>
            Full story
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
              <path d="M6 9V3M3 6l3-3 3 3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <div style={{ width: 32, height: 3.5, borderRadius: 2, background: 'rgba(60,60,67,0.14)' }} />
        </div>
      </div>
    </div>
  )
}
