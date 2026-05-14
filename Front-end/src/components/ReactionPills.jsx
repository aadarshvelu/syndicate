// Floating "X reactions" overlay for parent cards (NewsCard / TweetCard).
// Layout per pill:
//
//      ┌─[2h]      ← red age badge (top-right)
//      │
//   ┌──┴──┐
//   │  𝕏  │       ← X wordmark in handle-colored circle, wobbles 4s loop
//   └─────┘
//     @gdb        ← handle text (bottom, 10px)
//
// Multiple pills sit in a horizontal row anchored bottom-right of the card.
// First 3 visible; 4+ collapse to a `+N` pill that opens the carousel anyway.
//
// Tap → calls onPillClick(reaction, index). Today that opens the reaction's
// X.com URL in a new tab; Phase 3c will route through a carousel modal.

// X-brand black for the pills. Subtle two-stop gradient gives a satin look
// against light backgrounds without losing the "this is from X" recognition.
const PILL_BG = 'linear-gradient(140deg, #0F0F12 0%, #1C1C1F 60%, #0A0A0C 100%)'

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

const XIcon = ({ size = 18 }) => (
  <svg viewBox="0 0 24 24" width={size} height={size} fill="#fff" aria-hidden>
    <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/>
  </svg>
)

const wobbleKeyframes = `
@keyframes pill-wobble-a {
  0%, 100% { transform: rotate(0) scale(1); }
  18% { transform: rotate(-5deg) scale(1.06); }
  42% { transform: rotate(5deg)  scale(1.08); }
  68% { transform: rotate(-3deg) scale(1.04); }
}
@keyframes pill-pop-in {
  from { transform: translateY(8px) scale(0.6); opacity: 0; }
  to   { transform: translateY(0)   scale(1);   opacity: 1; }
}
`

function Pill({ reaction, index, onClick }) {
  const rm = reaction.raw_meta || {}
  const handle = rm.author_handle || `@${reaction.source || '?'}`
  const age    = relativeTime(reaction.date)

  return (
    <div
      style={{
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', gap: 4,
        animation: `pill-pop-in 0.28s ease-out ${index * 0.07}s both`,
      }}
    >
      <button
        data-action="reaction-pill"
        type="button"
        onClick={(e) => { e.stopPropagation(); onClick?.(reaction, index) }}
        style={{
          position: 'relative',
          width: 46, height: 46, padding: 0,
          borderRadius: '50%',
          background: PILL_BG,
          border: '2px solid #fff',
          boxShadow: '0 4px 12px rgba(0,0,0,0.28), 0 0 0 1px rgba(0,0,0,0.06)',
          cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          animation: `pill-wobble-a 3.6s ease-in-out ${index * 0.45}s infinite`,
          transformOrigin: 'center',
        }}
      >
        <XIcon size={22} />
        {age && (
          <span style={{
            position: 'absolute', top: -7, right: -8,
            padding: '2px 6px', minWidth: 18,
            background: '#FF3B30',
            color: '#fff',
            fontSize: 10, fontWeight: 700, lineHeight: 1,
            borderRadius: 9,
            border: '1.5px solid #fff',
            boxShadow: '0 1px 3px rgba(0,0,0,0.18)',
            whiteSpace: 'nowrap',
          }}>{age}</span>
        )}
      </button>
      <span style={{
        fontSize: 10, fontWeight: 600,
        color: '#1C1C1E',
        background: 'rgba(255,255,255,0.94)',
        padding: '2px 7px', borderRadius: 9,
        maxWidth: 72,
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        boxShadow: '0 1px 3px rgba(0,0,0,0.10)',
      }}>{handle}</span>
    </div>
  )
}

export default function ReactionPillStack({ reactions, onPillClick }) {
  if (!reactions?.length) return null

  const visible  = reactions.slice(0, 3)
  const overflow = reactions.length - 3

  return (
    <>
      <style>{wobbleKeyframes}</style>
      <div style={{
        position: 'absolute',
        bottom: 90, left: 12,
        zIndex: 30,
        display: 'flex', flexDirection: 'row', alignItems: 'flex-end',
        gap: 8,
        pointerEvents: 'auto',
      }}>
        {visible.map((r, i) => (
          <Pill key={r.id} reaction={r} index={i} onClick={onPillClick} />
        ))}
        {overflow > 0 && (
          <button
            data-action="reaction-pill"
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              onPillClick?.(reactions[3], 3)
            }}
            style={{
              width: 46, height: 46, padding: 0,
              borderRadius: '50%',
              background: PILL_BG,
              border: '2px solid #fff',
              boxShadow: '0 4px 12px rgba(0,0,0,0.28), 0 0 0 1px rgba(0,0,0,0.06)',
              color: '#fff',
              fontSize: 14, fontWeight: 800, letterSpacing: '-0.5px',
              cursor: 'pointer',
              alignSelf: 'flex-start',     // align with the avatar row, not handle row
              animation: `pill-pop-in 0.28s ease-out ${visible.length * 0.07}s both`,
            }}
          >+{overflow}</button>
        )}
      </div>
    </>
  )
}
