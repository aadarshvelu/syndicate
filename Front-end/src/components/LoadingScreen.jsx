import { useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { motion, AnimatePresence } from 'framer-motion'
// eslint-disable-next-line no-unused-vars
import * as THREE from 'three'

// Module-level constants — Math.random outside render cycle
const PARTICLE_COUNT = 90
const PARTICLE_POS = (() => {
  const arr = new Float32Array(PARTICLE_COUNT * 3)
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    arr[i * 3]     = (Math.random() - 0.5) * 12
    arr[i * 3 + 1] = (Math.random() - 0.5) * 18
    arr[i * 3 + 2] = Math.random() * -6
  }
  return arr
})()

function ParticleField() {
  const ref = useRef()

  useFrame(() => {
    if (!ref.current) return
    const arr = ref.current.geometry.attributes.position.array
    for (let i = 0; i < PARTICLE_COUNT; i++) {
      arr[i * 3 + 1] += 0.004
      if (arr[i * 3 + 1] > 9) arr[i * 3 + 1] = -9
    }
    ref.current.geometry.attributes.position.needsUpdate = true
  })

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute args={[PARTICLE_POS, 3]} attach="attributes-position" />
      </bufferGeometry>
      <pointsMaterial size={0.055} color="#FA2D48" opacity={0.45} transparent sizeAttenuation />
    </points>
  )
}

function Scene() {
  return (
    <>
      <ParticleField />
    </>
  )
}

export default function LoadingScreen({ visible, status = 'Fueling up the engine...' }) {
  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          style={{
            position: 'absolute', inset: 0, zIndex: 200,
            background: 'linear-gradient(160deg, #111114 0%, #1a1a1e 60%, #0d0d10 100%)',
            display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center',
            overflow: 'hidden',
          }}
          initial={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5, ease: 'easeInOut' }}
        >
          <div style={{ position: 'absolute', inset: 0 }}>
            <Canvas
              camera={{ position: [0, 0, 5.5], fov: 42 }}
              gl={{ antialias: true, alpha: false }}
              style={{ background: 'transparent' }}
            >
              <Scene />
            </Canvas>
          </div>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.18, duration: 0.5 }}
            style={{
              position: 'relative', zIndex: 10,
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', gap: 6,
              pointerEvents: 'none',
            }}
          >
            <p style={{
              margin: 0, fontSize: 11, fontWeight: 700,
              letterSpacing: '0.22em', textTransform: 'uppercase', color: '#FA2D48',
            }}>
              AI News Digest
            </p>
            <h1 style={{
              margin: 0, fontSize: 44, fontWeight: 800,
              letterSpacing: '-0.05em', color: '#FFFFFF',
              fontFamily: "'Geist', sans-serif",
            }}>
              Syndicate
            </h1>

            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.55 }}
              style={{
                marginTop: 24,
                display: 'flex', flexDirection: 'column',
                alignItems: 'center', gap: 10,
              }}
            >
              <motion.div
                animate={{ rotate: 360 }}
                transition={{ duration: 0.9, repeat: Infinity, ease: 'linear' }}
                style={{
                  width: 20, height: 20, borderRadius: '50%',
                  border: '2.5px solid rgba(255,255,255,0.10)',
                  borderTopColor: '#FA2D48',
                }}
              />
              <p style={{ margin: 0, fontSize: 12, color: 'rgba(255,255,255,0.38)', fontWeight: 400 }}>
                {status}
              </p>
            </motion.div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
