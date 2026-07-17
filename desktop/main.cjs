const { app, BrowserWindow, dialog, shell, ipcMain, net } = require('electron')
const { spawn, spawnSync } = require('node:child_process')
const fs = require('node:fs')
const http = require('node:http')
const path = require('node:path')
const {
  backendTerminationPlan,
  backendUrl,
  frontendLoadOptions,
  isTrustedNavigation,
  isTrustedTronClassUrl,
  resolveChatCompletionEndpoint,
  withApiBase,
} = require('./runtime-utils.cjs')

const BACKEND_PORT = 8765
const BACKEND_URL = backendUrl(BACKEND_PORT)
const HEALTH_URL = `http://127.0.0.1:${BACKEND_PORT}/api/health`
const isDevelopment = !app.isPackaged
let mainWindow = null
let backendProcess = null
let backendOwnedByApp = false
let backendLogStream = null
let tronClassWindow = null
let tronClassConfig = null
let tronClassRunning = false

const localRoot = path.resolve(
  process.env.JIAYUAN_DESKTOP_ROOT
    || path.join(process.env.LOCALAPPDATA || app.getPath('appData'), 'JiaYuan'),
)
const profileDir = path.join(localRoot, 'profile')
const logsDir = path.join(localRoot, 'logs')
fs.mkdirSync(profileDir, { recursive: true })
fs.mkdirSync(logsDir, { recursive: true })
app.setPath('userData', profileDir)
app.setAppLogsPath(logsDir)


function desktopLog(message) {
  fs.appendFileSync(
    path.join(logsDir, 'electron.log'),
    `[${new Date().toISOString()}] ${message}\n`,
    'utf8',
  )
}


function appendLog(message) {
  if (!backendLogStream) return
  backendLogStream.write(`[${new Date().toISOString()}] ${message}\n`)
}


function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 1080,
    minHeight: 700,
    show: false,
    backgroundColor: '#07101f',
    title: 'JiaYuan',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  })
  mainWindow.removeMenu()
  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) {
      shell.openExternal(url)
    }
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, url) => {
    if (!isTrustedNavigation(url, process.env.JIAYUAN_DEV_SERVER_URL)) {
      event.preventDefault()
      if (/^https?:\/\//i.test(url)) shell.openExternal(url)
    }
  })
  return mainWindow
}

ipcMain.handle('jiayuan:export-pdf', async (_event, payload = {}) => {
  const title = String(payload.title || 'JiaYuan 对话').replace(/[\\/:*?"<>|]/g, '_').slice(0, 100)
  const target = await dialog.showSaveDialog(mainWindow, {
    title: '导出对话为 PDF',
    defaultPath: `${title}.pdf`,
    filters: [{ name: 'PDF', extensions: ['pdf'] }],
  })
  if (target.canceled || !target.filePath) return { canceled: true }
  const printWindow = new BrowserWindow({ show: false, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } })
  try {
    await printWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(String(payload.html || ''))}`)
    const pdf = await printWindow.webContents.printToPDF({ printBackground: true, pageSize: 'A4', margins: { top: 0.5, bottom: 0.5, left: 0.55, right: 0.55 } })
    fs.writeFileSync(target.filePath, pdf)
    return { canceled: false, path: target.filePath }
  } finally {
    printWindow.destroy()
  }
})

function sendTronClassStatus(status = {}) {
  if (!mainWindow || mainWindow.isDestroyed()) return
  mainWindow.webContents.send('tronclass:status-changed', {
    open: Boolean(tronClassWindow && !tronClassWindow.isDestroyed()),
    running: tronClassRunning,
    ...status,
  })
}

function openTronClassWindow(config = {}) {
  tronClassConfig = { ...config }
  if (tronClassWindow && !tronClassWindow.isDestroyed()) {
    tronClassWindow.webContents.send('tronclass:configure', tronClassConfig)
    tronClassWindow.show()
    tronClassWindow.focus()
    return tronClassWindow
  }
  tronClassWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 960,
    minHeight: 640,
    show: false,
    title: 'XMU_TronClass · JiaYuan',
    webPreferences: {
      preload: path.join(__dirname, 'tronclass-preload.cjs'),
      partition: 'persist:jiayuan-tronclass',
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  })
  tronClassWindow.removeMenu()
  tronClassWindow.once('ready-to-show', () => tronClassWindow?.show())
  tronClassWindow.webContents.on('did-finish-load', () => {
    tronClassWindow?.webContents.send('tronclass:configure', tronClassConfig || {})
    sendTronClassStatus({ url: tronClassWindow?.webContents.getURL() || '' })
  })
  tronClassWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isTrustedTronClassUrl(url)) return { action: 'allow' }
    if (/^https?:\/\//i.test(url)) shell.openExternal(url)
    return { action: 'deny' }
  })
  tronClassWindow.webContents.on('will-navigate', (event, url) => {
    if (!isTrustedTronClassUrl(url)) {
      event.preventDefault()
      if (/^https?:\/\//i.test(url)) shell.openExternal(url)
    }
  })
  tronClassWindow.on('closed', () => {
    tronClassWindow = null
    tronClassRunning = false
    sendTronClassStatus({ open: false, running: false })
  })
  tronClassWindow.loadURL('https://lnt.xmu.edu.cn/')
  sendTronClassStatus({ open: true, running: false, url: 'https://lnt.xmu.edu.cn/' })
  return tronClassWindow
}

ipcMain.handle('tronclass:open', (_event, config = {}) => {
  openTronClassWindow(config)
  return { open: true }
})

ipcMain.handle('tronclass:close', () => {
  tronClassWindow?.close()
  return { open: false }
})

ipcMain.handle('tronclass:status', () => ({
  open: Boolean(tronClassWindow && !tronClassWindow.isDestroyed()),
  running: tronClassRunning,
  url: tronClassWindow && !tronClassWindow.isDestroyed() ? tronClassWindow.webContents.getURL() : '',
}))

ipcMain.handle('tronclass:command', (_event, payload = {}) => {
  if (!tronClassWindow || tronClassWindow.isDestroyed()) throw new Error('请先打开 TronClass 窗口')
  tronClassConfig = { ...(tronClassConfig || {}), ...(payload.config || {}) }
  tronClassWindow.webContents.send('tronclass:command', String(payload.command || ''), tronClassConfig)
  tronClassWindow.show()
  return { sent: true }
})

ipcMain.on('tronclass:solver-log', (event, message) => {
  if (!tronClassWindow || event.sender !== tronClassWindow.webContents) return
  mainWindow?.webContents.send('tronclass:log', String(message).slice(0, 2000))
})

ipcMain.on('tronclass:solver-status', (event, status = {}) => {
  if (!tronClassWindow || event.sender !== tronClassWindow.webContents) return
  tronClassRunning = Boolean(status.running)
  sendTronClassStatus({ ...status, open: true })
})

ipcMain.handle('tronclass:complete', async (event, payload = {}) => {
  if (!tronClassWindow || event.sender !== tronClassWindow.webContents) throw new Error('非法的模型请求来源')
  const model = payload.config || {}
  const base = String(model.baseUrl || '').trim().replace(/\/+$/, '')
  let endpoint
  try { endpoint = resolveChatCompletionEndpoint(base) }
  catch (error) { throw new Error(error.message.includes('HTTPS') ? '远程模型接口必须使用 HTTPS' : '模型 Base URL 格式不正确') }
  if (!model.apiKey || !model.modelId) throw new Error('模型密钥或模型 ID 为空')
  const messages = Array.isArray(payload.messages) ? payload.messages.slice(-20).map(item => ({
    role: item.role === 'assistant' ? 'assistant' : 'user',
    content: String(item.content || '').slice(0, 30000),
  })) : []
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 60000)
  try {
    const response = await net.fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${model.apiKey}` },
      body: JSON.stringify({
        model: model.modelId,
        messages: [
          { role: 'system', content: '你是课程练习辅助工具。分析选择题或判断题，并在末尾严格使用 <answer>答案</answer> 输出，例如 <answer>A</answer>、<answer>BC</answer> 或 <answer>对</answer>。' },
          ...messages,
        ],
        temperature: 0.1,
      }),
      signal: controller.signal,
    })
    const text = await response.text()
    if (!response.ok) {
      let detail = text.slice(0, 500)
      try {
        const parsed = JSON.parse(text)
        const errorPayload = Array.isArray(parsed) ? parsed[0]?.error : parsed?.error
        detail = String(errorPayload?.message || errorPayload || detail)
      } catch { /* 使用原始响应摘要 */ }
      const guidance = response.status === 401
        ? '当前 API Key 无效，或绑定的服务账号已被删除/禁用。请在 Settings 更换密钥或重新启用服务账号。'
        : response.status === 403
          ? '当前 API Key 没有调用该模型的权限，请检查模型权限与账单状态。'
          : response.status === 429
            ? '请求额度或频率已达到上限，请稍后重试或更换模型。'
            : '请检查模型地址、模型 ID 和服务状态。'
      return { error: `模型接口 HTTP ${response.status}：${detail} ${guidance}`, status: response.status }
    }
    const data = JSON.parse(text)
    return { content: String(data?.choices?.[0]?.message?.content || '') }
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('模型请求超过 60 秒')
    throw error
  } finally { clearTimeout(timeout) }
})


async function showSplash(status) {
  const splashPath = path.join(__dirname, 'splash.html')
  await mainWindow.loadFile(splashPath)
  await updateSplash(status)
}


async function updateSplash(status) {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const safeStatus = JSON.stringify(String(status))
  await mainWindow.webContents.executeJavaScript(
    `document.getElementById('status').textContent = ${safeStatus}`,
    true,
  ).catch(() => {})
}


function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, ''))
  } catch {
    return null
  }
}


function preparePrivatePython() {
  desktopLog('preparePrivatePython: begin')
  if (isDevelopment) {
    const configured = process.env.JIAYUAN_PYTHON
    if (configured && fs.existsSync(configured)) return configured
    return 'python'
  }

  const templateRoot = path.join(process.resourcesPath, 'runtime')
  const runtimeArchive = path.join(templateRoot, 'python-runtime.tar')
  const templateManifest = readJson(path.join(templateRoot, 'runtime-manifest.json'))
  if (!templateManifest?.runtimeVersion || !fs.existsSync(runtimeArchive)) {
    throw new Error('安装包缺少有效的私有 Python 运行时。')
  }

  const runtimeRoot = path.join(localRoot, 'runtime')
  const targetPython = path.join(runtimeRoot, 'python')
  const targetManifestPath = path.join(runtimeRoot, 'runtime-manifest.json')
  const currentManifest = readJson(targetManifestPath)
  const needsRefresh = (
    currentManifest?.runtimeVersion !== templateManifest.runtimeVersion
    || !fs.existsSync(path.join(targetPython, 'python.exe'))
  )

  if (needsRefresh) {
    fs.rmSync(runtimeRoot, { recursive: true, force: true })
    fs.mkdirSync(runtimeRoot, { recursive: true })
    const extractResult = spawnSync('tar.exe', ['-x', '-f', runtimeArchive, '-C', runtimeRoot], {
      windowsHide: true,
      encoding: 'utf8',
    })
    if (extractResult.status !== 0 || !fs.existsSync(path.join(runtimeRoot, 'python', 'python.exe'))) {
      throw new Error(`私有 Python 运行时解压失败：${extractResult.stderr || extractResult.status}`)
    }
    fs.writeFileSync(
      targetManifestPath,
      JSON.stringify(templateManifest, null, 2),
      'utf8',
    )
  }
  desktopLog(`preparePrivatePython: ready refresh=${needsRefresh}`)
  return path.join(targetPython, 'python.exe')
}


function prepareSeedModels() {
  desktopLog('prepareSeedModels: begin')
  if (isDevelopment) return
  const modelsArchive = path.join(process.resourcesPath, 'runtime', 'models-runtime.tar')
  if (!fs.existsSync(modelsArchive)) {
    throw new Error('安装包缺少基础向量模型。')
  }
  const targetModels = path.join(localRoot, 'models')
  const expectedModel = path.join(targetModels, 'huggingface', 'hub', 'models--BAAI--bge-small-zh-v1.5')
  if (fs.existsSync(expectedModel)) {
    desktopLog('prepareSeedModels: already ready')
    return
  }
  fs.mkdirSync(targetModels, { recursive: true })
  const extractResult = spawnSync('tar.exe', ['-x', '-f', modelsArchive, '-C', targetModels], {
    windowsHide: true,
    encoding: 'utf8',
  })
  if (extractResult.status !== 0 || !fs.existsSync(expectedModel)) {
    throw new Error(`基础向量模型解压失败：${extractResult.stderr || extractResult.status}`)
  }
  desktopLog('prepareSeedModels: ready')
}


function requestHealth(timeoutMs = 1500) {
  return new Promise((resolve) => {
    const request = http.get(HEALTH_URL, { timeout: timeoutMs }, (response) => {
      let body = ''
      response.setEncoding('utf8')
      response.on('data', (chunk) => { body += chunk })
      response.on('end', () => {
        try {
          const data = JSON.parse(body)
          resolve(response.statusCode === 200 && data.app === 'jiayuan' ? data : null)
        } catch {
          resolve(null)
        }
      })
    })
    request.on('timeout', () => { request.destroy(); resolve(null) })
    request.on('error', () => resolve(null))
  })
}


async function waitForBackend(timeoutMs = 5 * 60 * 1000) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    const health = await requestHealth()
    if (health) return health
    if (backendProcess && backendProcess.exitCode !== null) {
      throw new Error(`后端提前退出，返回码 ${backendProcess.exitCode}。请查看 ${path.join(localRoot, 'logs', 'backend.log')}`)
    }
    const elapsed = Math.round((Date.now() - started) / 1000)
    await updateSplash(`正在加载本地后端与向量模型… 已等待 ${elapsed} 秒`)
    await new Promise((resolve) => setTimeout(resolve, 1500))
  }
  throw new Error(`后端在 ${Math.round(timeoutMs / 1000)} 秒内未就绪。`)
}


function startBackend(pythonExecutable) {
  desktopLog(`startBackend: python=${pythonExecutable}`)
  const backendDir = isDevelopment
    ? path.resolve(__dirname, '..', 'backend')
    : path.join(process.resourcesPath, 'backend')
  const dataDir = path.join(localRoot, 'data')
  const modelDir = path.join(localRoot, 'models')
  fs.mkdirSync(dataDir, { recursive: true })
  fs.mkdirSync(modelDir, { recursive: true })
  fs.mkdirSync(logsDir, { recursive: true })
  backendLogStream = fs.createWriteStream(path.join(logsDir, 'backend.log'), { flags: 'a' })

  backendProcess = spawn(pythonExecutable, ['-u', path.join(backendDir, 'main.py')], {
    cwd: backendDir,
    windowsHide: true,
    env: {
      ...process.env,
      JIAYUAN_DATA_DIR: dataDir,
      JIAYUAN_MODEL_DIR: modelDir,
      JIAYUAN_RELOAD: '0',
      JIAYUAN_PORT: String(BACKEND_PORT),
      HF_HOME: path.join(modelDir, 'huggingface'),
      RAG_EMBEDDING_LOCAL_FILES_ONLY: '1',
      HF_HUB_OFFLINE: '1',
      TRANSFORMERS_OFFLINE: '1',
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
      PYTHONDONTWRITEBYTECODE: '1',
    },
  })
  backendOwnedByApp = true
  backendProcess.stdout.on('data', (data) => appendLog(`[stdout] ${data.toString().trimEnd()}`))
  backendProcess.stderr.on('data', (data) => appendLog(`[stderr] ${data.toString().trimEnd()}`))
  backendProcess.on('error', (error) => appendLog(`[spawn-error] ${error.stack || error}`))
  backendProcess.on('exit', (code, signal) => appendLog(`[exit] code=${code} signal=${signal}`))
}


function stopBackend() {
  if (!backendOwnedByApp || !backendProcess || backendProcess.exitCode !== null) return
  const plan = backendTerminationPlan(process.platform, backendProcess.pid)
  if (plan.command) {
    spawnSync(plan.command, plan.args, {
      windowsHide: true,
      stdio: 'ignore',
    })
  } else {
    backendProcess.kill('SIGTERM')
  }
  backendLogStream?.end()
}


async function launch() {
  desktopLog('launch: begin')
  createWindow()
  await showSplash('正在检查本地运行环境…')
  desktopLog('launch: splash ready')

  const existing = await requestHealth()
  if (!existing) {
    await updateSplash('首次启动：正在准备应用私有 Python 运行时…')
    const pythonExecutable = preparePrivatePython()
    await updateSplash('首次启动：正在准备基础向量模型…')
    prepareSeedModels()
    await updateSplash('正在启动本地后端…')
    startBackend(pythonExecutable)
  }
  await waitForBackend()
  desktopLog('launch: backend ready')

  if (isDevelopment && process.env.JIAYUAN_DEV_SERVER_URL) {
    await mainWindow.loadURL(withApiBase(process.env.JIAYUAN_DEV_SERVER_URL, BACKEND_URL))
  } else {
    const frontendPath = isDevelopment
      ? path.resolve(__dirname, '..', 'frontend', 'dist', 'index.html')
      : path.join(process.resourcesPath, 'frontend', 'index.html')
    await mainWindow.loadFile(frontendPath, frontendLoadOptions(BACKEND_URL))
  }
}


const gotSingleInstanceLock = app.requestSingleInstanceLock()
if (!gotSingleInstanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })
  app.whenReady().then(launch).catch((error) => {
    desktopLog(`[fatal] ${error.stack || error}`)
    appendLog(`[fatal] ${error.stack || error}`)
    dialog.showErrorBox('JiaYuan 启动失败', String(error.message || error))
    app.quit()
  })
}

app.on('before-quit', stopBackend)
app.on('window-all-closed', () => app.quit())
