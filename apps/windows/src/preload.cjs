'use strict';
const { contextBridge, ipcRenderer } = require('electron');
// Explicit methods only: never expose send/invoke, Node, paths, or arbitrary URLs.
contextBridge.exposeInMainWorld('nuaDesktop', Object.freeze({
  getInfo: () => ipcRenderer.invoke('nua:info'),
  setFullscreen: value => ipcRenderer.invoke('nua:fullscreen', value),
  listPrinters: () => ipcRenderer.invoke('nua:printers'),
  printReceipt: receipt => ipcRenderer.invoke('nua:print-receipt', receipt),
}));
