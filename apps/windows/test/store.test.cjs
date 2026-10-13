'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { randomBytes, createCipheriv, createDecipheriv } = require('node:crypto');
const { EncryptedStore } = require('../src/encrypted-store.cjs');
// Real ciphertext for durability tests, not a substitute for Windows DPAPI QA.
function cryptoFixture() {
  const key = randomBytes(32);
  return {
    encryptString(s) { const iv = randomBytes(12); const c = createCipheriv('aes-256-gcm', key, iv); return Buffer.concat([iv,c.update(s,'utf8'),c.final(),c.getAuthTag()]); },
    decryptString(b) { const d = createDecipheriv('aes-256-gcm',key,b.subarray(0,12)); d.setAuthTag(b.subarray(-16)); return Buffer.concat([d.update(b.subarray(12,-16)),d.final()]).toString(); },
  };
}
test('encrypted scoped store survives restart and isolates business and account', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(),'nua-store-')); t.after(() => fs.rm(root,{recursive:true,force:true}));
  const crypto = cryptoFixture(), a = new EncryptedStore(root,crypto);
  await a.write('A/user-A/device', { order:'private receipt' });
  const b = new EncryptedStore(root,crypto);
  assert.deepEqual(await b.read('A/user-A/device'),{order:'private receipt'});
  assert.equal(await b.read('B/user-A/device'),null); assert.equal(await b.read('A/user-B/device'),null);
  assert.ok(!(await fs.readFile(a.filename('A/user-A/device'))).toString().includes('private receipt'));
  await fs.writeFile(a.filename('A/user-A/device'),'corruption'); await assert.rejects(() => b.read('A/user-A/device'));
});
test('failed encryption preserves previous value and later writes recover', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(),'nua-atomic-')); t.after(() => fs.rm(root,{recursive:true,force:true}));
  let fail=false; const real=cryptoFixture();
  const store = new EncryptedStore(root,{...real,encryptString: value => { if(fail) throw new Error('OS locked'); return real.encryptString(value); }});
  await store.write('scope',{n:1}); fail=true; await assert.rejects(store.write('scope',{n:2}));
  assert.deepEqual(await store.read('scope'),{n:1}); fail=false;
  await store.write('scope',{n:3}); assert.deepEqual(await store.read('scope'),{n:3});
});

test('cash order survives encrypted-file restart and lost response without duplicate server effect', async t => {
  const { CashOrderQueue } = require('../../../packages/platform-core/queue.cjs');
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'nua-restart-')); t.after(()=>fs.rm(root,{recursive:true,force:true}));
  const crypto=cryptoFixture(), identity={businessId:'A',userId:'owner',deviceId:'till'}, server=new Map(); let first=true;
  const send=async p=>{ if(!server.has(p.clientOpId))server.set(p.clientOpId,{id:'one-sale',businessId:'A'}); if(first){first=false;throw new Error('connection lost after commit');} return server.get(p.clientOpId); };
  let q=new CashOrderQueue({store:new EncryptedStore(root,crypto),send,now:()=>0}); q.activate(identity);
  await q.enqueue({paymentMethod:'cash',items:[{productId:'p',quantity:1}]}); await q.flush();
  q=new CashOrderQueue({store:new EncryptedStore(root,crypto),send,now:()=>10000}); q.activate(identity); await q.flush();
  assert.equal(server.size,1); assert.equal((await q.list())[0].state,'synced');
});
