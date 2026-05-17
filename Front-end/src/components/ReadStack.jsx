import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import FullArticleSheet from './FullArticleSheet'
import TweetSheet from './TweetSheet'
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

// ── Twitter avatar helpers — matches TweetCard so the Read row reads as
// the same source identity (same gradient + initial for a given @handle). ──

const AVATAR_GRADIENTS = [
  ['#FA2D48', '#E11D48'], ['#3B82F6', '#1D4ED8'], ['#8B5CF6', '#6D28D9'],
  ['#0EA5E9', '#0369A1'], ['#22C55E', '#15803D'], ['#F97316', '#C2410C'],
  ['#EC4899', '#BE185D'], ['#A855F7', '#7E22CE'],
]
function hashStr(s) {
  let h = 0
  for (let i = 0; i < (s || '').length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}
const avatarGradient = (h) => AVATAR_GRADIENTS[hashStr(h) % AVATAR_GRADIENTS.length]
const avatarInitial = (h, fb) =>
  (h && h.length > 1) ? h[1].toUpperCase() : (fb ? fb[0].toUpperCase() : '𝕏')

function relativeTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000))
  if (sec < 60)         return `${sec}s`
  if (sec < 3600)       return `${Math.floor(sec / 60)}m`
  if (sec < 86_400)     return `${Math.floor(sec / 3600)}h`
  if (sec < 86_400 * 7) return `${Math.floor(sec / 86_400)}d`
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// Inline X-wordmark — same icon as TweetCard
const XLogo = ({ size = 11 }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="#1DA1F2" aria-hidden>
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
  </svg>
)

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

// Twitter row for the Read list — visually matches TweetCard's header
// (avatar + name + @handle + time) plus a 2-line tweet body preview. Same
// list density as ReadItem so the rhythm of the list isn't broken.
function ReadTweetItem({ card, index, onOpen }) {
  const rm           = card.raw_meta || {}
  const authorHandle = rm.author_handle || (card.source ? `@${card.source}` : '@?')
  const authorName   = card.author || card.source || authorHandle
  const dateStr      = relativeTime(card.date)
  const [gradA, gradB] = avatarGradient(authorHandle)
  const initial      = avatarInitial(authorHandle, authorName)

  // First few lines of the tweet body, with the quote-block delimiter
  // (backend emits "@handle wrote:\n>") trimmed off the preview.
  const preview = (card.content || '').split('\n\n@')[0].trim()

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: Math.min(index * 0.03, 0.22), type: 'spring', stiffness: 320, damping: 26 }}
      onClick={onOpen}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 12,
        background: '#FFFFFF',
        padding: '12px 14px',
        cursor: 'pointer',
        WebkitTapHighlightColor: 'transparent',
      }}
    >
      {/* Avatar — same gradient + initial pattern as TweetCard */}
      <div style={{
        width: 44, height: 44, borderRadius: '50%',
        background: `linear-gradient(135deg, ${gradA}, ${gradB})`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#fff', fontWeight: 700, fontSize: 17,
        flexShrink: 0,
        boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
      }}>{initial}</div>

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Author line: name · X icon · @handle · time */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 5,
          fontSize: 14, lineHeight: 1.2, marginBottom: 2,
          color: '#0F1419',
        }}>
          <span style={{
            fontWeight: 700,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            maxWidth: 140,
          }}>{authorName}</span>
          <XLogo size={11} />
          <span style={{
            fontWeight: 400, color: '#536471',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            minWidth: 0,
          }}>{authorHandle}</span>
          <span aria-hidden style={{ color: '#AEAEB2' }}>·</span>
          <span style={{ fontWeight: 400, color: '#536471', flexShrink: 0 }}>{dateStr}</span>
        </div>

        {/* Tweet preview body */}
        <p style={{
          margin: 0,
          fontSize: 14, fontWeight: 400, lineHeight: 1.35,
          color: '#0F1419',
          display: '-webkit-box', WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical', overflow: 'hidden',
          whiteSpace: 'pre-wrap', wordBreak: 'break-word',
        }}>
          {preview || <em style={{ color: '#AEAEB2', fontStyle: 'italic' }}>(media-only post)</em>}
        </p>
      </div>

      {/* Chevron — same as ReadItem so the column is consistent */}
      <svg width="7" height="12" viewBox="0 0 7 12" fill="none" style={{
        flexShrink: 0, opacity: 0.25, marginTop: 4,
      }}>
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
          {items.map((card, i) => {
            const isTw = card.source_channel === 'twitter'
            const Row = isTw ? ReadTweetItem : ReadItem
            // Divider sits below this row, so its left margin matches THIS
            // row's text-start position: 70px for tweet rows (44px avatar +
            // 14px padding + 12px gap), 88px for news rows (62px thumbnail +
            // 14 + 12). Using a single constant for both leaves the line
            // visibly clipping under the wider news thumbnail.
            const dividerMargin = isTw ? 70 : 88
            return (
              <div key={card.id}>
                <Row card={card} index={i} onOpen={() => setExpanded(card)} />
                {i < items.length - 1 && (
                  <div style={{
                    height: 0.5,
                    background: 'rgba(60,60,67,0.12)',
                    marginLeft: dividerMargin,
                  }} />
                )}
              </div>
            )
          })}
        </div>
      </div>
      </PullToRefresh>

      <AnimatePresence>
        {expanded && (
          expanded.source_channel === 'twitter'
            ? <TweetSheet      key={expanded.id} card={expanded} onClose={() => setExpanded(null)} />
            : <FullArticleSheet key={expanded.id} card={expanded} onClose={() => setExpanded(null)} />
        )}
      </AnimatePresence>
    </>
  )
}
