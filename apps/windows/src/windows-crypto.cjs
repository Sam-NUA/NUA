'use strict';
// Electron 44 pinned API; no plaintext or non-Windows fallback.
function windowsCrypto(safeStorage, platform = process.platform) {
  function check() {
    if (platform !== 'win32' || !safeStorage.isEncryptionAvailable()) throw new Error('Windows OS encryption unavailable');
  }
  return {
    encryptString(value) { check(); return safeStorage.encryptString(value); },
    decryptString(value) { check(); return safeStorage.decryptString(value); },
  };
}
module.exports = { windowsCrypto };
