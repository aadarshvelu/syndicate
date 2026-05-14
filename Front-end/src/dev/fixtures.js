// TEMPORARY: dev fixtures for validating TweetCard / NewsCard rendering.
// Triggered by URL flag ?dev=tweets — see App.jsx for the loader.
//
// Content: 10 handpicked real items from db/snapshot.db, captured to
// ./handpicked.json. All ids/cluster_ids are prefixed with `dev-real-`
// so they don't collide with anything fetched from news-archive by syncFeed.
//
// The 10 items:
//   News (2 standalone + 2 reaction-parents)
//     dev-real-d84b5a36  rss/fortune        — AI godfather extinction warning
//     dev-real-330418c6  rss/the_deep_dive  — U.S. Inflation 3.8%
//     dev-real-958bbf31  rss/openai_news    — OpenAI launches DeployCo  (parent of 2 reactions)
//     dev-real-31c14622  rss/openai_news    — Advancing voice intelligence (parent of 2 reactions)
//   Tweets (2 standalone)
//     dev-real-0e6f53e0  twitter/GaryMarcus    — "not a victory for pure LLMs"
//     dev-real-212f5ef9  twitter/demishassabis — "No.1 application of AI"
//   Reactions (4, paired with the 2 reaction-parents above)
//     dev-real-43fcb601  twitter/swyx          → DeployCo
//     dev-real-d2d9ab1b  twitter/sama          → DeployCo  (the ?)
//     dev-real-efbae968  twitter/gdb           → DeployCo
//     dev-real-296dc276  twitter/gdb           → Voice intel
//
// To remove this validation surface:
//   1. delete this file + handpicked.json
//   2. delete the loadDevFixtures()/handleDev* helpers in App.jsx
// To wipe injected items locally:  open with ?dev=clear

import handpicked from './handpicked.json'

const DEV_PREFIX = 'dev-real-'

export function devFixtures() {
  return handpicked
}

export const DEV_FIXTURE_PREFIXES = [DEV_PREFIX]
