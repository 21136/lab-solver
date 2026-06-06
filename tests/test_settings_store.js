/**
 * Unit tests for settings-store IPC helpers (mocked safeStorage).
 *
 * Usage: node tests/test_settings_store.js
 */

const assert = require('assert');
const crypto = require('crypto');

const mockSafeStorage = {
  isEncryptionAvailable: () => true,
  encryptString(plainText) {
    const key = crypto.scryptSync('test-key', 'salt', 32);
    const iv = crypto.randomBytes(16);
    const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
    const enc = Buffer.concat([cipher.update(plainText, 'utf8'), cipher.final()]);
    const tag = cipher.getAuthTag();
    return Buffer.concat([iv, tag, enc]);
  },
  decryptString(buffer) {
    const key = crypto.scryptSync('test-key', 'salt', 32);
    const iv = buffer.subarray(0, 16);
    const tag = buffer.subarray(16, 32);
    const data = buffer.subarray(32);
    const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
    decipher.setAuthTag(tag);
    return Buffer.concat([decipher.update(data), decipher.final()]).toString('utf8');
  },
};

require('module').Module._cache[require.resolve('electron')] = {
  exports: { safeStorage: mockSafeStorage },
};

const { encryptApiKey, decryptApiKey, isEncryptionAvailable } = require('../src/main/settings-store');

function testRoundTrip() {
  assert.strictEqual(isEncryptionAvailable(), true);
  const plain = 'sk-test-migration-key';
  const enc = encryptApiKey(plain);
  assert.strictEqual(enc.ok, true);
  assert.ok(enc.encrypted);
  const dec = decryptApiKey(enc.encrypted);
  assert.strictEqual(dec.ok, true);
  assert.strictEqual(dec.plainText, plain);
}

function testEmptyKey() {
  assert.deepStrictEqual(encryptApiKey(''), { ok: true, encrypted: '' });
  assert.deepStrictEqual(decryptApiKey(''), { ok: true, plainText: '' });
}

function testUnavailable() {
  mockSafeStorage.isEncryptionAvailable = () => false;
  const result = encryptApiKey('sk-x');
  assert.strictEqual(result.ok, false);
  assert.strictEqual(result.reason, 'encryption_unavailable');
  mockSafeStorage.isEncryptionAvailable = () => true;
}

testRoundTrip();
testEmptyKey();
testUnavailable();
console.log('test_settings_store: OK');
