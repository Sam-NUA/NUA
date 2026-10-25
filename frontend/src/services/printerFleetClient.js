/**
 * One active gateway per installation/business; multiple printers per gateway.
 * Each printer sends sequentially; independent devices send concurrently.
 * Backend claims make one transaction delivery unique across all logged-in POSs.
 */
import { registerPlugin } from '@capacitor/core';
import { detectPlatform } from '../platform';
import { printerFleetAPI } from './api';
import { generateDocketHTML } from './docket';

const native = registerPlugin('NuaPrinterFleet');
const queues = new Map();
const inProgress = new Set();

export const supported = () => ['android', 'ios', 'electron'].includes(detectPlatform());
const fresh = () => window.crypto?.randomUUID?.() || `${Date.now()}_${Math.random().toString(36).slice(2)}`;
const key = business => `nua_fleet_gateway_${business}`;
const blank = () => ({ gatewayId: `gate_${fresh().replace(/[^a-zA-Z0-9_-]/g, '')}`,
  enabled: false, devices: [] });

export async function getFleetConfig(businessId) {
  if (!businessId || !supported()) return blank();
  let saved = null;
  if (detectPlatform() === 'electron' && window.nuaDesktop?.getFleetConfig) {
    saved = await window.nuaDesktop.getFleetConfig(String(businessId));
  } else {
    saved = window.localStorage.getItem(key(businessId));
  }
  if (!saved) return blank();
  try {
    const config = JSON.parse(saved);
    if (typeof config.gatewayId !== 'string' || !Array.isArray(config.devices)) return blank();
    return { gatewayId: config.gatewayId, enabled: config.enabled === true,
      devices: config.devices.slice(0,32) };
  } catch { return blank(); }
}

export async function saveFleetConfig(businessId, config) {
  if (!supported() || !businessId || !config.gatewayId || !Array.isArray(config.devices))
    throw new Error('A supported, registered NUA terminal is required');
  if (config.devices.length > 32) throw new Error('Maximum 32 printers per gateway');
  const safe = { gatewayId: config.gatewayId, enabled: !!config.enabled, devices: config.devices };
  const value = JSON.stringify(safe);
  if (detectPlatform() === 'electron' && window.nuaDesktop?.setFleetConfig) {
    await window.nuaDesktop.setFleetConfig(String(businessId), value);
  } else window.localStorage.setItem(key(businessId), value);
  return safe;
}

export async function discover() {
  const p = detectPlatform();
  if (p === 'electron') {
    return (await window.nuaDesktop.listPrinters()).map(x => ({
      name: x.displayName || x.name, address: x.name, transport: 'windows-spooler',
    }));
  }
  if (p === 'android' || p === 'ios') {
    return (await native.listDevices()).devices || [];
  }
  return [];
}

export async function requestBluetooth() {
  if (detectPlatform() !== 'android') throw new Error('Use BLE discovery on an iPad');
  return native.requestBluetooth();
}
export async function requestUsb(address) {
  if (detectPlatform() !== 'android') throw new Error('Generic USB printer access requires Android');
  return native.requestUsb({ address });
}
export async function scanBle(serviceUUID) {
  if (detectPlatform() !== 'ios') throw new Error('BLE GATT discovery is supported on iOS');
  return (await native.scanBle({ serviceUUID })).devices || [];
}

export async function registerFleetDevice(config, device) {
  return printerFleetAPI.saveDevice(device.id, {
    gatewayId: config.gatewayId, name: device.name, station: device.station,
    transport: device.transport, enabled: !!device.enabled,
    width: Number(device.width || 48), codepage: device.codepage || 'cp437',
    cut: device.cut || 'partial',
  });
}

export async function syncFleet(config) {
  // A disabled gateway must disable existing routing to it. Never leave a
  // server-side enabled printer target pointing at an offline terminal.
  for (const device of config.devices) {
    await registerFleetDevice(config, {...device, enabled: config.enabled && device.enabled});
  }
}

function onDevice(deviceId, fn) {
  const prev = queues.get(deviceId) || Promise.resolve();
  const next = prev.catch(() => {}).then(fn);
  queues.set(deviceId, next);
  next.finally(() => { if (queues.get(deviceId) === next) queues.delete(deviceId); }).catch(() => {});
  return next;
}

export async function transportSend(device, payload, job) {
  const platform = detectPlatform();
  if (device.transport === 'windows-spooler') {
    if (platform !== 'electron') throw new Error('Windows printer unavailable on this platform');
    return window.nuaDesktop.sendFleetJob({
      transport: 'windows-spooler', printerName: device.address,
      html: job ? generateDocketHTML(job) : '<html><body><h2>NUA POS</h2><p>PRINTER TEST - NOT A SALE</p></body></html>',
    });
  }
  const request = {
    transport: device.transport, host: device.host || '', port: Number(device.port || 9100),
    address: device.address || '', payload,
    serviceUUID: device.serviceUUID || '', characteristicUUID: device.characteristicUUID || '',
  };
  if (platform === 'electron') return window.nuaDesktop.sendFleetJob(request);
  if (platform === 'android' || platform === 'ios') return native.send(request);
  throw new Error('Direct device printing requires NUA native app');
}

export async function fanOut(devices, payloadFor, jobFor = () => null) {
  // Each physical target is an independent Promise. One offline printer
  // cannot block a healthy one; each printer is serialized to prevent bytes
  // from two dockets interleaving on a shared thermal connection.
  return Promise.allSettled(devices.map(device => onDevice(device.id,
    () => transportSend(device, payloadFor(device), jobFor(device)))));
}

export function testPayload() {
  const ascii = '\x1b@\x1ba\x01NUA POS\nPRINTER TEST - NOT A SALE\n\x1ba\x00\n\n\n\x1dVB\x00';
  return btoa(ascii);
}

export async function runFleetPoll(businessId) {
  if (!supported() || !businessId || inProgress.has(businessId)) return;
  inProgress.add(businessId);
  try {
    const config = await getFleetConfig(businessId);
    if (!config.enabled || !config.devices.some(d => d.enabled)) return;
    const { data } = await printerFleetAPI.claim({gatewayId: config.gatewayId, maxJobs: 12});
    const deliveries = data?.deliveries || [];
    if (!deliveries.length) return;
    await Promise.allSettled(deliveries.map(delivery => {
      const device = config.devices.find(d => d.id === delivery.deviceId && d.enabled);
      return onDevice(delivery.deviceId, async () => {
        let status = 'uncertain';
        let error = '';
        try {
          if (!device) throw new Error('Device is not configured on this gateway');
          const result = await transportSend(device, delivery.payload, delivery.job);
          if (result?.status !== 'submitted') throw new Error(result?.reason || 'Printer submission was not confirmed');
          status = 'submitted';
        } catch (err) { error = String(err?.message || err).slice(0,250); }
        // NEVER retry on uncertainty without an operator's explicit action.
        await printerFleetAPI.complete({ gatewayId: config.gatewayId, id: delivery.id,
          token: delivery.token, status, error });
      });
    }));
  } finally { inProgress.delete(businessId); }
}
