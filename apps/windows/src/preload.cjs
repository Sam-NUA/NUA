'use strict';
const { contextBridge, ipcRenderer } = require('electron');
// Explicit methods only: never expose send/invoke, Node, paths, or arbitrary URLs.
contextBridge.exposeInMainWorld('nuaDesktop', Object.freeze({
  getInfo: () => ipcRenderer.invoke('nua:info'),
  setFullscreen: value => ipcRenderer.invoke('nua:fullscreen', value),
  listPrinters: () => ipcRenderer.invoke('nua:printers'),
  printReceipt: receipt => ipcRenderer.invoke('nua:print-receipt', receipt),
  printHtml: html => ipcRenderer.invoke('nua:print-html', html),
  saveFile: (filename, data) => ipcRenderer.invoke('nua:save-file', filename, data),
  getToken: () => ipcRenderer.invoke('nua:token-get'),
  setToken: value => ipcRenderer.invoke('nua:token-set', value),
  clearToken: () => ipcRenderer.invoke('nua:token-clear'),
  getDeviceId: () => ipcRenderer.invoke('nua:device-id-get'),
  setDeviceId: value => ipcRenderer.invoke('nua:device-id-set', value),
}));
