'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { privateIpv4, parseJob } = require('../src/printer-fleet.cjs');

test('network printer target only permits venue LAN, not internet or URL tricks', () => {
  for (const allowed of ['192.168.1.21','10.23.7.3','172.16.2.4','172.31.255.4'])
    assert.equal(privateIpv4(allowed),allowed);
  for (const forbidden of ['127.0.0.1','8.8.8.8','169.254.1.1.evil','localhost',
      'http://192.168.1.2','192.168.1.256','::1','192.168.1.2/../../']) {
    assert.throws(()=>privateIpv4(forbidden),forbidden);
  }
});
test('validates ESC/POS bytes and spooler targets', () => {
  const b64=Buffer.from([27,64,10]).toString('base64');
  assert.equal(parseJob({transport:'wifi',host:'192.168.1.9',port:9100,payload:b64}).bytes.length,3);
  assert.throws(()=>parseJob({transport:'wifi',host:'192.168.1.9',port:0,payload:b64}));
  assert.throws(()=>parseJob({transport:'wifi',host:'192.168.1.9',port:9100,payload:'%%%'}));
  assert.equal(parseJob({transport:'windows-spooler',printerName:'EPSON USB',html:'<html></html>'}).printerName,'EPSON USB');
  assert.throws(()=>parseJob({transport:'windows-spooler',printerName:'',html:'<html></html>'}));
  assert.throws(()=>parseJob({transport:'bluetooth',address:'00:11',payload:b64}));
});
