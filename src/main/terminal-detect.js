/**
 * 一键采集终端环境：读取 Cursor / VS Code 设置与本机环境
 */
const fs = require('fs');
const path = require('path');
const os = require('os');

const PROFILE_MAP = {
  powershell: 'win_powershell',
  'command prompt': 'win_cmd',
  'cmd': 'win_cmd',
  'git bash': 'win_gitbash',
  bash: 'win_gitbash',
  zsh: 'mac_zsh',
  'javascript debug terminal': 'win_powershell',
};

function readJsonSafe(filePath) {
  try {
    if (!fs.existsSync(filePath)) return null;
    const raw = fs.readFileSync(filePath, 'utf-8');
    // VS Code settings.json 允许注释，简单去掉 // 行
    const stripped = raw.replace(/\/\/.*$/gm, '').replace(/,\s*}/g, '}');
    return JSON.parse(stripped);
  } catch {
    return null;
  }
}

function mapProfileName(name) {
  if (!name) return '';
  const key = String(name).toLowerCase().trim();
  if (PROFILE_MAP[key]) return PROFILE_MAP[key];
  if (key.includes('power')) return 'win_powershell';
  if (key.includes('git') || key.includes('bash') || key.includes('mingw')) return 'win_gitbash';
  if (key.includes('cmd') || key.includes('command')) return 'win_cmd';
  if (key.includes('zsh')) return 'mac_zsh';
  return '';
}

function resolveCwdSetting(value, workspaceFolder) {
  if (!value || typeof value !== 'string') return '';
  let v = value.trim();
  if (v.includes('${workspaceFolder}') && workspaceFolder) {
    v = v.replace(/\$\{workspaceFolder\}/g, workspaceFolder);
  }
  if (v.includes('${userHome}')) {
    v = v.replace(/\$\{userHome\}/g, os.homedir());
  }
  if (/^[a-zA-Z]:\\/.test(v) || v.startsWith('/') || v.startsWith('~')) {
    return path.normalize(v.replace(/^~/, os.homedir()));
  }
  return '';
}

function findEditorSettings() {
  const appData = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
  const candidates = [
    { editor: 'Cursor', path: path.join(appData, 'Cursor', 'User', 'settings.json') },
    { editor: 'VS Code', path: path.join(appData, 'Code', 'User', 'settings.json') },
  ];
  for (const c of candidates) {
    const data = readJsonSafe(c.path);
    if (data) return { editor: c.editor, settings: data, path: c.path };
  }
  return null;
}

function guessWorkspaceFolder(currentFilePath) {
  if (currentFilePath && fs.existsSync(path.dirname(currentFilePath))) {
    return path.dirname(currentFilePath);
  }
  const desktop = path.join(os.homedir(), 'Desktop');
  if (fs.existsSync(desktop)) return desktop;
  return os.homedir();
}

function detectFromEnv(platform) {
  const comspec = (process.env.ComSpec || '').toLowerCase();
  const shell = (process.env.SHELL || '').toLowerCase();
  if (platform === 'darwin') {
    if (shell.includes('zsh')) return 'mac_zsh';
    if (shell.includes('bash')) return 'mac_bash';
    return 'mac_zsh';
  }
  if (process.env.PSModulePath || comspec.includes('powershell')) return 'win_powershell';
  if (comspec.includes('cmd.exe')) return 'win_cmd';
  if (process.env.MSYSTEM || process.env.MINGW_PREFIX) return 'win_gitbash';
  return 'win_powershell';
}

function detectTerminalEnv(currentFilePath = '') {
  const platform = process.platform;
  const workspace = guessWorkspaceFolder(currentFilePath);
  const sources = [];

  let profile = '';
  let cwd = '';
  let chrome = platform === 'darwin' ? 'mac' : 'windows';

  const editorInfo = findEditorSettings();
  if (editorInfo) {
    sources.push(editorInfo.editor);
    const s = editorInfo.settings;
    const profileKey = platform === 'darwin'
      ? 'terminal.integrated.defaultProfile.osx'
      : platform === 'win32'
        ? 'terminal.integrated.defaultProfile.windows'
        : 'terminal.integrated.defaultProfile.linux';

    const profileName = s[profileKey] || s['terminal.integrated.defaultProfile.windows'];
    profile = mapProfileName(profileName);

    cwd = resolveCwdSetting(s['terminal.integrated.cwd'], workspace);

    if (s['terminal.integrated.defaultProfile.windows'] && platform === 'win32') {
      chrome = 'windows';
    }
  }

  if (!profile) {
    profile = detectFromEnv(platform);
    sources.push('系统环境');
  }

  if (!cwd) {
    cwd = workspace;
    sources.push('工作目录推测');
  }

  return {
    success: true,
    terminal_profile: profile,
    terminal_cwd: cwd,
    chrome_style: chrome,
    editor: editorInfo?.editor || null,
    sources: sources.join(' + '),
    message: `已采集：${profile}，目录 ${cwd}${editorInfo ? `（来自 ${editorInfo.editor}）` : ''}`,
  };
}

module.exports = { detectTerminalEnv };
