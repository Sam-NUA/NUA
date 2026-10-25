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
  getWindowState: () => ipcRenderer.invoke('nua:window-state'),
  onWindowStateChanged: callback => {
    if (typeof callback !== 'function') throw new TypeError('Callback required');
    const listener = (_event, state) => callback({ fullscreen: !!state.fullscreen, maximized: !!state.maximized, minimized: !!state.minimized });
    ipcRenderer.on('nua:window-state-changed', listener);
    return () => ipcRenderer.removeListener('nua:window-state-changed', listener);
  },
  listPrinters: () => ipcRenderer.invoke('nua:printers'),
  sendFleetJob: request => ipcRenderer.invoke('nua:fleet-send', request),
  printReceipt: (receipt, printerName = '') => ipcRenderer.invoke('nua:print-receipt', receipt, printerName),
  printHtml: (html, printerName = '') => ipcRenderer.invoke('nua:print-html', html, printerName),
  saveFile: (filename, data) => ipcRenderer.invoke('nua:save-file', filename, data),
  getToken: () => ipcRenderer.invoke('nua:token-get'),
  setToken: value => ipcRenderer.invoke('nua:token-set', value),
  clearToken: () => ipcRenderer.invoke('nua:token-clear'),
  getDeviceMap: () => ipcRenderer.invoke('nua:device-map-get'),
  setDeviceMap: value => ipcRenderer.invoke('nua:device-map-set', value),
  getDeviceId: () => ipcRenderer.invoke('nua:device-id-get'),
  setDeviceId: value => ipcRenderer.invoke('nua:device-id-set', value),
}));
