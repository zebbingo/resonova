import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendHttp = process.env.VITE_BACKEND_HTTP_URL || 'http://192.168.52.134:8765'
const backendWs = process.env.VITE_BACKEND_WS_URL || 'ws://192.168.52.134:8765'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ['**/backend/**'],
    },
    proxy: {
      '/api': {
        target: backendHttp,
        changeOrigin: true,
      },
      '/ws': {
        target: backendWs,
        ws: true,
      },
    },
  },
})
