'use strict';
const net = require('node:net');

function privateIpv4(host) {
  if (typeof host !== 'string' || !/^(?:\d{1,3}\.){3}\d{1,3}$/.test(host)) {
    throw new Error('Printer must have a numeric private IPv4 address');
  }
  const parts = host.split('.').map(Number);
  if (parts.some(n => n < 0 || n > 255)) throw new Error('Invalid IPv4 address');
  const [a,b] = parts;
  if (!(a === 10 || a === 172 && b >= 16 && b <= 31 ||
        a === 192 && b === 168 || a === 169 && b === 254)) {
    throw new Error('Only private venue LAN addresses are allowed');
  }
  return host;
}

function parseJob(request) {
  if (!request || typeof request !== 'object') throw new Error('Invalid printer request');
  if (request.transport !== 'wifi' && request.transport !== 'windows-spooler') {
    throw new Error('USB/Bluetooth printing requires a printer installed in Windows');
  }
  if (request.transport === 'wifi') {
    privateIpv4(request.host);
    if (!Number.isInteger(request.port) || request.port < 1 || request.port > 65535)
      throw new Error('Invalid port');
    if (typeof request.payload !== 'string' ||
        request.payload.length > 400000 ||
        !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(request.payload)) {
      throw new Error('Invalid ESC/POS payload');
    }
    const bytes = Buffer.from(request.payload,'base64');
    if (!bytes.length || bytes.length > 262144) throw new Error('Print job too large');
    return { transport: request.transport, host: request.host, port: request.port, bytes };
  }
  if (typeof request.printerName !== 'string' || !request.printerName ||
      request.printerName.length > 255) throw new Error('Choose an installed Windows printer');
  if (typeof request.html !== 'string' || request.html.length > 250000) {
    throw new Error('Invalid ticket document');
  }
  return { transport: request.transport, printerName: request.printerName, html: request.html };
}

async function rawNetworkSend(job) {
  return new Promise((resolve, reject) => {
    const socket = new net.Socket();
    let ended = false;
    const finish = (error) => {
      if (ended) return;
      ended = true;
      socket.destroy();
      if (error) reject(new Error('Network printer submission uncertain: ' + error.message));
      else resolve({ status: 'submitted', bytes: job.bytes.length });
    };
    socket.setTimeout(5000, () => finish(new Error('TCP timeout')));
    socket.once('error', finish);
    socket.connect({ host: job.host, port: job.port, timeout: 3500 }, () => {
      socket.end(job.bytes, () => finish());
    });
  });
}
module.exports = { privateIpv4, parseJob, rawNetworkSend };
