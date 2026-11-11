import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { rollupOptions: { output: { manualChunks: { validation: ['zod'], framework: ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query'] } } } },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', ws: true } },
  },
});
