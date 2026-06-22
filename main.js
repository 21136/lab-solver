const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const { spawn, execSync } = require('child_process');
const http = require('http');
const fs = require('fs');
const { detectTerminalEnv } = require('./src/main/terminal-detect');
const { registerSettingsStoreIpc } = require('./src/main/settings-store');

let mainWindow;
let pythonProcess;
let pythonPid = null;
const PYTHON_PORT = 5199;
let serverReady = false;
let serverStartError = '';

function killPythonTree(pid) {
  if (!pid) return;
  try {
    if (process.platform === 'win32') {
      execSync(`taskkill /F /T /PID ${pid}`, { timeout: 5000, stdio: 'ignore' });
    } else {
      process.kill(-pid, 'SIGKILL');
    }
  } catch (e) {
    // Process may already be dead — ignore
  }
}

function killAllPythonOnPort(port) {
  // Kill any lingering process on the given port (stale from a previous crash).
  try {
    if (process.platform === 'win32') {
      const out = execSync(`netstat -ano | findstr ":${port}" | findstr "LISTENING"`, {
        timeout: 3000, encoding: 'utf8',
      });
      const lines = out.trim().split(/\r?\n/).filter(Boolean);
      const killed = new Set();
      for (const line of lines) {
        const parts = line.trim().split(/\s+/);
        const pid = parts[parts.length - 1];
        if (pid && !killed.has(pid) && pid !== String(pythonPid)) {
          killed.add(pid);
          try {
            execSync(`taskkill /F /PID ${pid}`, { timeout: 3000, stdio: 'ignore' });
            console.log(`[cleanup] killed stale process on port ${port}: PID ${pid}`);
          } catch (_) {}
        }
      }
    } else {
      execSync(`lsof -ti :${port} | xargs kill -9 2>/dev/null`, { timeout: 3000, stdio: 'ignore' });
    }
  } catch (_) {
    // No matching processes or netstat not available — fine
  }
}

function cleanupPython() {
  if (pythonPid) {
    killPythonTree(pythonPid);
    pythonPid = null;
  }
  pythonProcess = null;
  serverReady = false;
  // Belt and suspenders: also kill anything left on the port
  killAllPythonOnPort(PYTHON_PORT);
}

function getPythonPath() {
  if (app.isPackaged) {
    // 打包后，使用打包的Python环境
    const embeddedPython = path.join(process.resourcesPath, 'python-dist', 'server', 'server.exe');
    if (fs.existsSync(embeddedPython)) return embeddedPython;
    // 备用：系统Python
    return process.env.PYTHON || 'python';
  }
  // start.bat 会写入 PYTHON=python.exe 绝对路径，避免仅安装 py 启动器时找不到解释器
  const fromEnv = (process.env.PYTHON || '').trim();
  if (fromEnv && fs.existsSync(fromEnv)) return fromEnv;
  return 'python';
}

function getServerScript() {
  if (app.isPackaged) {
    const embeddedExe = path.join(process.resourcesPath, 'python-dist', 'server', 'server.exe');
    if (fs.existsSync(embeddedExe)) return null; // 使用exe模式
    return path.join(process.resourcesPath, 'python', 'server.py');
  }
  return path.join(__dirname, 'src', 'python', 'server.py');
}

function startPythonServer() {
  return new Promise((resolve, reject) => {
    const serverScript = getServerScript();
    const pythonPath = getPythonPath();

    let args, cmd;
    if (serverScript) {
      cmd = pythonPath;
      args = [serverScript, '--port', String(PYTHON_PORT)];
    } else {
      cmd = path.join(process.resourcesPath, 'python-dist', 'server', 'server.exe');
      args = ['--port', String(PYTHON_PORT)];
    }

    console.log(`启动Python服务: ${cmd} ${args.join(' ')}`);

    // Kill stale processes from a previous crash before spawning a new one
    killAllPythonOnPort(PYTHON_PORT);

    pythonProcess = spawn(cmd, args, {
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      detached: false,
    });
    pythonPid = pythonProcess.pid;
    console.log(`Python PID: ${pythonPid}`);

    pythonProcess.stdout.on('data', (data) => {
      const msg = data.toString();
      console.log('[Python]', msg);
      if (msg.includes('Running on') || msg.includes('started')) {
        resolve();
      }
    });

    pythonProcess.stderr.on('data', (data) => {
      const msg = data.toString();
      console.error('[Python Error]', msg);
      if (msg.includes('Running on') || msg.includes('Serving Flask')) {
        resolve();
      }
    });

    pythonProcess.on('error', (err) => {
      console.error('Python进程启动失败:', err);
      reject(err);
    });

    // 3秒后假定启动成功（防止某些情况下没有输出）
    setTimeout(resolve, 3000);
  });
}

function waitForServer(retries = 20) {
  return new Promise((resolve, reject) => {
    const attempt = () => {
      http.get(`http://localhost:${PYTHON_PORT}/api/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else {
          retry();
        }
      }).on('error', () => {
        retry();
      });
    };

    const retry = () => {
      if (retries-- > 0) {
        setTimeout(attempt, 500);
      } else {
        reject(new Error('Python服务器启动超时'));
      }
    };

    attempt();
  });
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    frame: false,
    backgroundColor: '#0f1117',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    icon: path.join(__dirname, 'assets', 'icon.ico'),
    show: false,
    titleBarStyle: 'hidden',
  });

  mainWindow.loadFile(path.join(__dirname, 'src', 'renderer', 'index.html'));

  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
  });

  if (process.argv.includes('--dev')) {
    mainWindow.webContents.openDevTools();
  }

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

registerSettingsStoreIpc(ipcMain);

// IPC: 窗口控制
ipcMain.on('window-minimize', () => mainWindow?.minimize());
ipcMain.on('window-maximize', () => {
  if (mainWindow?.isMaximized()) mainWindow.unmaximize();
  else mainWindow?.maximize();
});
ipcMain.on('window-close', () => mainWindow?.close());

// IPC: 打开文件对话框
ipcMain.handle('open-file-dialog', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [
      { name: '实验报告 (.doc / .docx / .pdf)', extensions: ['doc', 'docx', 'pdf'] },
      { name: 'Word 文档 (.doc / .docx)', extensions: ['doc', 'docx'] },
      { name: 'PDF 文档 (.pdf)', extensions: ['pdf'] },
      { name: '所有文件', extensions: ['*'] }
    ]
  });
  return result;
});

ipcMain.handle('open-docx-dialog', async () => {
  return dialog.showOpenDialog(mainWindow, {
    properties: ['openFile'],
    filters: [
      { name: 'Word 文档 (.docx)', extensions: ['docx'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  });
});

ipcMain.handle('open-image-dialog', async () => {
  return dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    filters: [
      { name: '图片 (.png / .jpg / .webp)', extensions: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tif', 'tiff'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  });
});

// IPC: 保存文件对话框
ipcMain.handle('save-file-dialog', async (event, defaultName, filters) => {
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: defaultName || '实验报告_已完成.docx',
    filters: filters || [
      { name: 'Word文档', extensions: ['docx'] }
    ]
  });
  return result;
});

// IPC: 写入二进制（base64）
ipcMain.handle('write-file-base64', async (event, filePath, b64) => {
  const buf = Buffer.from(b64 || '', 'base64');
  fs.writeFileSync(filePath, buf);
  return { ok: true };
});

// IPC: 写入文本
ipcMain.handle('write-file-text', async (event, filePath, content) => {
  fs.writeFileSync(filePath, content || '', 'utf8');
  return { ok: true };
});

// IPC: 保存思考过程文本（另存为对话框）
ipcMain.handle('save-text-dialog', async (event, defaultName, content) => {
  const result = await dialog.showSaveDialog(mainWindow, {
    defaultPath: defaultName || '思考过程.txt',
    filters: [
      { name: '文本文件', extensions: ['txt'] },
      { name: '所有文件', extensions: ['*'] },
    ],
  });
  if (result.canceled || !result.filePath) {
    return { canceled: true };
  }
  fs.writeFileSync(result.filePath, content || '', 'utf8');
  return { canceled: false, filePath: result.filePath };
});

// IPC: 自动写入思考过程到用户数据目录 thought_logs/
ipcMain.handle('write-thought-log', async (event, fileName, content) => {
  const dir = path.join(app.getPath('userData'), 'thought_logs');
  fs.mkdirSync(dir, { recursive: true });
  const safeName = (fileName || `thought_${Date.now()}.txt`).replace(/[<>:"/\\|?*]/g, '_');
  const filePath = path.join(dir, safeName);
  fs.writeFileSync(filePath, content || '', 'utf8');
  return { filePath };
});

// IPC: 用默认程序打开文件
ipcMain.handle('open-file-external', async (event, filePath) => {
  await shell.openPath(filePath);
  return true;
});

// IPC: 在浏览器中打开 URL
ipcMain.handle('open-external-url', async (event, url) => {
  await shell.openExternal(url);
  return true;
});

// IPC: 获取服务状态
ipcMain.handle('get-server-port', () => PYTHON_PORT);
ipcMain.handle('get-server-status', () => ({
  ready: serverReady,
  error: serverStartError || null,
}));

// IPC: 读取文件内容（base64）
ipcMain.handle('read-file-base64', async (event, filePath) => {
  const data = fs.readFileSync(filePath);
  return data.toString('base64');
});

// IPC: 一键采集终端环境（Cursor/VS Code 设置 + 本机路径）
ipcMain.handle('detect-terminal-env', async (event, currentFilePath) => {
  try {
    return detectTerminalEnv(currentFilePath || '');
  } catch (e) {
    return { success: false, error: e.message };
  }
});

// 应用初始化
app.whenReady().then(async () => {
  console.log('启动解题能手...');

  // 先创建窗口（显示loading）
  await createWindow();

  // 启动Python后端
  try {
    await startPythonServer();
    await waitForServer();
    console.log('Python服务就绪');
    serverReady = true;
    serverStartError = '';
    mainWindow?.webContents.send('server-ready');
  } catch (err) {
    console.error('后端启动失败:', err);
    serverReady = false;
    serverStartError = (err && err.message) ? err.message : String(err);
    mainWindow?.webContents.send('server-error', err.message);
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  cleanupPython();
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('before-quit', () => {
  cleanupPython();
});

app.on('will-quit', () => {
  cleanupPython();
});

// SIGINT / SIGTERM — graceful shutdown on Ctrl+C or process manager stop
process.on('SIGINT', () => {
  cleanupPython();
  app.quit();
});
process.on('SIGTERM', () => {
  cleanupPython();
  app.quit();
});
