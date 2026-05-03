import { useState, useEffect, useMemo } from 'react'
import AppShell from './components/AppShell'
import LoadingScreen from './components/LoadingScreen'
import BottomNav from './components/BottomNav'
import FeedStack from './components/FeedStack'
import ReadStack from './components/ReadStack'
import { getAllItems, markRead } from './db/store'
import { syncFeed, registerSyncListener, registerPeriodicSync } from './db/sync'

export default function App() {
  const [loading, setLoading]   = useState(true)
  const [status, setStatus]     = useState('Fueling up the engine...')
  const [tab, setTab]           = useState('unread')
  const [items, setItems]       = useState([])

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
          {/* Feed area */}
          <div
            style={{
              position: 'absolute',
              inset: 0,
              bottom: 0,
              padding: 0,
            }}
          >
            {tab === 'unread'
              ? <FeedStack items={unread} onCardRead={handleRead} />
              : <ReadStack items={read} />
            }
          </div>

          <BottomNav active={tab} onChange={setTab} unreadCount={unread.length} />
        </div>
      )}
    </AppShell>
  )
}
