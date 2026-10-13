'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { CashOrderQueue } = require('../queue.cjs');
const A={businessId:'A',userId:'owner-A',deviceId:'terminal'}, B={businessId:'B',userId:'owner-B',deviceId:'terminal'};
const cash={paymentMethod:'cash',items:[{productId:'product',quantity:1}]};
function memory() { const map=new Map(); return {read:async k=>structuredClone(map.get(k)??null),write:async(k,v)=>map.set(k,structuredClone(v))}; }
test('lost response then restart replays same ID and exactly one server order', async () => {
  const store=memory(), orders=new Map(); let lose=true, now=0;
  const send=async (p,{expectedScope}) => { assert.equal(JSON.parse(expectedScope)[0],'A'); if(!orders.has(p.clientOpId))orders.set(p.clientOpId,{id:'sale',businessId:'A'}); if(lose){lose=false;throw new Error('lost response');} return orders.get(p.clientOpId); };
  let q=new CashOrderQueue({store,send,now:()=>now}); q.activate(A);
  const row=await q.enqueue(cash); await q.flush(); assert.equal((await q.list())[0].state,'retry');
  q=new CashOrderQueue({store,send,now:()=>now}); q.activate(A); now=10000; await q.flush();
  assert.equal((await q.list())[0].id,row.id); assert.equal((await q.list())[0].state,'synced'); assert.equal(orders.size,1);
});
test('A queue never appears in B and switching stops remaining replay', async () => {
  const store=memory(); let calls=0, q;
  q=new CashOrderQueue({store,send:async()=>{calls++;q.activate(B);return {id:'sale',businessId:'A'};}});
  q.activate(A); await q.enqueue(cash); await q.enqueue(cash); await q.flush();
  assert.equal(calls,1); assert.deepEqual(await q.list(),[]);
  q.activate(A); const rows=await q.list(); assert.equal(rows[0].state,'synced'); assert.equal(rows[1].state,'pending');
  q.lock(); assert.throws(()=>q.list(),/Authentication/);
});
test('forbidden response retained for recovery and blocks later operations', async () => {
  const q=new CashOrderQueue({store:memory(),send:async()=>{throw {status:403};}}); q.activate(A);
  await q.enqueue(cash); await q.enqueue(cash); await q.flush();
  const rows=await q.list(); assert.equal(rows.length,2); assert.equal(rows[0].state,'conflict'); assert.equal(rows[1].attempts,0);
});
test('foreign tenant response never marks order synced', async () => {
  const q=new CashOrderQueue({store:memory(),send:async()=>({id:'foreign',businessId:'B'})}); q.activate(A);
  await q.enqueue(cash); await q.flush(); assert.equal((await q.list())[0].state,'conflict');
});
test('card and customer-balance payments cannot enter cash queue', () => {
  const q=new CashOrderQueue({store:memory(),send:async()=>{}}); q.activate(A);
  for(const p of [{...cash,paymentMethod:'card'},{...cash,pointsRedeemed:1},{...cash,customerId:'customer'},{...cash,giftCards:[{}]}])assert.throws(()=>q.enqueue(p));
});
test('parallel flush calls serialize and backoff prevents immediate retry', async () => {
  let calls=0, now=0;
  const q=new CashOrderQueue({store:memory(),now:()=>now,send:async()=>{calls++;throw {status:503};}}); q.activate(A);
  await q.enqueue(cash); await Promise.all([q.flush(),q.flush()]); assert.equal(calls,1);
  now=3000; await q.flush(); assert.equal(calls,2);
});
test('durable write failure prevents any send', async () => {
  let calls=0; const q=new CashOrderQueue({store:{read:async()=>null,write:async()=>{throw new Error('disk full');}},send:async()=>{calls++;}});q.activate(A);
  await assert.rejects(q.enqueue(cash)); assert.equal(calls,0);
});
