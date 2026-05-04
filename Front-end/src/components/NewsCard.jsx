import { useState, useEffect, useRef } from 'react'
import { motion, useMotionValue, useTransform, animate } from 'framer-motion'
import { useDrag } from '@use-gesture/react'

const SWIPE_DIST = 55
const SWIPE_VEL  = 0.35
const ADVANCE_MS = 30_000
const KB_NAMES   = ['kb-1', 'kb-2', 'kb-3']

const CAT_LABEL = (c) => (c || 'news').replace(/_/g, ' ')
const CAT_COLORS = {
  ai_research: '#3B82F6', ai_products: '#8B5CF6',
  tech_news:   '#0EA5E9', economics:   '#22C55E',
  policy:      '#F97316', startup:     '#FA2D48',
  world_news:  '#64748B', other:       '#78716C',
}
const catColor  = (c) => CAT_COLORS[c] || '#FA2D48'
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
  { scale: 1,     y: 0,  opacity: 1    },
  { scale: 0.956, y: 14, opacity: 0.72 },
  { scale: 0.914, y: 26, opacity: 0.46 },
]

export default function NewsCard({ card, cardIndex, isTop, stackOffset, onNext, onPrev, onExpand, isExpanded }) {
  const x      = useMotionValue(0)
  const y      = useMotionValue(0)
  const rotate = useTransform(x, [-260, 260], [-7, 7])
  const fade   = useTransform(x, [-300, -60, 0, 60, 300], [0, 1, 1, 1, 0.6])

  const [flying,    setFlying]    = useState(false)
  const [animKey,   setAnimKey]   = useState(0)
  const [playState, setPlayState] = useState('running')
  const dismissed = useRef(false)

  const kb = KB_NAMES[cardIndex % 3]
  const st = STACK[Math.min(stackOffset, 2)]
  const cc = catColor(card.category)

  useEffect(() => {
    if (!isTop) return
    dismissed.current = false
    setFlying(false)
    setAnimKey((k) => k + 1)
    setPlayState('running')
    x.set(0)
    y.set(0)
  }, [isTop, card.id, x, y])

  useEffect(() => {
    if (!isTop) return
    setPlayState(flying || isExpanded ? 'paused' : 'running')
  }, [flying, isExpanded, isTop])

  const safeNext = () => {
    if (dismissed.current) return
    dismissed.current = true
    onNext()
  }

  // Drag bound only to hero area — content panel stays fully tappable
  const bind = useDrag(
    ({ movement: [mx, my], velocity: [vx, vy], last }) => {
      if (!last) {
        x.set(Math.min(mx, 28))
        y.set(my < 0 ? my * 0.5 : my * 0.18)
        return
      }

      const swipedLeft  = mx < -SWIPE_DIST || vx < -SWIPE_VEL
      const swipedRight = mx >  SWIPE_DIST || vx >  SWIPE_VEL
      const swipeUp     = (my < -30 || vy < -SWIPE_VEL) && Math.abs(my) > Math.abs(mx) * 0.8

      if (swipedLeft) {
        setFlying(true)
        animate(x, -600, { duration: 0.22, ease: [0.32, 0, 0.67, 0] }).then(safeNext)
      } else if (swipedRight) {
        onPrev()
        animate(x, 0, { type: 'spring', stiffness: 400, damping: 30 })
        animate(y, 0, { type: 'spring', stiffness: 400, damping: 30 })
      } else if (swipeUp) {
        onExpand(card)
        animate(x, 0, { type: 'spring', stiffness: 380, damping: 30 })
        animate(y, 0, { type: 'spring', stiffness: 380, damping: 30 })
      } else {
        animate(x, 0, { type: 'spring', stiffness: 380, damping: 30 })
        animate(y, 0, { type: 'spring', stiffness: 380, damping: 30 })
      }
    },
    {
      from: () => [x.get(), y.get()],
      filterTaps: true,
      enabled: isTop && !flying && !isExpanded,
    }
  )

  return (
    <motion.div
      style={{
        x, y, rotate,
        opacity:    isTop ? fade : st.opacity,
        scale:      st.scale,
        translateY: st.y,
        zIndex:     10 - stackOffset,
        position:   'absolute',
        top: 0, left: 0, right: 0, bottom: 0,
        borderRadius: '0 0 20px 20px',
        overflow: 'hidden',
        background: '#FFFFFF',
        pointerEvents: isTop ? 'auto' : 'none',
        userSelect: 'none',
        boxShadow: '0 2px 20px rgba(0,0,0,0.10), 0 1px 4px rgba(0,0,0,0.06)',
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

      {/* Hero — drag zone (swipe left/right/up) */}
      <div
        {...bind()}
        style={{
          position: 'absolute', top: 0, left: 0, right: 0, height: '54%',
          touchAction: 'none',
          cursor: isTop ? 'grab' : 'default',
        }}
      >
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

      {/* Content panel — tap anywhere to expand */}
      <div
        onClick={() => { if (isTop && !flying) onExpand(card) }}
        style={{
          position: 'absolute', top: '48%', left: 0, right: 0, bottom: 0,
          background: '#FFFFFF', borderRadius: '18px 18px 0 0',
          padding: '14px 18px 16px',
          display: 'flex', flexDirection: 'column', gap: 7,
          boxShadow: '0 -1px 0 rgba(0,0,0,0.04)',
          cursor: isTop ? 'pointer' : 'default',
        }}
      >
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
    </motion.div>
  )
}
