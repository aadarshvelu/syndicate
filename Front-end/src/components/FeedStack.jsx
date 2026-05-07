import { useState, useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import NewsCard from './NewsCard'

export default function FeedStack({ items, onCardRead, onExpand, sheetCard, filterCategory, onLike }) {
  const [history, setHistory] = useState([])

  const activeItems = useMemo(() => {
    const seen = new Set(history)
    const remaining = items.filter((item) => !seen.has(item.id))
    if (!filterCategory) return remaining
    const matched = remaining.filter((i) => i.category === filterCategory)
    const rest = remaining.filter((i) => i.category !== filterCategory)
    return [...matched, ...rest]
  }, [items, history, filterCategory])

  const next = useCallback(() => {
    const current = activeItems[0]
    if (!current) return
    setHistory((h) => [...h, current.id])
    onCardRead?.(current.id)
  }, [activeItems, onCardRead])


  if (!items || items.length === 0) {
    return (
      <div style={{
        height: '100%', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center', gap: 8,
        background: '#F2F2F7',
      }}>
        <span style={{ fontSize: 36 }}>📭</span>
        <p style={{ margin: 0, fontSize: 15, color: '#6C6C70', fontWeight: 500 }}>No stories yet</p>
        <p style={{ margin: 0, fontSize: 13, color: '#AEAEB2' }}>Check back later</p>
      </div>
    )
  }

  if (activeItems.length === 0) {
    return (
      <div style={{
        height: '100%', display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        background: '#F2F2F7', padding: '0 28px',
      }}>
        <motion.div
          initial={{ scale: 0.7, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 280, damping: 22 }}
          style={{
            width: 56, height: 56, borderRadius: 28,
            background: '#FA2D48',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            marginBottom: 18,
          }}
        >
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
            <path d="M5 13l4 4L19 7" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </motion.div>

        <motion.h2
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.14 }}
          style={{
            margin: '0 0 8px', fontSize: 20, fontWeight: 700,
            color: '#000000', letterSpacing: '-0.3px', textAlign: 'center',
          }}
        >
          You're all caught up
        </motion.h2>

        <motion.p
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.24 }}
          style={{
            margin: '0 0 24px', fontSize: 14, color: '#6C6C70',
            textAlign: 'center', lineHeight: 1.5,
          }}
        >
          {items.length > 0
            ? `${items.length} ${items.length === 1 ? 'story' : 'stories'} read today`
            : 'Fresh stories coming soon'}
        </motion.p>

        {items.length > 0 && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ delay: 0.34 }}
            style={{ display: 'flex', gap: 10 }}
          >
            {[
              { label: 'Stories', value: items.length },
              { label: 'Categories', value: new Set(items.map((i) => i.category)).size },
            ].map(({ label, value }) => (
              <div key={label} style={{
                background: '#FFFFFF', borderRadius: 14,
                padding: '12px 22px', textAlign: 'center',
                boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
              }}>
                <div style={{ fontSize: 22, fontWeight: 700, color: '#FA2D48' }}>{value}</div>
                <div style={{ fontSize: 11, color: '#6C6C70', marginTop: 2 }}>{label}</div>
              </div>
            ))}
          </motion.div>
        )}
      </div>
    )
  }

  const visibleSlice = activeItems.slice(0, 3)
  const position = history.length + 1
  const isSheetOpen = sheetCard !== null

  return (
    <div style={{ position: 'relative', height: '100%', background: '#F2F2F7' }}>
      <AnimatePresence mode="wait">
        <motion.div
          key={filterCategory ?? 'all'}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          style={{ position: 'absolute', inset: 0 }}
        >
          {visibleSlice.map((card, offset) => (
            <NewsCard
              key={card.id}
              card={card}
              cardIndex={history.length + offset}
              isTop={offset === 0}
              stackOffset={offset}
              onNext={next}
              onExpand={onExpand}
              isExpanded={isSheetOpen && offset === 0}
              onLike={onLike}
            />
          ))}
        </motion.div>
      </AnimatePresence>

      <div style={{
        position: 'absolute', top: 10, right: 12, zIndex: 20,
        fontSize: 11, color: 'rgba(0,0,0,0.28)', letterSpacing: '0.02em',
        fontWeight: 500, pointerEvents: 'none',
      }}>
        {position} / {items.length}
      </div>
    </div>
  )
}
