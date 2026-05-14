import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import FullArticleSheet from './FullArticleSheet'
import PullToRefresh from './PullToRefresh'

const CAT_LABEL = (c) => (c || 'news').replace(/_/g, ' ')
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

function ReadItem({ card, index, onOpen }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.03, 0.22), type: 'spring', stiffness: 320, damping: 26 }}
      onClick={onOpen}
      style={{
        display: 'flex', alignItems: 'center', gap: 12,
        background: '#FFFFFF',
        padding: '12px 14px',
        cursor: 'pointer',
        WebkitTapHighlightColor: 'transparent',
      }}
    >
      {/* Thumbnail */}
      <div style={{
        width: 62, height: 62, borderRadius: 10,
        overflow: 'hidden', flexShrink: 0,
        background: '#F2F2F7',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        {card.image_url ? (
          <img
            src={card.image_url}
            alt=""
            draggable={false}
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          <span style={{ fontSize: 22, fontWeight: 800, color: catColor(card.category), opacity: 0.35 }}>
            {(card.source || 'N')[0].toUpperCase()}
          </span>
        )}
      </div>

      {/* Text */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ marginBottom: 3 }}>
          <span style={{
            fontSize: 9.5, fontWeight: 700, letterSpacing: '0.07em',
            textTransform: 'uppercase', color: catColor(card.category),
          }}>
            {CAT_LABEL(card.category)}
          </span>
        </div>
        <p style={{
          margin: '0 0 3px',
          fontSize: 14, fontWeight: 600, lineHeight: 1.3,
          color: '#000000',
          display: '-webkit-box', WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}>
          {card.title}
        </p>
        <span style={{ fontSize: 11, color: '#AEAEB2' }}>
          {card.source} · {new Date(card.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </span>
      </div>

      {/* Chevron */}
      <svg width="7" height="12" viewBox="0 0 7 12" fill="none" style={{ flexShrink: 0, opacity: 0.25 }}>
        <path d="M1 1l5 5-5 5" stroke="#000" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    </motion.div>
  )
}

export default function ReadStack({ items, onRefresh }) {
  const [expanded, setExpanded] = useState(null)
  const scrollRef = useRef(null)

  if (!items || items.length === 0) {
    return (
      <PullToRefresh onRefresh={onRefresh} mode="static">
        <div style={{
          height: '100%', display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 8,
          background: '#F2F2F7',
        }}>
          <span style={{ fontSize: 36 }}>📂</span>
          <p style={{ margin: 0, fontSize: 15, color: '#6C6C70', fontWeight: 500 }}>Nothing read yet</p>
        </div>
      </PullToRefresh>
    )
  }

  return (
    <>
      <PullToRefresh onRefresh={onRefresh} mode="scroll" scrollRef={scrollRef}>
      <div ref={scrollRef} style={{
        height: '100%',
        overflowY: 'auto',
        background: '#F2F2F7',
        WebkitOverflowScrolling: 'touch',
      }}>
        <div style={{
          padding: '12px 16px 8px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ fontSize: 13, fontWeight: 700, color: '#000000', letterSpacing: '-0.1px' }}>
            Read
          </span>
          <span style={{ fontSize: 12, color: '#AEAEB2' }}>
            {items.length} {items.length === 1 ? 'story' : 'stories'}
          </span>
        </div>

        <div style={{
          margin: '0 16px 100px',
          background: '#FFFFFF',
          borderRadius: 12,
          overflow: 'hidden',
          boxShadow: '0 1px 4px rgba(0,0,0,0.07)',
        }}>
          {items.map((card, i) => (
            <div key={card.id}>
              <ReadItem card={card} index={i} onOpen={() => setExpanded(card)} />
              {i < items.length - 1 && (
                <div style={{ height: 0.5, background: 'rgba(60,60,67,0.12)', marginLeft: 88 }} />
              )}
            </div>
          ))}
        </div>
      </div>
      </PullToRefresh>

      <AnimatePresence>
        {expanded && <FullArticleSheet card={expanded} onClose={() => setExpanded(null)} />}
      </AnimatePresence>
    </>
  )
}
