import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

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
        target: 'http://192.168.52.134:8765',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://192.168.52.134:8765',
        ws: true,
      },
    },
  },
})
