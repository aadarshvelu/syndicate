import { useState, useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

// ── helpers ──────────────────────────────────────────────────────────────────

const HANDLE_GRADIENTS = [
  ['#FA2D48', '#E11D48'], ['#3B82F6', '#1D4ED8'],
  ['#8B5CF6', '#6D28D9'], ['#0EA5E9', '#0369A1'],
  ['#22C55E', '#15803D'], ['#F97316', '#C2410C'],
  ['#EC4899', '#BE185D'], ['#A855F7', '#7E22CE'],
]
function hashStr(s) {
  let h = 0
  for (let i = 0; i < (s || '').length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}
const gradient = (h) => HANDLE_GRADIENTS[hashStr(h) % HANDLE_GRADIENTS.length]

function relativeTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000))
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.floor(sec / 60)}m`
  if (sec < 86_400) return `${Math.floor(sec / 3600)}h`
  if (sec < 86_400 * 7) return `${Math.floor(sec / 86_400)}d`
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

const isVideoThumb = (url) =>
  typeof url === 'string' && (url.includes('amplify_video_thumb') || url.includes('video_thumb'))

function splitQuote(content) {
  if (!content) return { main: '', quotedAuthor: null, quoted: null }
  const m = content.match(/^([\s\S]*?)\n\n(@\S+) wrote:\n((?:> [^\n]*(?:\n|$))+)/)
  if (!m) return { main: content, quotedAuthor: null, quoted: null }
  return {
    main: m[1].trim(),
    quotedAuthor: m[2],
    quoted: m[3].replace(/^> /gm, '').trim(),
  }
}

const XLogo = ({ size = 14, color = '#1DA1F2' }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill={color} aria-hidden>
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
  </svg>
)

// ── Inline X-post-style card (used inside the modal carousel) ────────────────

function PostView({ reaction, parent }) {
  const rm = reaction.raw_meta || {}
  const isRepost     = !!rm.is_repost
  const repostedBy   = rm.reposted_by || ''
  const authorHandle = rm.author_handle || `@${reaction.source || '?'}`
  const authorName   = reaction.author || reaction.source || authorHandle
  const dateStr      = relativeTime(reaction.date)
  const hasMedia     = !!reaction.image_url
  const isVideo      = isVideoThumb(reaction.image_url)
  const { main, quoted, quotedAuthor } = splitQuote(reaction.content || '')

  const [gradA, gradB] = gradient(authorHandle)
  const initial = (authorHandle && authorHandle[1]) ? authorHandle[1].toUpperCase()
                : (authorName ? authorName[0].toUpperCase() : '𝕏')

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        background: '#fff',
        borderRadius: 18,
        boxShadow: '0 10px 40px rgba(0,0,0,0.32)',
        padding: '18px 18px 16px',
        display: 'flex', flexDirection: 'column', gap: 10,
        fontFamily: 'system-ui, -apple-system, sans-serif',
        color: '#0F1419',
        maxHeight: '78vh',
        overflowY: 'auto',
        WebkitOverflowScrolling: 'touch',
      }}
    >
      {isRepost && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontSize: 12.5, fontWeight: 500, color: '#6C6C70',
          paddingBottom: 4,
          borderBottom: '0.5px solid rgba(60,60,67,0.08)',
        }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M17 1l4 4-4 4M3 11V9a4 4 0 0 1 4-4h14M7 23l-4-4 4-4M21 13v2a4 4 0 0 1-4 4H3"
              stroke="#6C6C70" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          <span>Reposted by <b style={{ color: '#1C1C1E' }}>{repostedBy}</b></span>
        </div>
      )}

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
        <div style={{
          width: 44, height: 44, borderRadius: '50%',
          background: `linear-gradient(135deg, ${gradA}, ${gradB})`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#fff', fontWeight: 700, fontSize: 18,
          flexShrink: 0,
        }}>{initial}</div>
        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 15, fontWeight: 700, lineHeight: 1.2 }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{authorName}</span>
            <XLogo size={13} />
          </div>
          <div style={{ fontSize: 13.5, color: '#536471', display: 'flex', gap: 4 }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{authorHandle}</span>
            <span style={{ color: '#AEAEB2' }}>·</span>
            <span>{dateStr}</span>
          </div>
        </div>
      </div>

      {/* Body */}
      {main && (
        <div style={{ fontSize: 16, lineHeight: 1.45, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {main}
        </div>
      )}

      {/* Quoted block */}
      {quoted && (
        <div style={{
          padding: '10px 12px',
          border: '1px solid rgba(60,60,67,0.16)',
          borderRadius: 14,
          background: '#F7F9FA',
          fontSize: 14, lineHeight: 1.4,
        }}>
          {quotedAuthor && (
            <div style={{ fontSize: 12.5, fontWeight: 600, color: '#536471', marginBottom: 4 }}>
              {quotedAuthor}
            </div>
          )}
          <div style={{ whiteSpace: 'pre-wrap' }}>{quoted}</div>
        </div>
      )}

      {/* Media */}
      {hasMedia && (
        <div
          onClick={(e) => {
            e.stopPropagation()
            if (reaction.url) window.open(reaction.url, '_blank', 'noopener,noreferrer')
          }}
          style={{
            position: 'relative',
            borderRadius: 14, overflow: 'hidden',
            border: '1px solid rgba(60,60,67,0.12)',
            cursor: 'pointer',
          }}
        >
          <img
            src={reaction.image_url}
            alt=""
            draggable={false}
            style={{ display: 'block', width: '100%', maxHeight: 320, objectFit: 'cover' }}
            onError={(e) => { e.currentTarget.style.display = 'none' }}
          />
          {isVideo && (
            <div style={{
              position: 'absolute', inset: 0,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              pointerEvents: 'none',
            }}>
              <div style={{
                width: 56, height: 56, borderRadius: '50%',
                background: 'rgba(0,0,0,0.6)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                backdropFilter: 'blur(4px)',
              }}>
                <svg width="22" height="22" viewBox="0 0 24 24" fill="#fff">
                  <path d="M8 5v14l11-7z"/>
                </svg>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Parent link footer */}
      {parent && (
        <div style={{
          borderTop: '0.5px solid rgba(60,60,67,0.10)',
          paddingTop: 10,
          display: 'flex', flexDirection: 'column', gap: 4,
        }}>
          <div style={{ fontSize: 11, color: '#536471', fontWeight: 500, letterSpacing: '0.04em', textTransform: 'uppercase' }}>
            ↪ Reacting to
          </div>
          <a
            href={parent.url || '#'}
            target="_blank" rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            style={{
              fontSize: 14, fontWeight: 600, color: '#1C1C1E',
              textDecoration: 'none',
              display: '-webkit-box',
              WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {parent.title || parent.summary || '(parent)'}
          </a>
        </div>
      )}
    </div>
  )
}

// ── Modal with horizontal carousel ───────────────────────────────────────────

export default function ReactionsModal({ reactions, parent, startIndex = 0, onClose }) {
  const [index, setIndex] = useState(startIndex)
  const trackRef = useRef(null)
  const [width, setWidth] = useState(typeof window !== 'undefined' ? window.innerWidth : 393)

  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  if (!reactions?.length) return null
  const total = reactions.length
  const clampedIndex = Math.max(0, Math.min(index, total - 1))

  // Keyboard nav (desktop)
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
      else if (e.key === 'ArrowRight' && clampedIndex < total - 1) setIndex((i) => i + 1)
      else if (e.key === 'ArrowLeft'  && clampedIndex > 0)         setIndex((i) => i - 1)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [clampedIndex, total, onClose])

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0,
        background: 'rgba(8,10,14,0.78)',
        backdropFilter: 'blur(14px)',
        WebkitBackdropFilter: 'blur(14px)',
        zIndex: 350,
        display: 'flex', flexDirection: 'column',
      }}
    >
      {/* Header */}
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          padding: 'calc(env(safe-area-inset-top, 0px) + 12px) 18px 8px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          color: '#fff',
        }}
      >
        <button
          onClick={onClose}
          style={{
            width: 36, height: 36, borderRadius: '50%',
            background: 'rgba(255,255,255,0.14)',
            border: 'none', cursor: 'pointer',
            color: '#fff', fontSize: 20, fontWeight: 600,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            backdropFilter: 'blur(8px)',
          }}
        >✕</button>
        <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: '0.04em', color: 'rgba(255,255,255,0.92)' }}>
          {clampedIndex + 1} / {total}
        </span>
      </div>

      {/* Carousel track. NO onClick stopPropagation here — clicks on track
          padding (around the card) should fall through to the backdrop and
          close the modal. Only the inner PostView swallows clicks. */}
      <div
        ref={trackRef}
        style={{
          flex: 1, position: 'relative', overflow: 'hidden',
          display: 'flex', alignItems: 'center',
        }}
      >
        <motion.div
          drag="x"
          dragConstraints={{ left: 0, right: 0 }}
          dragElastic={0.18}
          onDragEnd={(_, info) => {
            const threshold = 50
            if (info.offset.x < -threshold && clampedIndex < total - 1) setIndex((i) => i + 1)
            else if (info.offset.x > threshold && clampedIndex > 0)     setIndex((i) => i - 1)
          }}
          animate={{ x: -clampedIndex * width }}
          transition={{ type: 'spring', stiffness: 320, damping: 32 }}
          style={{
            display: 'flex',
            width: total * width,
            height: '100%',
            cursor: 'grab',
          }}
        >
          {reactions.map((r) => (
            <div key={r.id} style={{
              width, flexShrink: 0,
              padding: '0 18px',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <div style={{ width: '100%', maxWidth: 480 }}>
                <PostView reaction={r} parent={parent} />
              </div>
            </div>
          ))}
        </motion.div>

        {/* Side arrows (desktop) */}
        {total > 1 && (
          <>
            {clampedIndex > 0 && (
              <button
                onClick={(e) => { e.stopPropagation(); setIndex((i) => Math.max(0, i - 1)) }}
                aria-label="Previous"
                style={{
                  position: 'absolute', left: 8, top: '50%', transform: 'translateY(-50%)',
                  width: 40, height: 40, borderRadius: '50%',
                  background: 'rgba(0,0,0,0.45)', border: 'none', color: '#fff',
                  fontSize: 22, fontWeight: 600, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  backdropFilter: 'blur(6px)',
                }}
              >‹</button>
            )}
            {clampedIndex < total - 1 && (
              <button
                onClick={(e) => { e.stopPropagation(); setIndex((i) => Math.min(total - 1, i + 1)) }}
                aria-label="Next"
                style={{
                  position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
                  width: 40, height: 40, borderRadius: '50%',
                  background: 'rgba(0,0,0,0.45)', border: 'none', color: '#fff',
                  fontSize: 22, fontWeight: 600, cursor: 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  backdropFilter: 'blur(6px)',
                }}
              >›</button>
            )}
          </>
        )}
      </div>

      {/* Dots */}
      {total > 1 && (
        <div
          onClick={(e) => e.stopPropagation()}
          style={{
            padding: '10px 0 calc(env(safe-area-inset-bottom, 0px) + 18px)',
            display: 'flex', justifyContent: 'center', gap: 8,
          }}
        >
          {reactions.map((_, i) => (
            <button
              key={i}
              onClick={() => setIndex(i)}
              aria-label={`Go to reaction ${i + 1}`}
              style={{
                width: i === clampedIndex ? 22 : 8, height: 8,
                padding: 0,
                borderRadius: 6,
                background: i === clampedIndex ? '#fff' : 'rgba(255,255,255,0.38)',
                border: 'none',
                cursor: 'pointer',
                transition: 'width 0.2s ease, background 0.2s ease',
              }}
            />
          ))}
        </div>
      )}
    </motion.div>
  )
}
