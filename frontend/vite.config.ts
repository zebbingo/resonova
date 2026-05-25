import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,  // 固定前端端口
    strictPort: true,  // 如果端口被占用则报错，不自动切换
    proxy: {
      '/api': {
        target: 'http://192.168.52.134:8765',  // WSL 中的后端
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://192.168.52.134:8765',  // WSL 中的后端
        ws: true,
      },
    },
  },
})
