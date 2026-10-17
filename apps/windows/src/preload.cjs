'use strict';
const { contextBridge, ipcRenderer } = require('electron');
// Explicit methods only: never expose send/invoke, Node, paths, or arbitrary URLs.
contextBridge.exposeInMainWorld('nuaDesktop', Object.freeze({
  activateOffline: business => ipcRenderer.invoke('nua:offline-activate', business),
  lockOffline: () => ipcRenderer.invoke('nua:offline-lock'),
  readOffline: (kind, business) => ipcRenderer.invoke('nua:offline-read', kind, business),
  mutateOffline: (kind, business, commands) => ipcRenderer.invoke('nua:offline-mutate', kind, business, commands),
  getInfo: () => ipcRenderer.invoke('nua:info'),
  setFullscreen: value => ipcRenderer.invoke('nua:fullscreen', value),
  listPrinters: () => ipcRenderer.invoke('nua:printers'),
  printReceipt: receipt => ipcRenderer.invoke('nua:print-receipt', receipt),
  printHtml: html => ipcRenderer.invoke('nua:print-html', html),
  saveFile: (filename, data) => ipcRenderer.invoke('nua:save-file', filename, data),
  getToken: () => ipcRenderer.invoke('nua:token-get'),
  setToken: value => ipcRenderer.invoke('nua:token-set', value),
  clearToken: () => ipcRenderer.invoke('nua:token-clear'),
  getDeviceMap: () => ipcRenderer.invoke('nua:device-map-get'),
  setDeviceMap: value => ipcRenderer.invoke('nua:device-map-set', value),
  getDeviceId: () => ipcRenderer.invoke('nua:device-id-get'),
  setDeviceId: value => ipcRenderer.invoke('nua:device-id-set', value),
}));
