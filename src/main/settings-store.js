const { safeStorage } = require('electron');

function isEncryptionAvailable() {
  try {
    return safeStorage.isEncryptionAvailable();
  } catch {
    return false;
  }
}

function encryptApiKey(plainText) {
  if (!plainText) {
    return { ok: true, encrypted: '' };
  }
  if (!isEncryptionAvailable()) {
    return { ok: false, reason: 'encryption_unavailable' };
  }
  try {
    const buffer = safeStorage.encryptString(plainText);
    return { ok: true, encrypted: buffer.toString('base64') };
  } catch (err) {
    return { ok: false, reason: 'encrypt_failed', message: err.message };
  }
}

function decryptApiKey(base64) {
  if (!base64) {
    return { ok: true, plainText: '' };
  }
  if (!isEncryptionAvailable()) {
    return { ok: false, reason: 'encryption_unavailable' };
  }
  try {
    const buffer = Buffer.from(base64, 'base64');
    const plainText = safeStorage.decryptString(buffer);
    return { ok: true, plainText };
  } catch (err) {
    return { ok: false, reason: 'decrypt_failed', message: err.message };
  }
}

function registerSettingsStoreIpc(ipcMain) {
  ipcMain.handle('settings-store:is-encryption-available', () => isEncryptionAvailable());
  ipcMain.handle('settings-store:encrypt-api-key', (_event, plainText) => encryptApiKey(plainText));
  ipcMain.handle('settings-store:decrypt-api-key', (_event, base64) => decryptApiKey(base64));
}

module.exports = {
  registerSettingsStoreIpc,
  isEncryptionAvailable,
  encryptApiKey,
  decryptApiKey,
};
