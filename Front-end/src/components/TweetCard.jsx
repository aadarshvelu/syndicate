import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import ReactionPillStack from './ReactionPills'

const SWIPE_DIST = 45
const SWIPE_UP   = 50
const AXIS_LOCK  = 8
const ADVANCE_MS = 15_000
const SHOW_MORE_THRESHOLD = 380   // chars beyond which we offer Show more

const STACK = [
  { scale: 1,     sty: 0,  opacity: 1    },
  { scale: 0.956, sty: 14, opacity: 0.72 },
  { scale: 0.914, sty: 26, opacity: 0.46 },
]

// ── Visual helpers ──────────────────────────────────────────────────────────

// X / Twitter wordmark (the new shape)
const XLogo = ({ size = 14, color = '#1C1C1E' }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill={color} aria-hidden>
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
  </svg>
)

// Deterministic avatar gradients, indexed by handle hash
const AVATAR_GRADIENTS = [
  ['#FA2D48', '#E11D48'], // red
  ['#3B82F6', '#1D4ED8'], // blue
  ['#8B5CF6', '#6D28D9'], // violet
  ['#0EA5E9', '#0369A1'], // sky
  ['#22C55E', '#15803D'], // green
  ['#F97316', '#C2410C'], // orange
  ['#EC4899', '#BE185D'], // pink
  ['#A855F7', '#7E22CE'], // purple
]

function hashStr(s) {
  let h = 0
  for (let i = 0; i < (s || '').length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

function avatarGradient(handle) {
  return AVATAR_GRADIENTS[hashStr(handle) % AVATAR_GRADIENTS.length]
}

function avatarInitial(handle, fallback) {
  if (handle && handle.length > 1) return handle[1].toUpperCase()    // skip '@'
  if (fallback) return fallback[0].toUpperCase()
  return '𝕏'
}

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

function isVideoThumb(url) {
  return typeof url === 'string' && (url.includes('amplify_video_thumb') || url.includes('video_thumb'))
}

// Backend emits quote-tweets as: "<main text>\n\n@handle wrote:\n> <quoted>"
// Detect that structure so we can render the quoted block as an inline X-embed-style blockquote.
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

// ── Component ───────────────────────────────────────────────────────────────

export default function TweetCard({
  card,
  cardIndex,
  isTop,
  stackOffset,
  onNext,
  onExpand,
  isExpanded,
  onLike,
  reactions = [],
  onReactionClick,
  // Set true to skip the auto-advance progress bar entirely (used when the
  // card is rendered in a sheet/modal where there's no "next card" to
  // advance to — the bar would just sit there paused looking like a stray
  // red line at the top).
  hideProgress = false,
  // Set true to skip the top-right heart button. Useful in read-only sheet
  // contexts where double-tap-to-like wouldn't persist (no onLike handler),
  // so the heart UI is misleading.
  hideLike = false,
}) {
  const [tx,        setTx]        = useState(0)
  const [ty,        setTy]        = useState(0)
  const [flying,    setFlying]    = useState(false)
  const [dragging,  setDragging]  = useState(false)
  const [animKey,   setAnimKey]   = useState(0)
  const [isLiked,   setIsLiked]   = useState(false)
  const [heartKey,  setHeartKey]  = useState(0)
  const [showHeart, setShowHeart] = useState(false)
  const [expanded,  setExpanded]  = useState(false)   // long-content Show more

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
      setFlying(false); setDragging(false)
      setTx(0); setTy(0)
      setAnimKey(k => k + 1)
      setExpanded(false)
    }, 0)
    return () => clearTimeout(t)
  }, [isTop, card.id])

  const playState = isTop && !flying && !isExpanded && !dragging ? 'running' : 'paused'

  // ── Pointer handlers (identical contract to NewsCard) ─────────────────────

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

    if (!d.axis) {
      if (Math.sqrt(dx * dx + dy * dy) < AXIS_LOCK) return
      d.axis = Math.abs(dx) > Math.abs(dy) ? 'x' : 'y'
    }

    d.lastX = e.clientX
    d.lastY = e.clientY
    d.lastT = Date.now()

    if (d.axis === 'x') setTx(dx)
    else                setTy(dy < 0 ? dy * 0.55 : dy * 0.12)
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

    // Tap handling on TweetCard:
    //   - double-tap → like (kept)
    //   - single-tap → no-op (we don't open FullArticleSheet for tweets because
    //     X.com blocks iframe embedding, so the in-app reader would be blank)
    const holdMs = Date.now() - (d.downAt ?? Date.now())
    if (dist < 10 && holdMs < 250) {
      setTx(0); setTy(0)
      const now = Date.now()
      if (now - lastTapRef.current < 300) {
        lastTapRef.current = 0
        triggerLike()
      } else {
        lastTapRef.current = now
      }
      return
    }

    // Swipe-up on TweetCard: also a no-op (would otherwise open the blank sheet).
    if (axis === 'y') {
      setTy(0)
      return
    }

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

  // ── Derived ────────────────────────────────────────────────────────────────

  const st         = STACK[Math.min(stackOffset, 2)]
  const rotate     = isTop ? (tx / 280) * 7 : 0
  const opacity    = isTop ? (tx < 0 ? Math.max(0, 1 + tx / 320) : 1) : st.opacity

  const cssTransition = flying
    ? 'transform 0.26s cubic-bezier(0.4,0,1,1), opacity 0.22s ease'
    : dragging
    ? 'none'
    : 'transform 0.44s cubic-bezier(0.175,0.885,0.32,1.275)'

  const cssTransform = isTop
    ? `translateX(${tx}px) translateY(${ty}px) rotate(${rotate}deg)`
    : `scale(${st.scale}) translateY(${st.sty}px)`

  // ── Content shaping ────────────────────────────────────────────────────────

  const rm            = card.raw_meta || {}
  const isRepost      = !!rm.is_repost
  const repostedBy    = rm.reposted_by || ''
  const authorHandle  = rm.author_handle || (card.source ? `@${card.source}` : '@?')
  const authorName    = card.author || card.source || authorHandle
  const dateStr       = relativeTime(card.date)
  const threadCount   = rm.merged_tweet_count || 1
  const hasMedia      = !!card.image_url
  const isVideo       = isVideoThumb(card.image_url)

  // Scoop = tweet predates a matched news cluster. Linker captured the link
  // via parent_cluster_id with relation='standalone'.
  const isScoop = card.relation === 'standalone' && !!card.parent_cluster_id

  const { main, quoted, quotedAuthor } = useMemo(() => splitQuote(card.content || ''), [card.content])
  const isLong      = main.length > SHOW_MORE_THRESHOLD
  const showMoreBtn = isLong && !expanded

  // Advance time scales with reading effort: 2x for long content (so even
  // without expanding the user has time to scan), and another 2x when they
  // actually expand. So short=15s, long-collapsed=30s, long-expanded=60s.
  const advanceMs = ADVANCE_MS * (isLong ? 2 : 1) * (expanded ? 2 : 1)

  const [gradA, gradB] = avatarGradient(authorHandle)
  const initial = avatarInitial(authorHandle, authorName)

  // Adaptive font: shorter tweets get a slightly larger size for readability.
  // Always sans-serif (matches the modal's PostView).
  let bodyFont, bodyLine
  if (main.length < 100)      { bodyFont = 19; bodyLine = 1.45 }
  else if (main.length < 240) { bodyFont = 17; bodyLine = 1.5 }
  else                        { bodyFont = 16; bodyLine = 1.5 }

  // ── Render ─────────────────────────────────────────────────────────────────

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
        display: 'flex', flexDirection: 'column',
      }}
    >
      {/* Auto-advance progress bar */}
      {isTop && !hideProgress && (
        <div style={{
          position: 'absolute', top: 0, left: 0, right: 0,
          height: 3, zIndex: 40, overflow: 'hidden',
          background: 'rgba(0,0,0,0.07)',
        }}>
          <div
            key={`pb-${animKey}-${advanceMs}`}
            style={{
              height: '100%', background: '#FF3B30',
              transformOrigin: 'left',
              animation: `progress-run ${advanceMs}ms linear forwards`,
              animationPlayState: playState,
            }}
            onAnimationEnd={safeNext}
          />
        </div>
      )}

      {/* Top-right heart (like) — suppressed in sheet contexts where
          double-tap doesn't persist anywhere */}
      {!hideLike && (
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
      )}

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

      {/* Post block — vertically centered in the card with whitespace top & bottom.
          Same internal layout as the modal's PostView so reading a tweet on
          the feed and inside a reactions modal feels identical. */}
      <div style={{
        flex: 1,
        display: 'flex', flexDirection: 'column',
        // Short tweets get vertically centered (looks intentional on a
        // mostly-empty card). Once the user expands a long tweet, switch to
        // top-aligned so the body flows from the top and they can scroll
        // straight through it. The previous always-center behaviour clipped
        // both top and bottom of long expanded content.
        justifyContent: expanded ? 'flex-start' : 'center',
        padding: '36px 16px 16px',
        overflow: 'auto',
        WebkitOverflowScrolling: 'touch',
      }}>
        <div style={{
          display: 'flex', flexDirection: 'column', gap: 10,
          fontFamily: "system-ui, -apple-system, sans-serif",
          color: '#0F1419',
        }}>
          {/* Scoop banner — tweet predates news in the same cluster.
              Sits inside the centered post block so it reads as part of the tweet. */}
          {isScoop && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              fontSize: 12.5, fontWeight: 600, color: '#0F0F12',
              background: 'linear-gradient(90deg, rgba(255,59,48,0.10), rgba(255,59,48,0.04))',
              padding: '7px 10px',
              borderRadius: 10,
              border: '1px solid rgba(255,59,48,0.18)',
              marginBottom: 2,
              alignSelf: 'flex-start',
            }}>
              <span style={{
                display: 'inline-flex', alignItems: 'center', gap: 4,
                padding: '2px 6px',
                background: '#FF3B30', color: '#fff',
                fontSize: 10, fontWeight: 800, letterSpacing: '0.06em', textTransform: 'uppercase',
                borderRadius: 5,
              }}>
                <svg width="9" height="9" viewBox="0 0 24 24" fill="#fff" aria-hidden>
                  <path d="M13 2L3 14h8l-1 8 10-12h-8z"/>
                </svg>
                Scoop
              </span>
              <span style={{ color: '#536471', fontWeight: 500 }}>
                first reported by <b style={{ color: '#0F0F12' }}>{rm.author_handle || authorHandle}</b>
              </span>
            </div>
          )}

          {/* Repost banner — sits inside the post block, right above the avatar */}
          {isRepost && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 12.5, fontWeight: 500, color: '#6C6C70',
              marginBottom: 2,
            }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                <path d="M17 1l4 4-4 4M3 11V9a4 4 0 0 1 4-4h14M7 23l-4-4 4-4M21 13v2a4 4 0 0 1-4 4H3"
                  stroke="#6C6C70" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
              <span>Reposted by <span style={{ color: '#1C1C1E', fontWeight: 600 }}>{repostedBy}</span></span>
            </div>
          )}
          {/* Header — avatar + name/handle + time */}
          <div style={{
            display: 'flex', alignItems: 'flex-start', gap: 12,
          }}>
            <div style={{
              width: 44, height: 44, borderRadius: '50%',
              background: `linear-gradient(135deg, ${gradA}, ${gradB})`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', fontWeight: 700, fontSize: 18,
              flexShrink: 0,
              boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
            }}>{initial}</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 1, minWidth: 0, flex: 1 }}>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
                fontSize: 15, fontWeight: 700, color: '#0F1419', lineHeight: 1.2,
              }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {authorName}
                </span>
                <XLogo size={13} color="#1DA1F2" />
              </div>
              <div style={{
                fontSize: 13.5, color: '#536471', fontWeight: 400,
                display: 'flex', alignItems: 'center', gap: 4,
              }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {authorHandle}
                </span>
                <span aria-hidden style={{ color: '#AEAEB2' }}>·</span>
                <span>{dateStr}</span>
              </div>
            </div>
          </div>

          {/* Body */}
          {main ? (
            <div style={{
              fontSize: bodyFont, lineHeight: bodyLine,
              fontWeight: 400, color: '#0F1419',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              display: '-webkit-box',
              WebkitLineClamp: expanded ? 'unset' : 12,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}>
              {main}
            </div>
          ) : (
            <span style={{ color: '#AEAEB2', fontStyle: 'italic', fontSize: 15 }}>
              (media-only post)
            </span>
          )}

          {showMoreBtn && (
            <button
              data-action="show-more"
              type="button"
              onClick={() => setExpanded(true)}
              style={{
                marginTop: 2, padding: 0, alignSelf: 'flex-start',
                background: 'transparent', border: 'none',
                color: '#1DA1F2', fontSize: 14, fontWeight: 600,
                cursor: 'pointer', fontFamily: 'inherit',
              }}
            >Show more</button>
          )}

          {/* Quote block */}
          {quoted && (
            <div style={{
              padding: '10px 12px',
              border: '1px solid rgba(60,60,67,0.16)',
              borderRadius: 14,
              background: '#F7F9FA',
              fontSize: 14, lineHeight: 1.4,
            }}>
              {quotedAuthor && (
                <div style={{
                  fontSize: 12.5, fontWeight: 600, color: '#536471',
                  marginBottom: 4,
                }}>{quotedAuthor}</div>
              )}
              <div style={{ color: '#0F1419', whiteSpace: 'pre-wrap' }}>{quoted}</div>
            </div>
          )}

          {/* Media */}
          {hasMedia && (
            <div
              data-action="open-media"
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation()
                if (card.url) window.open(card.url, '_blank', 'noopener,noreferrer')
              }}
              style={{
                position: 'relative',
                borderRadius: 14, overflow: 'hidden',
                border: '1px solid rgba(60,60,67,0.12)',
                background: '#F2F2F7',
                cursor: 'pointer',
              }}
            >
              <img
                src={card.image_url}
                alt=""
                draggable={false}
                style={{
                  display: 'block', width: '100%', maxHeight: 280,
                  objectFit: 'cover', pointerEvents: 'none',
                }}
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
              <div style={{
                position: 'absolute', bottom: 8, right: 8,
                padding: '3px 8px',
                fontSize: 11, fontWeight: 500, color: 'rgba(255,255,255,0.95)',
                background: 'rgba(0,0,0,0.55)',
                borderRadius: 8,
                backdropFilter: 'blur(4px)',
                display: 'flex', alignItems: 'center', gap: 4,
                pointerEvents: 'none',
              }}>
                {isVideo ? 'Watch on X' : 'View on X'}
                <svg width="9" height="9" viewBox="0 0 12 12" fill="none">
                  <path d="M3 3h6v6M3 9l6-6" stroke="#fff" strokeWidth="1.5" strokeLinecap="round"/>
                </svg>
              </div>
            </div>
          )}

        </div>
      </div>

      {/* Footer — Track / Share. (No "Full story" for tweets: the post is
          already shown in full on the card; X.com blocks iframe embedding
          so an in-app reader would be blank anyway.) */}
      <div style={{
        flexShrink: 0,
        padding: '8px 16px 10px',
        display: 'flex', alignItems: 'center', gap: 2,
        borderTop: '0.5px solid rgba(60,60,67,0.08)',
      }}>
        {card.url && (
          <button
            data-action="share"
            type="button"
            onClick={() => {
              if (navigator.share) {
                navigator.share({ title: authorName + ' on X', url: card.url }).catch(() => {})
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
              padding: '3px 10px', cursor: 'pointer',
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

      {/* Drag handle */}
      <div style={{
        flexShrink: 0, display: 'flex', justifyContent: 'center',
        paddingBottom: 6,
      }}>
        <div style={{ width: 32, height: 3.5, borderRadius: 2, background: 'rgba(60,60,67,0.14)' }} />
      </div>

      {/* Floating X-reaction pills (Phase 3b). Only renders when this tweet
          has reactions in the same feed — e.g. a popular tweet that others
          reacted to (rare for tweets but symmetric with NewsCard). */}
      <ReactionPillStack reactions={reactions} onPillClick={onReactionClick} />
    </div>
  )
}
