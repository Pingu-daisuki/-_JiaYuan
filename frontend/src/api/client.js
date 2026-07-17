const DEFAULT_API_BASE = 'http://127.0.0.1:8000'

const normalizeBase = (value) => String(value || '').trim().replace(/\/$/, '')

const runtimeBase = (() => {
  const queryBase = typeof window === 'undefined'
    ? ''
    : new URLSearchParams(window.location.search).get('apiBase')
  return normalizeBase(queryBase || import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE)
})()

export const API_BASE = runtimeBase

export class ApiError extends Error {
  constructor(message, { status = 0, payload = null, cause = null, guidance = '' } = {}) {
    super(message, { cause })
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
    this.guidance = guidance
  }
}

const guidanceForStatus = status => ({
  400: '请检查输入内容或目标目录后重试。',
  401: '认证已失效，请重新验证身份或检查模型密钥。',
  403: '当前操作没有权限，请重新认证或更换可访问的资料。',
  404: '目标可能已被移动或删除，请刷新页面后重试。',
  409: '当前状态与操作冲突，请等待正在执行的任务结束。',
  413: '文件过大，请压缩或拆分后重新导入。',
  422: '文件内容无法解析，请检查格式、密码保护或文件是否损坏。',
  429: '请求过于频繁，请稍后重试。',
  500: '本地服务处理失败，可前往“运行与数据”查看任务日志并重试。',
  503: '依赖服务暂不可用，请检查模型服务或解析引擎状态。',
}[status] || (status >= 500 ? '请查看任务日志或数据自检后重试。' : '请刷新当前数据后重试。'))

export const apiUrl = (path = '') => {
  if (/^https?:\/\//i.test(path)) return path
  return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`
}

const errorMessage = (payload, fallback) => {
  if (typeof payload === 'string' && payload.trim()) return payload
  if (payload?.detail) return typeof payload.detail === 'string'
    ? payload.detail
    : JSON.stringify(payload.detail)
  if (payload?.message) return payload.message
  return fallback
}

export const apiFetch = async (path, options = {}) => {
  const {
    timeoutMs = 30000,
    signal: callerSignal,
    headers,
    ...fetchOptions
  } = options
  const controller = timeoutMs > 0 ? new AbortController() : null
  const onAbort = () => controller?.abort(callerSignal?.reason)
  if (callerSignal) {
    if (callerSignal.aborted) onAbort()
    else callerSignal.addEventListener('abort', onAbort, { once: true })
  }
  const timer = controller && setTimeout(() => controller.abort('timeout'), timeoutMs)

  try {
    return await fetch(apiUrl(path), {
      ...fetchOptions,
      headers,
      signal: controller?.signal || callerSignal,
    })
  } catch (cause) {
    if (controller?.signal.aborted && !callerSignal?.aborted) {
      throw new ApiError(`请求超时（${Math.ceil(timeoutMs / 1000)} 秒）`, { cause, guidance: '任务可能仍在后台运行，请先查看任务中心，避免重复提交。' })
    }
    if (callerSignal?.aborted) throw cause
    throw new ApiError('无法连接本地服务，请确认后端已启动', { cause, guidance: '完全退出并重新打开 App；若仍失败，请前往“运行与数据”查看状态。' })
  } finally {
    if (timer) clearTimeout(timer)
    callerSignal?.removeEventListener('abort', onAbort)
  }
}

export const apiJson = async (path, options = {}) => {
  const response = await apiFetch(path, options)
  const contentType = response.headers.get('content-type') || ''
  let payload
  try {
    payload = contentType.includes('json') ? await response.json() : await response.text()
  } catch {
    payload = undefined
  }
  if (!response.ok) {
    const message = errorMessage(payload, `请求失败（HTTP ${response.status}）`)
    const guidance = payload?.guidance || guidanceForStatus(response.status)
    throw new ApiError(
      `${message}${guidance ? ` ${guidance}` : ''}`,
      { status: response.status, payload, guidance },
    )
  }
  return payload
}

export const apiEventSource = (path) => new EventSource(apiUrl(path))
