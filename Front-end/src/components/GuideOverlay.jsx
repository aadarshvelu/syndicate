/**
 * GuideOverlay — first-launch tour shown once per device.
 *
 * Visibility logic:
 *   localStorage.isGuideShown !== 'true'  → show
 *   user taps "Got it"                    → set 'true', dismiss forever
 *
 * Visual theme matches LoadingScreen: dark gradient background, red accent,
 * Geist headline font. Four gesture tiles in a 2x2 grid; each tile has a
 * tiny looping animation that demonstrates the gesture. No paragraphs of
 * text — just the visual + a 1–2 word caption per tile.
 */

import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const STORAGE_KEY = 'isGuideShown'

export function shouldShowGuide() {
  if (typeof window === 'undefined') return false
  try {
    return localStorage.getItem(STORAGE_KEY) !== 'true'
  } catch {
    return false
  }
}

// ── Gesture animation primitives ─────────────────────────────────────────────
//
// All four tiles share the same mini-phone frame so the cheat sheet reads
// as one visual language. Inside each frame, a small "card" rectangle
// runs the gesture-specific animation in a tight infinite loop.

const PHONE_W = 84
const PHONE_H = 120
const CARD_INSET = 8   // padding between phone wall and card

// Reusable phone outline. children is rendered inside the inner padding.
function PhoneFrame({ children }) {
  return (
    <div style={{
      width: PHONE_W, height: PHONE_H,
      borderRadius: 8,
      border: '1.5px solid rgba(255,255,255,0.25)',
      position: 'relative',
      overflow: 'hidden',
      background: 'rgba(0,0,0,0.18)',
    }}>
      {children}
    </div>
  )
}

// The card stub that lives inside the phone frame. Soft white surface so
// it reads as a card on the dark background. animate/transition control
// the per-tile gesture loop.
function PhoneCard({ animate, transition, style }) {
  return (
    <motion.div
      animate={animate}
      transition={transition}
      style={{
        position: 'absolute',
        top: CARD_INSET, left: CARD_INSET, right: CARD_INSET, bottom: CARD_INSET,
        borderRadius: 4,
        background: 'rgba(255,255,255,0.85)',
        boxShadow: '0 1px 3px rgba(0,0,0,0.25)',
        ...style,
      }}
    />
  )
}

// Tile 1: Swipe to advance — top card swipes BOTH ways across the loop:
// first off to the left (with a slight tilt), invisibly snaps back, then
// off to the right (tilted the other way). Both directions advance to the
// next card in the real app, so the gesture indicator shows both.
function SwipeAdvance() {
  return (
    <PhoneFrame>
      {/* Card underneath — the "next-up" card. Stays put. */}
      <PhoneCard style={{ background: 'rgba(255,255,255,0.55)' }} />
      {/* Top card — animates: center → off-left + tilt → invisible reset
          → off-right + tilt → invisible reset → back to center. Opacity
          masks the snap-back so the user only sees the two swipe legs. */}
      <PhoneCard
        animate={{
          x:       [0,  -PHONE_W * 1.1, 0, PHONE_W * 1.1, 0],
          opacity: [1,  0,              0, 0,              1],
          rotate:  [0,  -10,            0, 10,             0],
        }}
        transition={{
          duration: 3.6,
          repeat: Infinity,
          times: [0, 0.22, 0.5, 0.72, 1],
          ease: 'easeInOut',
        }}
      />
    </PhoneFrame>
  )
}

// Tile 2: Auto-advance timer — card sits still, a bright red bar at the
// TOP depletes from full → empty, shrinking right→left. Matches the real
// `@keyframes progress-run` in index.css (scaleX 1 → 0, transformOrigin
// left), so the guide demonstrates exactly the behavior users will see on
// a live card. The bar is taller (5px) and glow-shadowed so it reads as
// the highlight, not just a card edge.
function AutoTimer() {
  return (
    <PhoneFrame>
      <PhoneCard style={{ background: 'rgba(255,255,255,0.55)' }} />
      {/* Highlight: red bar at the very top of the frame */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0,
        height: 5,
        background: 'rgba(255,255,255,0.10)',
        zIndex: 2,
      }}>
        <motion.div
          animate={{ scaleX: [1, 0] }}
          transition={{ duration: 2.4, repeat: Infinity, ease: 'linear' }}
          style={{
            height: '100%', width: '100%',
            background: '#FA2D48',
            transformOrigin: 'left',
            boxShadow: '0 0 8px rgba(250,45,72,0.7)',
          }}
        />
      </div>
    </PhoneFrame>
  )
}

// Tile 3: Swipe up for full read — a sheet card rises up from the bottom
// edge of the phone, covers most of the screen, then resets. The base
// card behind stays put so users see what's being covered.
function SwipeUpRead() {
  return (
    <PhoneFrame>
      <PhoneCard style={{ background: 'rgba(255,255,255,0.55)' }} />
      {/* Rising sheet */}
      <motion.div
        animate={{ y: [PHONE_H, 12, 12, PHONE_H] }}
        transition={{ duration: 2.4, repeat: Infinity, times: [0, 0.3, 0.75, 1], ease: 'easeInOut' }}
        style={{
          position: 'absolute',
          left: CARD_INSET, right: CARD_INSET,
          top: 0, bottom: 0,
          borderRadius: 6,
          background: '#FFFFFF',
          boxShadow: '0 -3px 10px rgba(0,0,0,0.35)',
        }}
      />
    </PhoneFrame>
  )
}

// Tile 4: Read tab — phone outline with a tab-bar row, right tab pulses
// red to indicate the History/Read tab destination.
function ReadTabIndicator() {
  return (
    <PhoneFrame>
      {/* Content stub fills most of the phone */}
      <div style={{
        position: 'absolute',
        top: CARD_INSET, left: CARD_INSET, right: CARD_INSET, bottom: 18,
        borderRadius: 4,
        background: 'rgba(255,255,255,0.55)',
      }} />
      {/* Tab bar at the bottom */}
      <div style={{
        position: 'absolute', bottom: 4, left: CARD_INSET, right: CARD_INSET,
        height: 10,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <div style={{ width: 14, height: 4, borderRadius: 2, background: 'rgba(255,255,255,0.25)' }} />
        <motion.div
          animate={{ opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 1.6, repeat: Infinity, ease: 'easeInOut' }}
          style={{ width: 14, height: 4, borderRadius: 2, background: '#FA2D48' }}
        />
      </div>
    </PhoneFrame>
  )
}

// ── Tile wrapper ─────────────────────────────────────────────────────────────

function Tile({ children, label, delay = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.35, ease: 'easeOut' }}
      style={{
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.07)',
        borderRadius: 14,
        padding: '20px 14px 16px',
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', gap: 14,
        // Stretch to the grid row height. Grid row is 1fr so this fills
        // the available vertical space between header and CTA button.
        height: '100%',
      }}
    >
      <div style={{
        flex: 1,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        width: '100%',
      }}>{children}</div>
      <span style={{
        fontSize: 12, fontWeight: 600,
        letterSpacing: '0.04em',
        color: 'rgba(255,255,255,0.78)',
        textAlign: 'center', lineHeight: 1.25,
      }}>{label}</span>
    </motion.div>
  )
}

// ── Overlay ──────────────────────────────────────────────────────────────────

export default function GuideOverlay({ onDismiss }) {
  const [open, setOpen] = useState(true)

  const dismiss = () => {
    try { localStorage.setItem(STORAGE_KEY, 'true') } catch { /* private mode etc. */ }
    setOpen(false)
    // Defer notifying the parent so the exit animation can finish.
    setTimeout(() => onDismiss?.(), 350)
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          style={{
            position: 'absolute', inset: 0, zIndex: 250,
            background: 'linear-gradient(160deg, #111114 0%, #1a1a1e 60%, #0d0d10 100%)',
            display: 'flex', flexDirection: 'column',
            // flex-start (top-aligned) so the button's `marginTop: auto`
            // actually pushes it to the bottom. Header + grid stack from the
            // top with their own margins; button anchors to the bottom edge.
            alignItems: 'center', justifyContent: 'flex-start',
            padding: '48px 24px 24px',
            overflow: 'hidden',
          }}
        >
          {/* Header */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4 }}
            style={{
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', gap: 4,
              marginBottom: 26,
            }}
          >
            <p style={{
              margin: 0, fontSize: 10, fontWeight: 700,
              letterSpacing: '0.22em', textTransform: 'uppercase', color: '#FA2D48',
            }}>
              Quick Tour
            </p>
            <h2 style={{
              margin: 0, fontSize: 26, fontWeight: 800,
              letterSpacing: '-0.04em', color: '#FFFFFF',
              fontFamily: "'Geist', sans-serif",
            }}>
              How it works
            </h2>
          </motion.div>

          {/* 2×2 gesture grid — wrapped in flex:1 so it fills the entire
              vertical space between header and the bottom CTA. Inside, the
              grid uses `1fr 1fr` for both columns AND rows, so all four
              tiles share the available height evenly. */}
          <div style={{
            flex: 1,
            width: '100%',
            maxWidth: 380,
            display: 'flex', flexDirection: 'column',
            minHeight: 0,                   /* allow flex item to shrink */
            paddingBottom: 20,              /* breathing room above the button */
          }}>
            <div style={{
              flex: 1,
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gridTemplateRows: '1fr 1fr',
              gap: 12,
              minHeight: 0,
            }}>
              <Tile delay={0.12} label="Swipe to advance to next story">
                <SwipeAdvance />
              </Tile>
              <Tile delay={0.20} label="Auto-advance timer">
                <AutoTimer />
              </Tile>
              <Tile delay={0.28} label="Swipe up for full read full story">
                <SwipeUpRead />
              </Tile>
              <Tile delay={0.36} label="History in Read tab">
                <ReadTabIndicator />
              </Tile>
            </div>
          </div>

          {/* Got it CTA — pinned to the bottom of the overlay, full width.
              `marginTop: auto` in the flex column pushes it past the grid;
              `width: 100%` makes it stretch within the overlay's 24px
              horizontal padding. safe-area-inset-bottom keeps it clear of
              the iOS home indicator on PWA installs. */}
          <motion.button
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.55, duration: 0.35 }}
            type="button"
            onClick={dismiss}
            style={{
              marginTop: 'auto',
              marginBottom: 'env(safe-area-inset-bottom, 0px)',
              width: '100%',
              background: '#FA2D48', border: 'none',
              color: '#FFFFFF',
              padding: '14px 24px',
              borderRadius: 999,
              fontSize: 14, fontWeight: 700,
              letterSpacing: '0.02em',
              cursor: 'pointer',
              boxShadow: '0 6px 22px rgba(250,45,72,0.35)',
              fontFamily: 'inherit',
            }}
          >
            Got it
          </motion.button>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
