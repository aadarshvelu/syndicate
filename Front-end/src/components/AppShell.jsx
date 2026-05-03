import { useState, useEffect } from 'react'
import { useDeviceType } from '../hooks/useDeviceType'

function useTime() {
  const fmt = () =>
    new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
  const [time, setTime] = useState(fmt)
  useEffect(() => {
    const id = setInterval(() => setTime(fmt()), 10_000)
    return () => clearInterval(id)
  }, [])
  return time
}

function StatusBar() {
  const time = useTime()
  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: 54,
        display: 'flex',
        alignItems: 'flex-end',
        justifyContent: 'space-between',
        paddingBottom: 8,
        paddingLeft: 24,
        paddingRight: 24,
        zIndex: 20,
        pointerEvents: 'none',
      }}
    >
      {/* Time */}
      <span style={{ fontSize: 15, fontWeight: 600, color: '#000', letterSpacing: '-0.3px' }}>
        {time}
      </span>

      {/* Right icons */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        {/* Signal bars */}
        <svg width="17" height="12" viewBox="0 0 17 12" fill="none">
          {[0,1,2,3].map((i) => (
            <rect key={i} x={i * 4.5} y={12 - (i + 1) * 3} width="3" height={(i + 1) * 3} rx="1"
              fill={i < 4 ? '#000' : 'rgba(0,0,0,0.25)'} />
          ))}
        </svg>
        {/* WiFi */}
        <svg width="16" height="12" viewBox="0 0 16 12" fill="black">
          <path d="M8 9.5a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3z"/>
          <path d="M8 6C6.07 6 4.32 6.76 3 8.01l1.42 1.42A5 5 0 0 1 8 8c1.38 0 2.63.56 3.54 1.46L13 8.01A7 7 0 0 0 8 6z" opacity=".7"/>
          <path d="M8 3C5.1 3 2.5 4.14.69 6L2.1 7.41A8.97 8.97 0 0 1 8 5c2.49 0 4.75 1.01 6.38 2.64L15.79 6.22A10.96 10.96 0 0 0 8 3z" opacity=".4"/>
        </svg>
        {/* Battery */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <div style={{ width: 25, height: 12, borderRadius: 3, border: '1.5px solid rgba(0,0,0,0.35)', padding: '1.5px', display: 'flex' }}>
            <div style={{ width: '80%', background: '#000', borderRadius: 1.5 }} />
          </div>
          <div style={{ width: 2, height: 5, background: 'rgba(0,0,0,0.35)', borderRadius: '0 1px 1px 0' }} />
        </div>
      </div>
    </div>
  )
}

function HomeIndicator() {
  return (
    <div
      style={{
        position: 'absolute',
        bottom: 8,
        left: '50%',
        transform: 'translateX(-50%)',
        width: 134,
        height: 5,
        background: 'rgba(0,0,0,0.2)',
        borderRadius: 3,
        zIndex: 20,
        pointerEvents: 'none',
      }}
    />
  )
}

function DynamicIsland() {
  return (
    <div
      style={{
        position: 'absolute',
        top: 12,
        left: '50%',
        transform: 'translateX(-50%)',
        width: 126,
        height: 37,
        background: '#000',
        borderRadius: 20,
        zIndex: 30,
        pointerEvents: 'none',
      }}
    />
  )
}

function IPhoneFrame({ children }) {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'radial-gradient(ellipse at center, #2a2a2c 0%, #111113 100%)',
      }}
    >
      {/* Device body */}
      <div
        style={{
          position: 'relative',
          width: 393,
          height: 'min(852px, calc(100vh - 48px))',
          borderRadius: 55,
          background: 'linear-gradient(145deg, #2a2a2c 0%, #1a1a1c 40%, #111113 100%)',
          boxShadow: `
            inset 0 0 0 1px rgba(255,255,255,0.13),
            inset 0 1px 0 rgba(255,255,255,0.2),
            0 0 0 1px rgba(0,0,0,0.8),
            0 30px 80px rgba(0,0,0,0.85),
            0 10px 30px rgba(0,0,0,0.5)
          `,
          padding: '10px 9px 10px',
        }}
      >
        {/* Volume buttons — left */}
        {[
          { top: 110, height: 30 },
          { top: 152, height: 60 },
          { top: 224, height: 60 },
        ].map(({ top, height }, i) => (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: -3,
              top,
              width: 3,
              height,
              background: 'linear-gradient(180deg, #3a3a3c 0%, #2a2a2c 100%)',
              borderRadius: '2px 0 0 2px',
              boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.1)',
            }}
          />
        ))}

        {/* Power button — right */}
        <div
          style={{
            position: 'absolute',
            right: -3,
            top: 172,
            width: 3,
            height: 80,
            background: 'linear-gradient(180deg, #3a3a3c 0%, #2a2a2c 100%)',
            borderRadius: '0 2px 2px 0',
            boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.1)',
          }}
        />

        {/* Screen */}
        <div
          style={{
            width: '100%',
            height: '100%',
            borderRadius: 47,
            overflow: 'hidden',
            background: '#FAFAF8',
            position: 'relative',
            boxShadow: 'inset 0 0 0 0.5px rgba(0,0,0,0.8)',
          }}
        >
          <DynamicIsland />
          <StatusBar />
          {/* Content area — children manage their own scroll */}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              top: 54,
              bottom: 28,
            }}
          >
            {children}
          </div>
          <HomeIndicator />
        </div>
      </div>
    </div>
  )
}

export default function AppShell({ children }) {
  const { isDesktop } = useDeviceType()

  if (isDesktop) return <IPhoneFrame>{children}</IPhoneFrame>

  return (
    <div style={{ position: 'fixed', inset: 0, overflow: 'hidden' }}>
      {children}
    </div>
  )
}
