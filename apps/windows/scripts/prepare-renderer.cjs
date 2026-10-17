'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { apiOrigin } = require('../src/policy.cjs');
// No default production endpoint. Build the shared UI with this same origin.
const origin = apiOrigin(process.env.NUA_WINDOWS_API_ORIGIN);
const source = path.resolve(__dirname, '../../../frontend/build');
const target = path.resolve(__dirname, '../renderer');
const manifest = JSON.parse(fs.readFileSync(path.join(source, 'asset-manifest.json')));
// Vite may factor shared modules out of the entry; verify the compiled JS set.
const bundle = Object.values(manifest.files).filter(name => name.endsWith('.js'))
  .map(name => fs.readFileSync(path.join(source, name.replace(/^\//, '')), 'utf8')).join('\n');
if (!bundle.includes(origin)) throw new Error('Build frontend with REACT_APP_BACKEND_URL equal to NUA_WINDOWS_API_ORIGIN');
fs.rmSync(target, { recursive: true, force: true });
fs.cpSync(source, target, { recursive: true });
// PWA manifest selection/update scripts are web-only. No inline scripts in the host.
const html = fs.readFileSync(path.join(target, 'index.html'), 'utf8')
  .replace(/<script\b(?![^>]*\bsrc=)[^>]*>[\s\S]*?<\/script>/gi, '')
  .replace('</head>', '<link rel="stylesheet" href="/desktop.css"></head>')
  .replace('</body>', '<script src="/desktop.js" defer></script></body>');
fs.writeFileSync(path.join(target, 'index.html'), html);
fs.copyFileSync(path.join(__dirname, '../src/desktop.css'), path.join(target, 'desktop.css'));
fs.copyFileSync(path.join(__dirname, '../src/desktop.js'), path.join(target, 'desktop.js'));
fs.writeFileSync(path.join(target, 'host-config.json'), JSON.stringify({ apiOrigin: origin, schemaVersion: 1 }));
for (const name of ['service-worker.js', 'sw.js']) fs.rmSync(path.join(target, name), { force: true });
console.log('Shared renderer prepared for Windows; no backend or secrets copied.');
