// Auto-update: activate immediately, claim all clients
self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()))

// Periodic background sync — fires ~every 1hr when installed as PWA (Chromium only)
self.addEventListener('periodicsync', (e) => {
  if (e.tag === 'syndicate-feed-sync') {
    e.waitUntil(
      self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
        // Wake up any open tab to run sync via postMessage
        if (clients.length > 0) {
          clients[0].postMessage({ type: 'SYNC_FEED' })
        }
        // If no tab open, sync will run on next app open via staleness check
      })
    )
  }
})
