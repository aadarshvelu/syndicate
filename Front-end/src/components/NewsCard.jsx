import { useState, useEffect, useRef, useCallback } from 'react'

const SWIPE_DIST = 45
const SWIPE_UP   = 50    // px upward to trigger expand
const AXIS_LOCK  = 8     // px before axis is decided
const ADVANCE_MS = 15_000
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

// Dense tiled doodle patterns — 5 tile designs, each 28×28 SVG unit
const DOODLE_TILES = [
  // 0 — tiny 4-point stars
  (c) => <path d="M14 6 l1.5 6 6 1.5-6 1.5-1.5 6-1.5-6-6-1.5 6-1.5z" fill="none" stroke={c} strokeWidth="1.2" strokeLinejoin="round"/>,
  // 1 — mini circles with dot
  (c) => <><circle cx="14" cy="14" r="5" fill="none" stroke={c} strokeWidth="1.1"/><circle cx="14" cy="14" r="1.4" fill={c}/></>,
  // 2 — small diamond
  (c) => <path d="M14 7 l5 7-5 7-5-7z" fill="none" stroke={c} strokeWidth="1.2"/>,
  // 3 — cross / plus
  (c) => <><path d="M14 8 l0 12" stroke={c} strokeWidth="1.4" strokeLinecap="round"/><path d="M8 14 l12 0" stroke={c} strokeWidth="1.4" strokeLinecap="round"/></>,
  // 4 — tiny leaf / teardrop
  (c) => <path d="M14 8 c6 0 8 12 0 14 c-8-2-6-14 0-14z" fill="none" stroke={c} strokeWidth="1.2"/>,
]

function NoImagePlaceholder({ card, cc, styleIdx }) {
  const bg   = noImageBg(card.category)
  const cat  = card.category || 'other'
  const tile = DOODLE_TILES[styleIdx % DOODLE_TILES.length](cc)
  const pid  = `dp-${styleIdx}-${(card.id || '').slice(-4)}`

  return (
    <div style={{
      width: '100%', height: '100%', background: bg,
      position: 'relative', overflow: 'hidden',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity: 0.22 }}>
        <defs>
          <pattern id={pid} x="0" y="0" width="28" height="28" patternUnits="userSpaceOnUse">
            {tile}
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill={`url(#${pid})`} />
      </svg>
      <span style={{
        position: 'relative', zIndex: 1,
        fontFamily: "'Bebas Neue', sans-serif",
        fontSize: 72, lineHeight: 1,
        color: cc, opacity: 0.7,
        userSelect: 'none',
      }}>
        {(CAT_LABEL(cat)[0] || '?').toUpperCase()}
      </span>
    </div>
  )
}

const STACK = [
  { scale: 1,     sty: 0,  opacity: 1    },
  { scale: 0.956, sty: 14, opacity: 0.72 },
  { scale: 0.914, sty: 26, opacity: 0.46 },
]

export default function NewsCard({ card, cardIndex, isTop, stackOffset, onNext, onExpand, isExpanded, onLike }) {
  const [tx,         setTx]         = useState(0)
  const [ty,         setTy]         = useState(0)
  const [flying,     setFlying]     = useState(false)
  const [dragging,   setDragging]   = useState(false)
  const [animKey,    setAnimKey]    = useState(0)
  const [isLiked,    setIsLiked]    = useState(false)
  const [heartKey,   setHeartKey]   = useState(0)
  const [showHeart,  setShowHeart]  = useState(false)

  const onNextRef    = useRef(onNext)
  const dismissedRef = useRef(false)
  const dragRef      = useRef(null)
  const lastTapRef   = useRef(0)
  const tapTimerRef  = useRef(null)

  useEffect(() => { onNextRef.current = onNext }, [onNext])

  const safeNext = useCallback(() => {
    if (dismissedRef.current) return
    dismissedRef.current = true
    onNextRef.current()
  }, [])

  const triggerLike = useCallback(() => {
    setIsLiked(true)
    setHeartKey(k => k + 1)
    setShowHeart(true)
    onLike?.(card)
    setTimeout(() => setShowHeart(false), 900)
  }, [card, onLike])

  useEffect(() => {
    if (!isTop) return
    dismissedRef.current = false
    dragRef.current = null
    clearTimeout(tapTimerRef.current)
    tapTimerRef.current = null
    const t = setTimeout(() => {
      setFlying(false)
      setDragging(false)
      setTx(0)
      setTy(0)
      setAnimKey(k => k + 1)
    }, 0)
    return () => clearTimeout(t)
  }, [isTop, card.id])

  const playState = isTop && !flying && !isExpanded && !dragging ? 'running' : 'paused'

  // ── Pointer handlers ──────────────────────────────────────────────────────

  const onPointerDown = (e) => {
    if (!isTop || flying || isExpanded) return
    if (e.target.closest('[data-action]')) return
    e.currentTarget.setPointerCapture(e.pointerId)
    dragRef.current = {
      x0: e.clientX, y0: e.clientY,
      lastX: e.clientX, lastY: e.clientY, lastT: Date.now(),
      downAt: Date.now(),
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

  const onPointerUp = () => {
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

    // Tap (no significant movement, no hold) — double tap = like, single tap = expand
    const holdMs = Date.now() - (d.downAt ?? Date.now())
    if (dist < 10 && holdMs < 250) {
      setTx(0)
      setTy(0)
      const now = Date.now()
      if (now - lastTapRef.current < 300) {
        clearTimeout(tapTimerRef.current)
        tapTimerRef.current = null
        lastTapRef.current = 0
        triggerLike()
      } else {
        lastTapRef.current = now
        tapTimerRef.current = setTimeout(() => {
          tapTimerRef.current = null
          if (!flying) onExpand(card)
        }, 250)
      }
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
      onContextMenu={(e) => e.preventDefault()}
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
              height: '100%', background: '#FF3B30',
              transformOrigin: 'left',
              animation: `progress-run ${ADVANCE_MS}ms linear forwards`,
              animationPlayState: playState,
            }}
            onAnimationEnd={safeNext}
          />
        </div>
      )}

      {/* Hero */}
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '38%' }}>
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
          <NoImagePlaceholder card={card} cc={cc} styleIdx={cardIndex % 5} />
        )}
      </div>

      {/* Top-right heart */}
      <div style={{
        position: 'absolute', top: 12, right: 12, zIndex: 20,
        width: 32, height: 32, borderRadius: '50%',
        background: 'rgba(0,0,0,0.32)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        backdropFilter: 'blur(6px)',
      }}>
        <svg width="16" height="16" viewBox="0 0 24 24">
          {isLiked
            ? <path fill="#FF3B30" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
            : <path fill="none" stroke="#fff" strokeWidth="2" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          }
        </svg>
      </div>

      {/* Center heart burst on double-tap */}
      {showHeart && (
        <div key={heartKey} style={{
          position: 'absolute', inset: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          zIndex: 25, pointerEvents: 'none',
        }}>
          <svg
            width="96" height="96" viewBox="0 0 24 24"
            style={{ animation: 'heart-burst 0.9s ease forwards', filter: 'drop-shadow(0 4px 16px rgba(255,59,48,0.5))' }}
          >
            <path fill="#FF3B30" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          </svg>
        </div>
      )}

      {/* Content panel */}
      <div style={{
        position: 'absolute', top: '34%', left: 0, right: 0, bottom: 0,
        background: '#FFFFFF', borderRadius: '18px 18px 0 0',
        padding: '14px 18px 16px',
        display: 'flex', flexDirection: 'column', gap: 7,
        boxShadow: '0 -1px 0 rgba(0,0,0,0.04)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', color: cc }}>
              {CAT_LABEL(card.category)}
            </span>
            <span style={{ width: 2, height: 2, borderRadius: '50%', background: '#C7C7CC', flexShrink: 0 }} />
            <span style={{ fontSize: 11, color: '#6C6C70', fontWeight: 500 }}>{card.source}</span>
          </div>
          <span style={{ fontSize: 11, color: '#AEAEB2', fontWeight: 500 }}>
            {new Date(card.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </span>
        </div>

        <h2 style={{
          margin: 0, fontSize: 36, fontWeight: 700,
          lineHeight: 1.2, letterSpacing: '0.1px', color: '#FF3B30',
          fontFamily: "'Bebas Neue', sans-serif",
          display: '-webkit-box', WebkitLineClamp: 4,
          WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}>
          {card.title}
        </h2>

        <p style={{
          margin: 0, fontSize: 18, lineHeight: 1.55, color: '#2C2C2E',
          fontFamily: "'Playfair Display', serif",
          fontStyle: 'italic',
          fontWeight: 400,
          display: '-webkit-box', WebkitLineClamp: 3,
          WebkitBoxOrient: 'vertical', overflow: 'hidden',
          borderLeft: '2.5px solid #FF3B30',
          paddingLeft: 10,
          marginTop: 12,
          letterSpacing: '.1px',
        }}>
          {card.teaser}
        </p>

        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          paddingTop: 8, borderTop: '0.5px solid rgba(60,60,67,0.1)',
          marginTop: 'auto',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: 5,
              fontSize: 15, fontWeight: 400, color: '#1C1C1E',
              background: 'transparent',
              padding: '3px 10px', letterSpacing: '-0.1px', cursor: 'pointer',
            }}>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                <path d="M5 3h14a1 1 0 0 1 1 1v17l-8-4-8 4V4a1 1 0 0 1 1-1z" stroke="#1C1C1E" strokeWidth="2" strokeLinejoin="round"/>
              </svg>
              Track
            </div>
            {card.url && (
              <button
                data-action="share"
                type="button"
                onClick={() => {
                  if (navigator.share) {
                    navigator.share({ title: card.title, url: card.url }).catch(() => {})
                  } else if (navigator.clipboard) {
                    navigator.clipboard.writeText(card.url).catch(() => {})
                  } else {
                    window.open(card.url, '_blank', 'noopener,noreferrer')
                  }
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  fontSize: 15, fontWeight: 400, color: '#1C1C1E',
                  background: 'transparent', border: 'none',
                  padding: '3px 10px', letterSpacing: '-0.1px', cursor: 'pointer',
                  fontFamily: 'inherit',
                }}
              >
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
                  <circle cx="18" cy="5" r="3" stroke="#1C1C1E" strokeWidth="2"/>
                  <circle cx="6" cy="12" r="3" stroke="#1C1C1E" strokeWidth="2"/>
                  <circle cx="18" cy="19" r="3" stroke="#1C1C1E" strokeWidth="2"/>
                  <path d="M8.59 13.51l6.83 3.98M15.41 6.51l-6.82 3.98" stroke="#1C1C1E" strokeWidth="2" strokeLinecap="round"/>
                </svg>
                Share
              </button>
            )}
          </div>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 5,
            fontSize: 13, fontWeight: 600, color: '#FF3B30',
            background: 'transparent', border: '1.5px solid #FF3B30', borderRadius: 20,
            padding: '3px 10px', letterSpacing: '-0.1px',
          }}>
            Full story
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
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
