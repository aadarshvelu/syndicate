import { useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence, useDragControls } from 'framer-motion'

const CAT_LABEL = (c) => (c || '').replace(/_/g, ' ')
const CAT_COLORS = {
  ai_research: '#3B82F6',
  ai_products: '#8B5CF6',
  tech_news:   '#0EA5E9',
  economics:   '#22C55E',
  policy:      '#F97316',
  startup:     '#FA2D48',
  world_news:  '#64748B',
  other:       '#78716C',
}
const catColor = (c) => CAT_COLORS[c] || '#FA2D48'


function Skeleton() {
  const pulse = {
    animate: { opacity: [0.4, 0.9, 0.4] },
    transition: { duration: 1.6, repeat: Infinity, ease: 'easeInOut' },
  }
  const bar = (w, h = 14, mb = 10, delay = 0) => (
    <motion.div {...pulse} transition={{ ...pulse.transition, delay }} style={{
      width: w, height: h, borderRadius: 7,
      background: '#E5E5EA', marginBottom: mb, flexShrink: 0,
    }} />
  )
  return (
    <div style={{ padding: '24px 18px', flex: 1, overflow: 'hidden' }}>
      {/* hero image placeholder */}
      <motion.div {...pulse} style={{ width: '100%', height: 180, borderRadius: 12, background: '#E5E5EA', marginBottom: 20 }} />

      {/* source · date */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
        {bar('30%', 10, 0, 0.05)}
        {bar('22%', 10, 0, 0.08)}
      </div>

      {/* title */}
      {bar('95%', 26, 6, 0.1)}
      {bar('80%', 26, 20, 0.13)}

      {/* teaser block */}
      <div style={{ borderLeft: '2.5px solid #FF3B30', paddingLeft: 12, marginBottom: 22 }}>
        {bar('100%', 14, 7, 0.16)}
        {bar('96%',  14, 7, 0.18)}
        {bar('70%',  14, 0, 0.20)}
      </div>

      {/* divider */}
      <div style={{ height: 0.5, background: '#E5E5EA', marginBottom: 18 }} />

      {/* body paragraphs */}
      {bar('100%', 13, 7, 0.22)}
      {bar('100%', 13, 7, 0.24)}
      {bar('92%',  13, 7, 0.26)}
      {bar('100%', 13, 7, 0.28)}
      {bar('85%',  13, 18, 0.30)}

      {bar('100%', 13, 7, 0.32)}
      {bar('96%',  13, 7, 0.34)}
      {bar('100%', 13, 7, 0.36)}
      {bar('60%',  13, 0, 0.38)}
    </div>
  )
}

function FullScreenReader({ url, onClose }) {
  const [loaded, setLoaded] = useState(false)

  return createPortal(
    <AnimatePresence>
      <motion.div
        key="fullscreen"
        initial={{ y: '100%' }}
        animate={{ y: 0 }}
        exit={{ y: '100%' }}
        transition={{ type: 'spring', stiffness: 300, damping: 32, mass: 1 }}
        style={{
          position: 'fixed', inset: 0, zIndex: 1000,
          background: '#fff', display: 'flex', flexDirection: 'column',
        }}
      >
        {/* Top progress bar */}
        {!loaded && (
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, zIndex: 10, overflow: 'hidden' }}>
            <motion.div
              animate={{ x: ['-100%', '100%'] }}
              transition={{ duration: 1.2, repeat: Infinity, ease: 'easeInOut' }}
              style={{ height: '100%', width: '55%', background: 'linear-gradient(90deg, transparent, #FF3B30, transparent)', borderRadius: 2 }}
            />
          </div>
        )}

        <div style={{ flex: 1, position: 'relative' }}>
          <AnimatePresence>
            {!loaded && (
              <motion.div
                key="skeleton"
                initial={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.3 }}
                style={{ position: 'absolute', inset: 0, zIndex: 5, background: '#fff', display: 'flex', flexDirection: 'column' }}
              >
                <Skeleton />
              </motion.div>
            )}
          </AnimatePresence>

          <iframe
            src={url}
            onLoad={() => setLoaded(true)}
            style={{ width: '100%', height: 'calc(100% - 90px)', border: 'none', display: 'block' }}
            title="Full article"
            sandbox="allow-scripts allow-same-origin allow-popups allow-forms allow-top-navigation"
          />
          {/* Gradient scrim — blocks iframe events + hides white gap */}
          <div style={{
            position: 'absolute', bottom: 0, left: 0, right: 0, height: 110,
            background: 'linear-gradient(to bottom, transparent 0%, rgba(255,255,255,0.85) 55%, #ffffff 100%)',
            zIndex: 20, pointerEvents: 'all',
          }} />
        </div>
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          style={{
            position: 'absolute',
            bottom: 'calc(20px + env(safe-area-inset-bottom, 0px))',
            left: 0, right: 0,
            display: 'flex', justifyContent: 'center',
            zIndex: 30,
          }}
        >
          <button
            onClick={onClose}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: '#FF3B30',
              border: 'none', borderRadius: 30,
              padding: '14px 48px',
              color: '#fff', fontSize: 15, fontWeight: 600,
              cursor: 'pointer', letterSpacing: '-0.1px',
              boxShadow: '0 4px 20px rgba(255,59,48,0.45)',
            }}
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path d="M1.5 1.5l11 11M12.5 1.5l-11 11" stroke="#fff" strokeWidth="2" strokeLinecap="round"/>
            </svg>
            Close
          </button>
        </motion.div>
      </motion.div>
    </AnimatePresence>,
    document.body
  )
}

export default function FullArticleSheet({ card, onClose }) {
  const [showFullScreen, setShowFullScreen] = useState(false)
  const dragControls = useDragControls()
  const cc = catColor(card.category)

  return (
    <>
    <motion.div
      initial={{ y: '100%' }}
      animate={{ y: 0 }}
      exit={{ y: '100%' }}
      transition={{ type: 'spring', stiffness: 320, damping: 32, mass: 1 }}
      drag="y"
      dragControls={dragControls}
      dragListener={false}
      dragConstraints={{ top: 0 }}
      dragElastic={{ top: 0, bottom: 0.4 }}
      onDragEnd={(_, info) => {
        if (info.offset.y > 80 || info.velocity.y > 400) onClose()
      }}
      style={{
        position: 'absolute', inset: 0, zIndex: 300,
        background: '#FFFFFF', borderRadius: 20,
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Handle + nav bar */}
      <div
        onPointerDown={(e) => dragControls.start(e)}
        style={{ flexShrink: 0, touchAction: 'none', cursor: 'grab' }}
      >
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 10, paddingBottom: 2 }}>
          <div style={{ width: 36, height: 4, borderRadius: 2, background: 'rgba(60,60,67,0.18)' }} />
        </div>

        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '8px 16px 10px',
        }}>
          <button
            onPointerDown={(e) => e.stopPropagation()}
            onClick={onClose}
            style={{
              background: '#F2F2F7', border: 'none', cursor: 'pointer',
              width: 32, height: 32, borderRadius: 16,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
              <path d="M1.5 1.5l10 10M11.5 1.5l-10 10" stroke="#000" strokeWidth="1.8" strokeLinecap="round"/>
            </svg>
          </button>

          <span style={{
            fontSize: 11, fontWeight: 700, letterSpacing: '0.09em',
            textTransform: 'uppercase', color: cc,
          }}>
            {CAT_LABEL(card.category)}
          </span>

          <button
            onPointerDown={(e) => e.stopPropagation()}
            onClick={() => card.url && window.open(card.url, '_blank', 'noopener,noreferrer')}
            style={{
              background: '#F2F2F7', border: 'none', cursor: 'pointer',
              width: 32, height: 32, borderRadius: 16,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
              <path d="M5 1.5H2a1 1 0 0 0-1 1v8.5a1 1 0 0 0 1 1h8.5a1 1 0 0 0 1-1V8M7.5 1.5H12m0 0v4.5m0-4.5L5.5 8" stroke="#000" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden' }}>

        {/* Hero image */}
        {card.image_url && (
          <div style={{ height: 220, overflow: 'hidden', position: 'relative' }}>
            <img
              src={card.image_url} alt=""
              style={{ width: '100%', height: '100%', objectFit: 'cover' }}
            />
            <div style={{
              position: 'absolute', inset: 0,
              background: 'linear-gradient(to bottom, transparent 50%, rgba(0,0,0,0.45) 100%)',
            }} />
          </div>
        )}

        <div style={{ padding: '20px 18px 48px' }}>

          {/* Source + date */}
          <p style={{
            margin: '0 0 12px', fontSize: 11, color: '#AEAEB2', fontWeight: 500,
            letterSpacing: '0.04em', textTransform: 'uppercase',
          }}>
            {card.source} · {new Date(card.date).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
          </p>

          {/* Title */}
          <h1 style={{
            margin: '0 0 16px',
            fontFamily: "'Bebas Neue', sans-serif",
            fontSize: 32, fontWeight: 700,
            lineHeight: 1, letterSpacing: '.1px',
            color: '#FF3B30',
          }}>
            {card.title}
          </h1>

          {/* Teaser */}
          {card.teaser && (
            <p style={{
              margin: '0 0 20px', fontSize: 17, lineHeight: 1.65,
              fontFamily: "'Playfair Display', serif",
              fontStyle: 'italic', fontWeight: 400,
              color: '#1C1C1E',
              borderLeft: '2.5px solid #FF3B30', paddingLeft: 13,
            }}>
              {card.teaser}
            </p>
          )}

          <div style={{ height: 0.5, background: 'rgba(60,60,67,0.12)', margin: '0 0 20px' }} />

          {/* Summary body */}
          <p style={{
            margin: '0 0 28px', fontSize: 15, lineHeight: 1.8,
            color: '#1C1C1E', fontWeight: 400,
          }}>
            {card.summary}
          </p>

          {/* Read full article button */}
          <button
            onClick={() => setShowFullScreen(true)}
            style={{
              width: '100%', padding: '14px 0',
              background: '#FF3B30', color: '#FFFFFF',
              border: 'none', borderRadius: 14,
              fontSize: 15, fontWeight: 600,
              cursor: 'pointer', letterSpacing: '-0.1px',
              marginBottom: 16,
            }}
          >
            Read full article
          </button>
        </div>
      </div>
    </motion.div>

    {showFullScreen && (
      <FullScreenReader url={card.url} onClose={() => setShowFullScreen(false)} />
    )}
    </>
  )
}
