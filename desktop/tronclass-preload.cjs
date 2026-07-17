const { ipcRenderer } = require('electron')

const SELECTORS = {
  containers: ['.subject', '.subject-item', '.question-card', '.quiz-question', '.problem-item', '.problem-body', '.question-item'],
  questions: ['.title', '.subject-head', '.question-desc', '.question-text', '.question-title', '.markdown-body', '.question-content .title', '.quiz-question .desc', '.problem-description'],
  options: ['.option-item', '.option', 'mat-radio-button', 'mat-checkbox', '.choice', '.choice-item', '.answer-item', '.option-card', '.mat-radio-button', '.mat-checkbox'],
  answered: 'input[type="radio"]:checked, input[type="checkbox"]:checked, .selected, .checked, .is-checked, .mat-radio-checked, .mat-checkbox-checked, .option-checked, .choice-checked',
}

let config = { delayMin: 5, delayMax: 10, autoNext: true, useHistory: false }
let running = false
let timer = null
let history = []
let busy = false
let requestEpoch = 0
let currentIndex = 0
let visibleQuestions = []

const emitLog = message => ipcRenderer.send('tronclass:solver-log', String(message))
const emitStatus = () => ipcRenderer.send('tronclass:solver-status', { open: true, running, url: location.href })
const visible = element => {
  if (!element) return false
  const rect = element.getBoundingClientRect()
  const style = getComputedStyle(element)
  return rect.width > 10 && rect.height > 10 && style.display !== 'none' && style.visibility !== 'hidden'
}

function scanQuestions() {
  for (const selector of SELECTORS.containers) {
    const found = [...document.querySelectorAll(selector)].filter(element => visible(element) && !element.closest('.answer-card, .answer-sheet, .subject-index-list, #jy-tron-helper'))
    if (found.length) return found
  }
  return []
}

function isAnswered(container) {
  return Boolean(container?.querySelector(SELECTORS.answered))
}

function extractQuestion(container) {
  const root = container || document.body
  let questionElement = null
  for (const selector of SELECTORS.questions) {
    questionElement = root.querySelector(selector)
    if (questionElement && visible(questionElement)) break
  }
  if (!questionElement) return null
  let optionElements = []
  for (const selector of SELECTORS.options) {
    optionElements = [...root.querySelectorAll(selector)].filter(visible)
    if (optionElements.length >= 2) break
  }
  const unique = optionElements.filter((element, index, all) => !all.some((other, otherIndex) => otherIndex < index && other.contains(element)))
  return {
    text: questionElement.textContent.trim().replace(/^\d+[.、\s]*/, ''),
    container: root,
    options: unique.map((element, index) => ({
      letter: String.fromCharCode(65 + index),
      text: element.textContent.trim().replace(/^[A-Z][.、]\s*/i, ''),
      element,
    })),
  }
}

function parseAnswer(value) {
  const tagged = String(value || '').match(/<answer>([\s\S]*?)<\/answer>/i)
  return String(tagged ? tagged[1] : value || '').replace(/[^A-Za-z对错]/g, '').toUpperCase()
}

function selectAnswers(answer, options) {
  const targets = []
  if (answer.includes('对') || answer.includes('错') || answer === 'TRUE' || answer === 'FALSE') {
    const wantTrue = answer.includes('对') || answer === 'TRUE'
    const match = options.find(option => wantTrue
      ? /对|正确|^true$|^t$/i.test(option.text.trim())
      : /错|错误|^false$|^f$/i.test(option.text.trim()))
    if (match) targets.push(match)
  } else {
    for (const letter of [...new Set(answer.split(''))]) {
      const match = options.find(option => option.letter === letter)
      if (match) targets.push(match)
    }
  }
  for (const option of targets) {
    const target = option.element.querySelector('input[type="radio"], input[type="checkbox"], label, .mat-radio-label, .mat-checkbox-layout') || option.element
    target.click()
    emitLog(`[选择] ${option.letter}. ${option.text.slice(0, 50)}`)
  }
  return targets.length
}

function nextButton() {
  const keywords = ['下一题', '保存并下一题', '保存并继续', '下一页']
  const candidates = [...document.querySelectorAll('button, a, .btn, .next-btn')].filter(visible)
  return candidates.find(element => keywords.some(keyword => element.textContent.trim().includes(keyword)))
    || document.querySelector('.next-question, .next-btn, .btn-next')
}

function promptFor(info) {
  const options = info.options.map(option => `${option.letter}. ${option.text}`).join('\n')
  return `请分析并解答下面的选择题或判断题。最后必须用 <answer>答案</answer> 输出答案，例如 <answer>A</answer>、<answer>BC</answer> 或 <answer>对</answer>。\n\n【题目】\n${info.text}\n\n【选项】\n${options}`
}

async function solveCurrentInternal(epoch) {
  visibleQuestions = scanQuestions()
  const multi = visibleQuestions.length > 1
  let container = multi ? visibleQuestions[currentIndex] : visibleQuestions[0]
  if (multi) {
    const unanswered = visibleQuestions.findIndex((item, index) => index >= currentIndex && !isAnswered(item))
    const wrapped = unanswered >= 0 ? unanswered : visibleQuestions.findIndex(item => !isAnswered(item))
    if (wrapped < 0) return { success: true, finished: true, multi }
    currentIndex = wrapped
    container = visibleQuestions[currentIndex]
    container.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  const info = extractQuestion(container)
  if (!info || info.options.length < 2) {
    emitLog('[错误] 没有识别到有效题目和选项，请确认已进入测验页面')
    return { success: false, finished: false, multi }
  }
  if (isAnswered(info.container)) {
    emitLog(`[跳过] 已作答：${info.text.slice(0, 40)}`)
    if (multi) currentIndex += 1
    return { success: true, finished: false, multi, skipped: true }
  }
  emitLog(`[识别] ${info.text.slice(0, 100)}`)
  info.options.forEach(option => emitLog(`  ${option.letter}. ${option.text.slice(0, 100)}`))
  const userPrompt = promptFor(info)
  const messages = config.useHistory
    ? [...history, { role: 'user', content: userPrompt }].slice(-20)
    : [{ role: 'user', content: config.context ? `【参考资料】\n${config.context}\n\n${userPrompt}` : userPrompt }]
  let response
  try {
    response = await ipcRenderer.invoke('tronclass:complete', { config, messages })
  } catch (error) {
    emitLog(`[错误] 模型请求失败：${error.message}`)
    return { success: false, finished: false, multi }
  }
  if (epoch !== requestEpoch) {
    emitLog('[系统] 本次模型结果已取消，不会选择选项')
    return { success: false, finished: false, multi, cancelled: true }
  }
  if (!response?.content) {
    emitLog(`[错误] ${response?.error || '模型没有返回答案'}`)
    return { success: false, finished: false, multi }
  }
  if (config.useHistory) history = [...messages, { role: 'assistant', content: response.content }].slice(-20)
  const answer = parseAnswer(response.content)
  emitLog(`[模型] ${response.content.slice(0, 240)}`)
  const selected = selectAnswers(answer, info.options)
  if (!selected) {
    emitLog(`[错误] 无法把模型答案“${answer}”匹配到页面选项`)
    return { success: false, finished: false, multi }
  }
  if (multi) currentIndex += 1
  return { success: true, finished: false, multi }
}

async function solveCurrent() {
  if (busy) {
    emitLog('[提示] 上一个模型请求仍在处理中，请勿重复点击')
    return { success: false, finished: false, busy: true }
  }
  busy = true
  updatePanel()
  const epoch = requestEpoch
  try { return await solveCurrentInternal(epoch) }
  finally { busy = false; updatePanel() }
}

const delayMs = skipped => {
  if (skipped) return 1000
  const min = Math.max(0, Number(config.delayMin) || 0)
  const max = Math.max(min, Number(config.delayMax) || min)
  return (min + Math.random() * (max - min)) * 1000
}

async function loop() {
  if (!running) return
  const result = await solveCurrent()
  if (!running) return
  if (!result.success || result.finished) return stop(result.finished ? '[完成] 当前页面没有未作答题目' : '[暂停] 本题处理失败')
  timer = setTimeout(() => {
    if (!running) return
    if (result.multi) return loop()
    if (!config.autoNext && !result.skipped) return stop('[暂停] 已完成本题，自动下一题已关闭')
    const button = nextButton()
    if (!button) return stop('[完成] 未找到下一题按钮；不会自动点击最终提交或交卷')
    emitLog('[页面] 正在前往下一题')
    button.click()
    timer = setTimeout(loop, 3000)
  }, delayMs(result.skipped))
}

function start() {
  if (running || busy) return emitLog('[提示] 当前题目仍在处理中，请稍候')
  if (!config?.apiKey || !config?.baseUrl || !config?.modelId) return emitLog('[错误] 请先在 JiaYuan 中选择有效模型')
  running = true
  currentIndex = 0
  updatePanel()
  emitStatus()
  emitLog('[系统] 自动答题已启动；不会自动提交或交卷')
  loop()
}

function stop(reason = '[系统] 已暂停') {
  running = false
  requestEpoch += 1
  if (timer) clearTimeout(timer)
  timer = null
  updatePanel()
  emitStatus()
  emitLog(reason)
}

async function single() {
  if (running || busy) return emitLog('[提示] 当前题目仍在处理中，请稍候')
  emitLog('[系统] 开始单步识别')
  await solveCurrent()
}

function updatePanel() {
  const button = document.getElementById('jy-tron-toggle')
  const status = document.getElementById('jy-tron-status')
  if (button) { button.textContent = running ? '暂停' : busy ? '处理中' : '开始'; button.disabled = busy }
  if (status) { status.textContent = running ? '运行中' : busy ? '处理中' : '已停止'; status.className = running || busy ? 'running' : '' }
}

function mountPanel() {
  if (!document.body || document.getElementById('jy-tron-helper')) return
  const style = document.createElement('style')
  style.textContent = `#jy-tron-helper{position:fixed;right:18px;bottom:18px;z-index:2147483647;width:260px;padding:12px;border-radius:12px;background:rgba(20,25,34,.94);color:#e5e7eb;font:13px system-ui;box-shadow:0 10px 35px #0006}#jy-tron-helper header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;font-weight:700}#jy-tron-status{font-size:11px;color:#fca5a5}#jy-tron-status.running{color:#6ee7b7}#jy-tron-helper .actions{display:flex;gap:7px}#jy-tron-helper button{flex:1;border:0;border-radius:8px;padding:8px;cursor:pointer;background:#374151;color:white}#jy-tron-helper button.primary{background:#409eff}#jy-tron-helper p{font-size:11px;color:#9ca3af;margin:9px 0 0;line-height:1.4}`
  document.head.appendChild(style)
  const panel = document.createElement('div')
  panel.id = 'jy-tron-helper'
  panel.innerHTML = '<header><span>🎓 JiaYuan TronClass</span><span id="jy-tron-status">已停止</span></header><div class="actions"><button id="jy-tron-single">单步</button><button id="jy-tron-toggle" class="primary">开始</button></div><p>仅处理选择/判断题，不会自动点击最终提交或交卷。</p>'
  document.body.appendChild(panel)
  panel.querySelector('#jy-tron-single').addEventListener('click', single)
  panel.querySelector('#jy-tron-toggle').addEventListener('click', () => running ? stop() : start())
  updatePanel()
}

ipcRenderer.on('tronclass:configure', (_event, nextConfig) => { config = { ...config, ...nextConfig } })
ipcRenderer.on('tronclass:command', (_event, command, nextConfig) => {
  config = { ...config, ...(nextConfig || {}) }
  if (command === 'start') start()
  else if (command === 'stop') stop()
  else if (command === 'single') single()
  else if (command === 'clear-history') { history = []; emitLog('[系统] 已清空多轮记忆') }
})

window.addEventListener('DOMContentLoaded', () => { mountPanel(); emitStatus() })
window.addEventListener('beforeunload', () => stop('[页面] 页面正在切换'))
