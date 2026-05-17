/**
 * TweetSheet — bottom-sheet wrapper that renders a single TweetCard for the
 * "tap a tweet in the Read tab" flow.
 *
 * Why a separate sheet (not FullArticleSheet):
 *   - FullArticleSheet renders newspaper-style: bold headline, "Read full
 *     article" CTA, iframe of source URL. None of that fits tweets — tweets
 *     ARE the full content, and X.com blocks iframe embedding so the reader
 *     would be blank anyway.
 *
 * Why reuse TweetCard verbatim:
 *   - Same visual identity across feed and Read tab. A tweet read from the
 *     Read list looks identical to how it appeared in the original feed.
 *
 * What's disabled in this context:
 *   - Auto-advance — there's no "next tweet" to advance to. Passing
 *     isExpanded=true to TweetCard pauses the progress bar (TweetCard's own
 *     playState gates on !isExpanded).
 *   - Swipe-to-dismiss-card — we hijack onNext so any horizontal swipe
 *     closes the sheet instead.
 *   - onLike — Read tab doesn't track likes from this view. The visual
 *     heart still bursts on double-tap (TweetCard handles that locally) but
 *     no persistence callback fires.
 */

import { motion, useDragControls } from 'framer-motion'
import TweetCard from './TweetCard'

// Mirror ReadStack's category palette so the sheet header chip matches the
// rest of the app. Tweets that the summarizer didn't classify fall back to
// a neutral "TWITTER" label.
const CAT_LABEL = (c) => (c || 'twitter').replace(/_/g, ' ')
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
const catColor = (c) => CAT_COLORS[c] || '#1DA1F2'   // twitter-blue fallback

export default function TweetSheet({ card, onClose }) {
  const dragControls = useDragControls()
  const cc = catColor(card.category)

  return (
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
        background: '#FFFFFF',
        borderRadius: 20,
        display: 'flex', flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      {/* Top chrome: drag handle (for swipe-down dismiss) + close button.
          Mirrors FullArticleSheet's pattern so the two sheets feel like
          siblings. The drag handle is the only interactive zone that
          forwards pointer events to the framer drag controls — the
          TweetCard below has its own pointer logic and can't be allowed
          to swallow drags meant for the sheet. */}
      <div
        onPointerDown={(e) => dragControls.start(e)}
        style={{ flexShrink: 0, touchAction: 'none', cursor: 'grab' }}
      >
        <div style={{
          display: 'flex', justifyContent: 'center',
          paddingTop: 10, paddingBottom: 2,
        }}>
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

          {/* Category chip — mirrors FullArticleSheet's top-right label so
              both modals feel like siblings. Falls back to "TWITTER" in
              twitter-blue when the tweet wasn't classified. */}
          <span style={{
            fontSize: 11, fontWeight: 700, letterSpacing: '0.09em',
            textTransform: 'uppercase', color: cc,
          }}>
            {CAT_LABEL(card.category)}
          </span>
        </div>
      </div>

      {/* TweetCard host. TweetCard uses position:absolute relative to its
          nearest positioned ancestor, so we wrap it in a relatively-
          positioned flex:1 container that gives it bounds to fill. */}
      <div style={{ position: 'relative', flex: 1, overflow: 'hidden' }}>
        <TweetCard
          card={card}
          cardIndex={0}
          isTop={true}
          stackOffset={0}
          isExpanded={true}     /* pauses progress bar + suppresses pointer */
          hideProgress={true}   /* don't render the red bar at all */
          hideLike={true}       /* no top-right heart in sheet view */
          onNext={onClose}      /* any swipe-dismiss = close the sheet */
          reactions={[]}
        />
      </div>
    </motion.div>
  )
}
