const DB_NAME = 'syndicate'
const DB_VERSION = 2

let _db = null

export function openDB() {
  if (_db) return Promise.resolve(_db)

  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)

    req.onupgradeneeded = (e) => {
      const db = e.target.result
      if (!db.objectStoreNames.contains('items')) {
        const store = db.createObjectStore('items', { keyPath: 'id' })
        store.createIndex('date', 'date')
        store.createIndex('is_read', 'is_read')
        store.createIndex('category', 'category')
        store.createIndex('fetched_at', 'fetched_at')
      }
      if (!db.objectStoreNames.contains('meta')) {
        db.createObjectStore('meta', { keyPath: 'key' })
      }
      if (!db.objectStoreNames.contains('likes')) {
        const likes = db.createObjectStore('likes', { keyPath: 'id', autoIncrement: true })
        likes.createIndex('liked_at', 'liked_at')
      }
    }

    req.onsuccess = (e) => {
      _db = e.target.result
      // Release connection if another tab opens a higher version — prevents upgrade blocking
      _db.onversionchange = () => { _db.close(); _db = null }
      resolve(_db)
    }
    req.onerror = () => reject(req.error)
  })
}
