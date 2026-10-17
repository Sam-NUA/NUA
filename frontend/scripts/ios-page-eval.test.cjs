'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const { attach } = require('webdriverio');
const evaluatePage = require('./ios-page-eval.cjs');

test('iOS page evaluation awaits a promise and preserves false/null values', async () => {
  const driver = { execute: async script => {
    assert.equal(script.constructor.name, 'AsyncFunction');
    return script();
  } };
  assert.equal(await evaluatePage(driver, 'Promise.resolve(42)'), 42);
  assert.equal(await evaluatePage(driver, 'Promise.resolve(false)'), false);
  assert.equal(await evaluatePage(driver, 'Promise.resolve(null)'), null);
  await assert.rejects(evaluatePage(driver, 'Promise.reject(new Error("page failure"))'), /page failure/);
});

test('public WebdriverIO 10 uses the W3C async endpoint for the iOS helper', async () => {
  const requests = [];
  const server = http.createServer(async (request, response) => {
    let body = '';
    for await (const chunk of request) body += chunk;
    requests.push({ method: request.method, path: request.url, body: JSON.parse(body || '{}') });
    response.setHeader('Content-Type', 'application/json');
    const value = request.url.endsWith('/context') ? 'WEBVIEW_nua-test'
      : request.url.endsWith('/window') ? 'nua-window' : { ok: true, value: 'resolved-page-result' };
    response.end(JSON.stringify({ value }));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    const driver = await attach({ sessionId: 'nua-test', hostname: '127.0.0.1', port: server.address().port,
      path: '/', capabilities: { platformName: 'iOS', browserName: 'Safari' }, logLevel: 'silent' });
    assert.equal(await evaluatePage(driver, 'Promise.resolve("resolved-page-result")'), 'resolved-page-result');
    // The SDK may probe context/window on attach; page execution must use only
    // one async script command, never the synchronous execute/sync endpoint.
    const commands = requests.filter(r => r.method === 'POST');
    assert.equal(commands.length, 1);
    assert.equal(commands[0].path, '/session/nua-test/execute/async');
    assert.match(commands[0].body.script, /async function/);
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});
