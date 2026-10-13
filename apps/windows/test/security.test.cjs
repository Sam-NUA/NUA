'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { isAppUrl, apiOrigin, assetPath, safeFilename, safeHtmlDocument, assertSender, contentSecurityPolicy } = require('../src/policy.cjs');
const { renderReceipt } = require('../src/receipt.cjs');
const { windowsCrypto } = require('../src/windows-crypto.cjs');
test('origin validation rejects URL tricks and insecure API origins', () => {
  for (const url of ['https://app','nua://app.evil','nua://evil@app','nua://app:123','javascript:alert(1)','file:///app']) assert.equal(isAppUrl(url), false, url);
  assert.equal(isAppUrl('nua://app/pos?x=y'), true);
  for (const url of ['http://api.example','https://api.example/path','https://user@api.example','https://api.example/?key=secret']) assert.throws(() => apiOrigin(url));
});
test('asset resolver never serves files outside bundle', () => {
  const root = path.resolve('renderer');
  for (const url of ['nua://app/%2e%2e%2fsecret','nua://app/%5c..%5csecret','nua://app/%00','nua://other/index.html']) assert.throws(() => assetPath(url, root));
  assert.equal(assetPath('nua://app/static/main.js', root), path.join(root,'static','main.js'));
});
test('IPC denies foreign frames and other windows even at trusted URL', () => {
  const frame = { url: 'nua://app/pos' }, contents = { mainFrame: frame };
  const window = { isDestroyed: () => false, webContents: contents };
  assert.doesNotThrow(() => assertSender({ sender: contents, senderFrame: frame }, window));
  assert.throws(() => assertSender({ sender: contents, senderFrame: { url: frame.url } }, window));
  assert.throws(() => assertSender({ sender: {}, senderFrame: frame }, window));
  frame.url = 'https://app.nuapos.com.au';
  assert.throws(() => assertSender({ sender: contents, senderFrame: frame }, window));
});
test('CSP permits configured API but no remote or inline script execution', () => {
  const csp = contentSecurityPolicy('https://api.example');
  assert.match(csp, /script-src 'self';/); assert.match(csp, /connect-src 'self' https:\/\/api.example wss:\/\/api.example;/);
});
test('receipt escapes active HTML and rejects invalid amounts and item counts', () => {
  const r = { businessName:'<img src=x onerror=alert(1)>', receiptId:'"<&', items:[{name:'<script>alert(1)</script>',quantity:1,totalCents:100}], totalCents:100 };
  const html = renderReceipt(r);
  assert.ok(!html.includes('<script>')); assert.match(html,/&lt;script&gt;/); assert.ok(!html.includes('<img'));
  assert.throws(() => renderReceipt({...r,totalCents:NaN}));
  assert.throws(() => renderReceipt({...r,items:Array(201).fill(r.items[0])}));
  assert.throws(() => renderReceipt({...r,items:[{...r.items[0],quantity:0}]}));
});
test('save-file name rejects path traversal and device-file tricks', () => {
  for (const name of ['../secret.csv','a/b.csv','a\\b.csv','.', '..', '', 'x\0.csv', 'a'.repeat(201)]) assert.throws(() => safeFilename(name), name);
  assert.equal(safeFilename('payroll-2026-10.csv'), 'payroll-2026-10.csv');
});
test('print-html bounds document type and size, unlike the structured receipt path', () => {
  assert.throws(() => safeHtmlDocument(null));
  assert.throws(() => safeHtmlDocument(''));
  assert.throws(() => safeHtmlDocument('<html></html>'.padEnd(2 * 1024 * 1024 + 1, ' ')));
  assert.equal(safeHtmlDocument('<html></html>'), '<html></html>');
});
test('Windows crypto never falls back to plaintext', () => {
  const provider = { isEncryptionAvailable: () => false };
  assert.throws(() => windowsCrypto(provider,'win32').encryptString('value'));
  assert.throws(() => windowsCrypto(provider,'linux').encryptString('value'));
});
