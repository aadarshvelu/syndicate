import { openDB } from './schema.js'
import { upsertItems, cleanOldRead } from './store.js'

const REPO_RAW = 'https://raw.githubusercontent.com/aadarshvelu/news-archive/main'
const SYNC_INTERVAL_MS = 60 * 60 * 1000 // 1hr

async function getLastSyncAt() {
  const db = await openDB()
  return new Promise((resolve) => {
    const req = db.transaction('meta', 'readonly').objectStore('meta').get('lastSyncAt')
    req.onsuccess = () => resolve(req.result?.value ?? 0)
    req.onerror = () => resolve(0)
  })
}

async function setLastSyncAt(ts) {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const req = db.transaction('meta', 'readwrite').objectStore('meta').put({ key: 'lastSyncAt', value: ts })
    req.onsuccess = () => resolve()
    req.onerror = () => reject(req.error)
  })
}

function feedUrl(date) {
  const d = new Date(date)
  const day = d.getDate()
  const month = d.toLocaleString('en-US', { month: 'long' })
  const mon = d.toLocaleString('en-US', { month: 'short' })
  const year = d.getFullYear()
  const yy = String(year).slice(2)
  return `${REPO_RAW}/${year}/${month}/${day}-${mon}-${yy}.json`
}

async function fetchDay(date) {
  try {
    const res = await fetch(feedUrl(date), { cache: 'no-store' })
    if (!res.ok) return []
    return await res.json()
  } catch {
    return []
  }
}

export async function syncFeed({ force = false } = {}) {
  const now = Date.now()
  const lastSyncAt = await getLastSyncAt()
  if (!force && now - lastSyncAt < SYNC_INTERVAL_MS) return { skipped: true }

  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)

  const [todayItems, yestItems] = await Promise.all([
    fetchDay(today),
    fetchDay(yesterday),
  ])

  const all = [...todayItems, ...yestItems]
  const inserted = await upsertItems(all)
  const cleaned = await cleanOldRead()

  await setLastSyncAt(now)
  return { inserted, cleaned, total: all.length }
}

// Called by SW postMessage or on app focus staleness check
export function registerSyncListener() {
  if (!('serviceWorker' in navigator)) return

  navigator.serviceWorker.addEventListener('message', (e) => {
    if (e.data?.type === 'SYNC_FEED') syncFeed({ force: true })
  })

  // Fallback: sync on tab visibility if > 1hr stale
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') syncFeed()
  })
}

// Register periodic background sync (Chromium PWA only)
export async function registerPeriodicSync() {
  if (!('serviceWorker' in navigator) || !('periodicSync' in ServiceWorkerRegistration.prototype)) return

  try {
    const reg = await navigator.serviceWorker.ready
    await reg.periodicSync.register('syndicate-feed-sync', { minInterval: SYNC_INTERVAL_MS })
  } catch {
    // Permission denied or not supported — fallback handles it
  }
}
