import { openDB } from './schema.js'

const THREE_DAYS_MS = 3 * 24 * 60 * 60 * 1000

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
