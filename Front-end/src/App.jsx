import { useState, useEffect, useMemo } from 'react'
import { AnimatePresence } from 'framer-motion'
import AppShell from './components/AppShell'
import LoadingScreen from './components/LoadingScreen'
import BottomNav from './components/BottomNav'
import FeedStack from './components/FeedStack'
import ReadStack from './components/ReadStack'
import FullArticleSheet from './components/FullArticleSheet'
import { getAllItems, markRead } from './db/store'
import { syncFeed, registerSyncListener, registerPeriodicSync } from './db/sync'

export default function App() {
  const [loading,   setLoading]   = useState(true)
  const [status,    setStatus]    = useState('Fueling up the engine...')
  const [tab,       setTab]       = useState('unread')
  const [items,     setItems]     = useState([])
  const [sheetCard, setSheetCard] = useState(null)

  const loadItems = async () => {
    const all = await getAllItems()
    setItems(all.sort((a, b) => new Date(b.date) - new Date(a.date)))
  }

  useEffect(() => {
    if (screen.orientation?.lock) screen.orientation.lock('portrait').catch(() => {})

    async function init() {
      const existing = await getAllItems()
      if (existing.length > 0) {
        setItems(existing.sort((a, b) => new Date(b.date) - new Date(a.date)))
        setLoading(false)
        syncFeed().then(loadItems)
      } else {
        setStatus('Fetching latest news…')
        await syncFeed({ force: true })
        await loadItems()
        setLoading(false)
      }
      registerSyncListener()
      registerPeriodicSync()
    }

    init()
  }, [])

  const unread = useMemo(() => items.filter((i) => !i.is_read), [items])
  const read   = useMemo(() => items.filter((i) => i.is_read),  [items])

  const handleRead = async (id) => {
    await markRead(id)
    await loadItems()
  }

  return (
    <AppShell>
      <LoadingScreen visible={loading} status={status} />

      {!loading && (
        <div style={{ position: 'relative', height: '100%' }}>
          {/* Feed area — stops above the BottomNav (60px height, flush bottom) */}
          <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 'calc(60px + env(safe-area-inset-bottom, 0px))' }}>
            {tab === 'unread'
              ? <FeedStack items={unread} onCardRead={handleRead} onExpand={setSheetCard} sheetCard={sheetCard} />
              : <ReadStack items={read} />
            }
          </div>

          <BottomNav active={tab} onChange={setTab} unreadCount={unread.length} />

          {/* Sheet lives here — same stacking context as BottomNav, z-index 300 beats it */}
          <AnimatePresence>
            {sheetCard && (
              <FullArticleSheet
                card={sheetCard}
                onClose={() => setSheetCard(null)}
              />
            )}
          </AnimatePresence>
        </div>
      )}
    </AppShell>
  )
}
