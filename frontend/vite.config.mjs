import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'REACT_APP_');
  // Keep the existing public build-time contract. Never inject arbitrary env.
  const publicEnv = { REACT_APP_BACKEND_URL: env.REACT_APP_BACKEND_URL ?? '',
    REACT_APP_LICENSE_ENFORCEMENT: env.REACT_APP_LICENSE_ENFORCEMENT ?? 'false',
    NODE_ENV: mode === 'production' ? 'production' : 'development', PUBLIC_URL: process.env.PUBLIC_URL ?? './' };
  return {
    plugins: [react(), {
      name: 'nua-host-build-contract',
      generateBundle(_options, bundle) {
        const entry = Object.values(bundle).find(item => item.type === 'chunk' && item.isEntry);
        if (!entry) throw new Error('Missing application entry');
        const files = Object.fromEntries(Object.values(bundle).map(item => [item.fileName, item.fileName]));
        files['main.js'] = entry.fileName;
        this.emitFile({ type: 'asset', fileName: 'asset-manifest.json', source: JSON.stringify({ files }) });
      },
    }],
    base: process.env.PUBLIC_URL === '/' ? '/' : './',
    define: Object.fromEntries(Object.entries(publicEnv).map(([key, value]) => [`process.env.${key}`, JSON.stringify(value)])),
    resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
    build: { outDir: 'build', target: ['es2020', 'chrome90', 'safari15'], sourcemap: false },
    server: { host: '127.0.0.1', port: 3000, strictPort: true },
    preview: { host: '127.0.0.1', strictPort: true },
  };
});
