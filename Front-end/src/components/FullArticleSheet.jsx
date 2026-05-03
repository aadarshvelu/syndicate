import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

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

function InlineReader({ url }) {
  const [state, setState] = useState('loading')

  const handleLoad = (e) => {
    try {
      const loc = e.target.contentWindow?.location?.href
      setState(loc && loc !== 'about:blank' ? 'loaded' : 'blocked')
    } catch {
      setState('loaded')
    }
  }
  const handleError = () => setState('blocked')

  return (
    <div style={{ borderRadius: 12, overflow: 'hidden', background: '#F2F2F7' }}>
      {state === 'loading' && (
        <div style={{
          height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
        }}>
          <motion.div
            animate={{ rotate: 360 }}
            transition={{ duration: 0.85, repeat: Infinity, ease: 'linear' }}
            style={{
              width: 20, height: 20, borderRadius: '50%',
              border: '2.5px solid rgba(0,0,0,0.08)',
              borderTopColor: '#FA2D48',
            }}
          />
          <span style={{ fontSize: 12, color: '#6C6C70' }}>Loading article…</span>
        </div>
      )}
      {state === 'blocked' && (
        <div style={{ padding: '24px 16px', textAlign: 'center' }}>
          <p style={{ margin: '0 0 8px', fontSize: 13, color: '#6C6C70' }}>
            This site doesn't allow inline embedding.
          </p>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontSize: 13, fontWeight: 600, color: '#FA2D48', textDecoration: 'none' }}
          >
            Open in browser →
          </a>
        </div>
      )}
      <iframe
        key={url}
        src={url}
        onLoad={handleLoad}
        onError={handleError}
        sandbox="allow-scripts allow-same-origin allow-popups allow-forms allow-top-navigation"
        style={{
          width: '100%', height: 540, border: 'none',
          display: state === 'blocked' ? 'none' : 'block',
          opacity: state === 'loaded' ? 1 : 0,
          transition: 'opacity 0.3s ease',
        }}
        title="Article"
      />
    </div>
  )
}

export default function FullArticleSheet({ card, onClose }) {
  const [showInline, setShowInline] = useState(false)
  const cc = catColor(card.category)

  return (
    <motion.div
      initial={{ y: '100%' }}
      animate={{ y: 0 }}
      exit={{ y: '100%' }}
      transition={{ type: 'spring', stiffness: 320, damping: 32, mass: 1 }}
      style={{
        position: 'absolute', inset: 0, zIndex: 100,
        background: '#FFFFFF', overflowY: 'auto', overflowX: 'hidden',
        borderRadius: 20,
      }}
    >
      {/* Handle */}
      <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 10 }}>
        <div style={{ width: 36, height: 4, borderRadius: 2, background: 'rgba(60,60,67,0.18)' }} />
      </div>

      {/* Nav */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 16px 0',
      }}>
        <button
          onClick={onClose}
          style={{
            background: '#F2F2F7', border: 'none', cursor: 'pointer',
            width: 30, height: 30, borderRadius: 15,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
            <path d="M1.5 1.5l10 10M11.5 1.5l-10 10" stroke="#000" strokeWidth="1.8" strokeLinecap="round"/>
          </svg>
        </button>

        <span style={{
          fontSize: 10.5, fontWeight: 700, letterSpacing: '0.07em',
          textTransform: 'uppercase', color: cc,
        }}>
          {CAT_LABEL(card.category)}
        </span>

        <button
          onClick={() => card.url && window.open(card.url, '_blank', 'noopener,noreferrer')}
          style={{
            background: '#F2F2F7', border: 'none', cursor: 'pointer',
            width: 30, height: 30, borderRadius: 15,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
            <path d="M5 1.5H2a1 1 0 0 0-1 1v8.5a1 1 0 0 0 1 1h8.5a1 1 0 0 0 1-1V8M7.5 1.5H12m0 0v4.5m0-4.5L5.5 8" stroke="#000" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      </div>

      {/* Hero */}
      {card.image_url && (
        <div style={{ height: 210, overflow: 'hidden', marginTop: 14 }}>
          <img
            src={card.image_url}
            alt=""
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        </div>
      )}

      {/* Content */}
      <div style={{ padding: '20px 18px 48px' }}>
        <p style={{ margin: '0 0 10px', fontSize: 12, color: '#AEAEB2', fontWeight: 500 }}>
          {card.source} · {new Date(card.date).toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })}
        </p>

        <h1 style={{
          margin: '0 0 14px', fontSize: 22, fontWeight: 800,
          lineHeight: 1.22, letterSpacing: '-0.4px', color: '#000000',
        }}>
          {card.title}
        </h1>

        {card.teaser && (
          <p style={{
            margin: '0 0 16px', fontSize: 15, lineHeight: 1.6,
            color: '#1C1C1E', fontWeight: 400,
            borderLeft: `3px solid ${cc}`,
            paddingLeft: 13,
          }}>
            {card.teaser}
          </p>
        )}

        <div style={{ height: 0.5, background: 'rgba(60,60,67,0.12)', margin: '0 0 16px' }} />

        <p style={{ margin: '0 0 24px', fontSize: 15, lineHeight: 1.75, color: '#1C1C1E' }}>
          {card.summary}
        </p>

        <button
          onClick={() => setShowInline((v) => !v)}
          style={{
            width: '100%', padding: '12px 0',
            background: showInline ? '#F2F2F7' : '#000000',
            color: showInline ? '#000000' : '#FFFFFF',
            border: 'none', borderRadius: 12,
            fontSize: 14, fontWeight: 600,
            cursor: 'pointer', letterSpacing: '-0.1px',
            marginBottom: 16,
          }}
        >
          {showInline ? 'Hide article' : 'Read full article'}
        </button>

        <AnimatePresence>
          {showInline && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 280, damping: 28 }}
              style={{ overflow: 'hidden' }}
            >
              <InlineReader url={card.url} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  )
}
