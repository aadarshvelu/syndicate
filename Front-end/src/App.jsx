import { useState, useEffect, useMemo, useRef } from 'react'
import { AnimatePresence } from 'framer-motion'
import AppShell from './components/AppShell'
import LoadingScreen from './components/LoadingScreen'
import GuideOverlay, { shouldShowGuide } from './components/GuideOverlay'
import BottomNav from './components/BottomNav'
import FeedStack from './components/FeedStack'
import ReadStack from './components/ReadStack'
import FullArticleSheet from './components/FullArticleSheet'
import ReactionsModal from './components/ReactionsModal'
import { getAllItems, markRead, storeLike, getPreferenceScores } from './db/store'
import { syncFeed, registerSyncListener, registerPeriodicSync } from './db/sync'
import { devFixtures, DEV_FIXTURE_PREFIXES } from './dev/fixtures'

const CAT_LABELS = {
  ai_research:  'AI Research',
  ai_products:  'AI Products',
  economics:    'Economics',
  policy:       'Policy',
  startup:      'Startup',
  world_news:   'World News',
  tech_news:    'Tech',
  other:        'Other',
}

const CHIP_BAR_H = 52 // px — tight strip above nav

function sortItems(all) {
  return all.sort((a, b) => new Date(b.date) - new Date(a.date))
}

function CategoryBar({ items, activeFilter, onFilterChange }) {
  const scrollRef = useRef(null)

  const chips = useMemo(() => {
    const counts = {}
    items.forEach((i) => { if (i.category) counts[i.category] = (counts[i.category] || 0) + 1 })
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1])
    if (!activeFilter) return sorted
    return [...sorted.filter(([cat]) => cat === activeFilter), ...sorted.filter(([cat]) => cat !== activeFilter)]
  }, [items, activeFilter])

  const handleChipClick = (cat) => {
    onFilterChange(cat)
    scrollRef.current?.scrollTo({ left: 0, behavior: 'smooth' })
  }

  if (chips.length === 0) return null

  return (
    <div ref={scrollRef} style={{
      position: 'absolute',
      bottom: 'calc(60px + env(safe-area-inset-bottom, 0px))',
      left: 0, right: 0,
      height: CHIP_BAR_H,
      display: 'flex', alignItems: 'center',
      overflowX: 'auto',
      paddingLeft: 10, paddingRight: 10, gap: 8,
      scrollbarWidth: 'none',
      msOverflowStyle: 'none',
      zIndex: 30,
    }}>
      {chips.map(([cat, count]) => {
        const active = activeFilter === cat
        return (
          <div
            key={cat}
            onClick={() => handleChipClick(cat)}
            style={{
              flexShrink: 0,
              display: 'flex', alignItems: 'center', gap: 4,
              background: '#fff',
              border: active ? '1.5px solid #FF3B30' : '1.5px solid transparent',
              borderRadius: 20,
              padding: '7px 12px',
              boxShadow: '0 1px 4px rgba(0,0,0,0.10)',
              whiteSpace: 'nowrap',
              cursor: 'pointer',
              transition: 'border-color 0.18s',
            }}
          >
            <svg width="13.4" height="16.4" viewBox="0 0 16 16" fill="none" style={{ flexShrink: 0 }}>
              <defs>
                <linearGradient id="hg" x1="0" y1="16" x2="16" y2="0" gradientUnits="userSpaceOnUse">
                  <stop offset="0%"   stopColor="#FCAF45" />
                  <stop offset="35%"  stopColor="#E1306C" />
                  <stop offset="70%"  stopColor="#C13584" />
                  <stop offset="100%" stopColor="#833AB4" />
                </linearGradient>
              </defs>
              <line x1="4.5" y1="14" x2="6.5" y2="2"  stroke="url(#hg)" strokeWidth="2.2" strokeLinecap="round"/>
              <line x1="10"  y1="14" x2="12"  y2="2"  stroke="url(#hg)" strokeWidth="2.2" strokeLinecap="round"/>
              <line x1="1.5" y1="5.5"  x2="14.5" y2="5.5"  stroke="url(#hg)" strokeWidth="2.2" strokeLinecap="round"/>
              <line x1="1.5" y1="10.5" x2="14.5" y2="10.5" stroke="url(#hg)" strokeWidth="2.2" strokeLinecap="round"/>
            </svg>
            <span style={{ fontSize: 13, fontWeight: 600, color: '#1C1C1E', lineHeight: 1 }}>
              {CAT_LABELS[cat] ?? cat}
            </span>
            <span style={{
              fontSize: 11, fontWeight: 600, lineHeight: 1.2,
              color: '#fff',
              background: '#FF3B30',
              borderRadius: 10, padding: '3px 6px', minWidth: 22,
              textAlign: 'center', marginLeft: 1,
            }}>
              {count}
            </span>
          </div>
        )
      })}
    </div>
  )
}

export default function App() {
  const [loading,   setLoading]   = useState(true)
  const [status,    setStatus]    = useState('Fueling up the engine...')
  // First-launch guide. Computed once at mount — once dismissed, the guide
  // sets localStorage.isGuideShown='true' and shouldShowGuide() returns
  // false for every future visit on this device.
  const [showGuide, setShowGuide] = useState(() => shouldShowGuide())
  const [tab,       setTab]       = useState('unread')
  const [items,        setItems]        = useState([])
  const [sheetCard,    setSheetCard]    = useState(null)
  const [activeFilter, setActiveFilter] = useState(null)
  // Reactions modal state: { reactions, parent, startIndex } | null
  const [reactionModal, setReactionModal] = useState(null)

  const loadItems = async () => {
    const all = await getAllItems()
    setItems(sortItems(all))
  }

  useEffect(() => {
    if (screen.orientation?.lock) screen.orientation.lock('portrait').catch(() => {})

    async function init() {
      // TEMP dev-mode: ?dev=tweets injects TweetCard validation fixtures.
      //                ?dev=clear wipes them. Remove this block + src/dev/ when done.
      const devFlag = new URLSearchParams(window.location.search).get('dev')
      if (devFlag === 'tweets')      await handleDevInject()
      else if (devFlag === 'clear')  await handleDevClear()

      const existing = await getAllItems()
      if (existing.length > 0) {
        // Render cached items immediately, then force a fresh fetch — the
        // 1hr throttle is intentionally bypassed here so every PWA launch /
        // hard refresh actually pulls today's feed. visibilitychange below
        // still uses the throttle so app-switching doesn't spam the CDN.
        setItems(sortItems(existing))
        setLoading(false)
        syncFeed({ force: true }).then(loadItems)
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

  // ─── Dev-mode helpers (temporary) ─────────────────────────────────────────

  async function handleDevInject() {
    try {
      const { upsertItems } = await import('./db/store')
      const items = devFixtures()
      console.log(`[dev] preparing to inject ${items.length} fixture(s):`, items.map(i => i.id))
      const inserted = await upsertItems(items)
      console.log(`[dev] injected ${inserted}/${items.length} fixture(s) into IndexedDB ` +
                  `(items already present are kept — they only insert on first visit)`)
    } catch (err) {
      console.error('[dev] inject FAILED:', err)
    }
  }

  async function handleDevClear() {
    const { openDB } = await import('./db/schema')
    const db = await openDB()
    const store = db.transaction('items', 'readwrite').objectStore('items')
    const req = store.openCursor()
    let deleted = 0
    await new Promise((resolve) => {
      req.onsuccess = (e) => {
        const cursor = e.target.result
        if (!cursor) return resolve()
        const id = cursor.value.id || ''
        if (DEV_FIXTURE_PREFIXES.some(p => id.startsWith(p))) {
          cursor.delete()
          deleted++
        }
        cursor.continue()
      }
      req.onerror = () => resolve()
    })
    console.log(`[dev] cleared ${deleted} fixture item(s) from IndexedDB`)
  }

  const [scores, setScores] = useState({ categories: {}, sources: {} })

  useEffect(() => {
    getPreferenceScores().then(setScores)
  }, [])

  // Phase 3f note: unread count works correctly as-is.
  // - Reactions whose parent is UNREAD     → in `raw`, but filtered out by
  //   FeedStack's reactionsByCluster check (they render as pills on parent).
  // - Reactions whose parent has been READ → in `raw`, NOT filtered by
  //   FeedStack (parent not in feed), surface as standalone tweet cards.
  const unread = useMemo(() => {
    const raw = items.filter((i) => !i.is_read)
    return [...raw].sort((a, b) => {
      const score = (item) =>
        (scores.categories[item.category] || 0) * 2 +
        (scores.sources[item.source] || 0)
      return score(b) - score(a)
    })
  }, [items, scores])

  const read = useMemo(() => items.filter((i) => i.is_read).sort((a, b) => b.read_at - a.read_at), [items])

  const handleFilterChange = (cat) => setActiveFilter(prev => prev === cat ? null : cat)

  const handleRead = async (id) => {
    await markRead(id)
    await loadItems()
  }

  // Wired into pull-to-refresh on both stacks. Force-syncs the feed JSON
  // (bypassing the 1hr throttle) then re-reads IndexedDB. Returns the
  // promise so PTR components can keep their spinner up until done.
  const handleRefresh = async () => {
    await syncFeed({ force: true })
    await loadItems()
  }

  const handleLike = async (card) => {
    await storeLike(card)
    const updated = await getPreferenceScores()
    setScores(updated)
  }

  return (
    <AppShell>
      <LoadingScreen visible={loading} status={status} />

      {/* Quick-tour guide overlay — fires once on first launch (when
          localStorage.isGuideShown is missing/false). Renders AFTER the
          loading screen finishes so users see the brand reveal first,
          then the gesture cheat sheet. */}
      {!loading && showGuide && (
        <GuideOverlay onDismiss={() => setShowGuide(false)} />
      )}

      {!loading && (
        <div style={{ position: 'relative', height: '100%' }}>
          {/* Feed area — shrunk by chip bar height */}
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0,
            bottom: tab === 'unread'
              ? `calc(60px + env(safe-area-inset-bottom, 0px) + ${CHIP_BAR_H}px)`
              : `calc(60px + env(safe-area-inset-bottom, 0px))`,
          }}>
            {tab === 'unread'
              ? <FeedStack items={unread} onCardRead={handleRead} onExpand={setSheetCard} sheetCard={sheetCard} filterCategory={activeFilter} onLike={handleLike} onOpenReactions={setReactionModal} reactionModalOpen={reactionModal !== null} onRefresh={handleRefresh} />
              : <ReadStack items={read} onRefresh={handleRefresh} />
            }
          </div>

          {tab === 'unread' && <CategoryBar items={unread} activeFilter={activeFilter} onFilterChange={handleFilterChange} />}

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

          {/* Reactions carousel modal — z-index 350, above FullArticleSheet */}
          <AnimatePresence>
            {reactionModal && (
              <ReactionsModal
                reactions={reactionModal.reactions}
                parent={reactionModal.parent}
                startIndex={reactionModal.startIndex}
                onClose={() => setReactionModal(null)}
              />
            )}
          </AnimatePresence>
        </div>
      )}
    </AppShell>
  )
}
