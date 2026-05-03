import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  base: '/syndicate/',
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      strategies: 'injectManifest',
      srcDir: 'src/sw',
      filename: 'sw.js',
      injectManifest: {
        injectionPoint: undefined,
      },
      includeAssets: ['favicon.svg', 'pwa-icon.svg', 'pwa-icon-maskable.svg'],
      manifest: {
        name: 'Syndicate — AI News Digest',
        short_name: 'Syndicate',
        description: 'Your daily AI-curated news digest. Swipe through top stories across tech, AI research, policy, economics, and more.',
        theme_color: '#111114',
        background_color: '#111114',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/syndicate/',
        scope: '/syndicate/',
        icons: [
          { src: 'pwa-icon.svg',          sizes: 'any', type: 'image/svg+xml', purpose: 'any'       },
          { src: 'pwa-icon-maskable.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'maskable'  },
        ],
      },
    }),
  ],
})
