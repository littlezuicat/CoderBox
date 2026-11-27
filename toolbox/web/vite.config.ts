import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
// Monaco 的 worker 用 ES 模块；esnext 目标
export default defineConfig({
  base: './',
  plugins: [react()],
  server: { host: '0.0.0.0', port: 5190 },
  worker: { format: 'es' },
  optimizeDeps: { esbuildOptions: { tsconfigRaw: { compilerOptions: { experimentalDecorators: true } } } },
  build: { target: 'esnext', chunkSizeWarningLimit: 100000 },
})
