import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// @ts-ignore Node is supplied by the Vite runtime.
import { execFileSync } from 'node:child_process';
const apiBuild = JSON.parse(execFileSync('python3', ['-m', 'modelanvil.build_info'], { cwd: new URL('..', import.meta.url), encoding: 'utf8' }));

declare const process: { env: Record<string, string | undefined> };

const apiTarget = process.env.VITE_API_URL || 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react()],
  define: { __API_BUILD__: JSON.stringify(apiBuild) },
  server: {
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: false,
      },
    },
  },
});
