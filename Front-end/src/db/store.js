import { openDB } from './schema.js'

const THREE_DAYS_MS = 3 * 24 * 60 * 60 * 1000
const LIKES_CAP     = 500
const DECAY_LAMBDA  = 0.1   // half-life ~7 days

function tx(db, mode) {
  return db.transaction('items', mode).objectStore('items')
}

export async function upsertItems(items) {
  const db = await openDB()
  const store = tx(db, 'readwrite')
  const now = Date.now()

  return new Promise((resolve, reject) => {
    let pending = items.length
    if (pending === 0) return resolve(0)
    let inserted = 0

    items.forEach((item) => {
      const getReq = store.get(item.id)
      getReq.onsuccess = () => {
        if (getReq.result) {
          if (--pending === 0) resolve(inserted)
          return
        }
        const putReq = store.put({ ...item, is_read: false, read_at: null, fetched_at: now })
        putReq.onsuccess = () => { inserted++; if (--pending === 0) resolve(inserted) }
        putReq.onerror = () => reject(putReq.error)
      }
      getReq.onerror = () => reject(getReq.error)
    })
  })
}

export async function getAllItems() {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const req = tx(db, 'readonly').getAll()
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

export async function markRead(id) {
  const db = await openDB()
  const store = tx(db, 'readwrite')
  return new Promise((resolve, reject) => {
    const getReq = store.get(id)
    getReq.onsuccess = () => {
      if (!getReq.result) return resolve()
      const putReq = store.put({ ...getReq.result, is_read: true, read_at: Date.now() })
      putReq.onsuccess = () => resolve()
      putReq.onerror = () => reject(putReq.error)
    }
    getReq.onerror = () => reject(getReq.error)
  })
}

export async function storeLike(card) {
  const db = await openDB()
  const t = db.transaction('likes', 'readwrite')
  const store = t.objectStore('likes')

  return new Promise((resolve, reject) => {
    const addReq = store.add({ category: card.category, source: card.source, liked_at: Date.now() })
    addReq.onsuccess = () => {
      // Enforce cap — delete oldest entries beyond LIKES_CAP
      const countReq = store.count()
      countReq.onsuccess = () => {
        const excess = countReq.result - LIKES_CAP
        if (excess <= 0) return resolve()
        const idx = store.index('liked_at')
        const cursorReq = idx.openCursor()
        let toDelete = excess
        cursorReq.onsuccess = (e) => {
          const cursor = e.target.result
          if (!cursor || toDelete <= 0) return resolve()
          cursor.delete()
          toDelete--
          cursor.continue()
        }
        cursorReq.onerror = () => resolve()
      }
      countReq.onerror = () => resolve()
    }
    addReq.onerror = () => reject(addReq.error)
  })
}

export async function getPreferenceScores() {
  const db = await openDB()
  const store = db.transaction('likes', 'readonly').objectStore('likes')

  return new Promise((resolve, reject) => {
    const req = store.getAll()
    req.onsuccess = () => {
      const now = Date.now()
      const categories = {}
      const sources = {}

      req.result.forEach(({ category, source, liked_at }) => {
        const daysAgo = (now - liked_at) / 86_400_000
        const weight = Math.exp(-DECAY_LAMBDA * daysAgo)
        if (category) categories[category] = (categories[category] || 0) + weight
        if (source)   sources[source]       = (sources[source]   || 0) + weight
      })

      resolve({ categories, sources })
    }
    req.onerror = () => reject(req.error)
  })
}

// Delete read items older than 3 days
export async function cleanOldRead() {
  const db = await openDB()
  const store = tx(db, 'readwrite')
  const cutoff = Date.now() - THREE_DAYS_MS

  return new Promise((resolve, reject) => {
    const req = store.openCursor()
    let deleted = 0
    req.onsuccess = (e) => {
      const cursor = e.target.result
      if (!cursor) return resolve(deleted)
      const { is_read, read_at } = cursor.value
      if (is_read && read_at && read_at < cutoff) {
        cursor.delete()
        deleted++
      }
      cursor.continue()
    }
    req.onerror = () => reject(req.error)
  })
}
