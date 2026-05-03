import { motion } from 'framer-motion'

const TABS = [
  {
    id: 'unread',
    label: 'Unread',
    icon: (active) => (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth={active ? 2.1 : 1.7}
        strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 4h16v12H4z" />
        <path d="M4 8l8 5 8-5" />
      </svg>
    ),
  },
  {
    id: 'read',
    label: 'Read',
    icon: (active) => (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth={active ? 2.1 : 1.7}
        strokeLinecap="round" strokeLinejoin="round">
        <path d="M9 11l3 3L22 4" />
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
      </svg>
    ),
  },
]

export default function BottomNav({ active, onChange, unreadCount = 0 }) {
  return (
    <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, zIndex: 50, height: 60 }}>

      <svg style={{ position: 'absolute', width: 0, height: 0, overflow: 'hidden' }}>
        <defs>
          <filter id="nav-gooey" x="-20%" y="-60%" width="140%" height="220%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="blur" />
            <feColorMatrix in="blur" mode="matrix"
              values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 22 -10" result="gooey" />
          </filter>
        </defs>
      </svg>

      {/* Glass shell — rounded top mirrors card's rounded bottom */}
      <div style={{
        position: 'absolute', inset: 0, borderRadius: '20px 20px 0 0',
        background: 'rgba(255,255,255,0.80)',
        backdropFilter: 'blur(40px) saturate(180%)',
        WebkitBackdropFilter: 'blur(40px) saturate(180%)',
        border: '1px solid rgba(255,255,255,0.9)',
        boxShadow: `
          0 0 0 0.5px rgba(0,0,0,0.06),
          0 4px 20px rgba(0,0,0,0.08),
          0 1px 2px rgba(0,0,0,0.05),
          inset 0 1px 0 rgba(255,255,255,1)
        `,
      }} />

      {/* Gooey pill */}
      <div style={{
        position: 'absolute', inset: 0, display: 'flex',
        padding: '5px 5px 0', filter: 'url(#nav-gooey)', pointerEvents: 'none',
      }}>
        {TABS.map((tab) => (
          <div key={tab.id} style={{ flex: 1, position: 'relative', borderRadius: 14 }}>
            {active === tab.id && (
              <motion.div
                layoutId="nav-pill"
                transition={{ type: 'spring', stiffness: 420, damping: 32, mass: 0.9 }}
                style={{
                  position: 'absolute', inset: 0, borderRadius: 14,
                  background: 'rgba(250,45,72,0.10)',
                }}
              />
            )}
          </div>
        ))}
      </div>

      {/* Buttons */}
      <div style={{ position: 'absolute', inset: 0, display: 'flex', padding: '5px 5px 0' }}>
        {TABS.map((tab) => {
          const isActive = active === tab.id
          const showBadge = tab.id === 'unread' && unreadCount > 0

          return (
            <button
              key={tab.id}
              onClick={() => onChange(tab.id)}
              style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center', gap: 2,
                background: 'transparent', border: 'none', cursor: 'pointer',
                borderRadius: 14, padding: 0,
                WebkitTapHighlightColor: 'transparent', outline: 'none',
              }}
            >
              <motion.span
                animate={{ color: isActive ? '#FA2D48' : 'rgba(0,0,0,0.38)', scale: isActive ? 1.08 : 1 }}
                transition={{ type: 'spring', stiffness: 400, damping: 28 }}
                style={{ display: 'flex', position: 'relative' }}
              >
                {tab.icon(isActive)}

                {showBadge && (
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    style={{
                      position: 'absolute', top: -5, right: -6,
                      background: '#FA2D48', color: '#fff',
                      fontSize: 9, fontWeight: 700,
                      minWidth: 16, height: 16, borderRadius: 8,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      padding: '0 4px',
                      border: '1.5px solid rgba(255,255,255,0.9)',
                    }}
                  >
                    {unreadCount > 99 ? '99+' : unreadCount}
                  </motion.div>
                )}
              </motion.span>

              <motion.span
                animate={{ color: isActive ? '#FA2D48' : 'rgba(0,0,0,0.35)', fontWeight: isActive ? 650 : 400 }}
                style={{ fontSize: 10, letterSpacing: '0.01em' }}
              >
                {tab.label}
              </motion.span>
            </button>
          )
        })}
      </div>
    </div>
  )
}
