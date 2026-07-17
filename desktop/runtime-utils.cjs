const { URL } = require('node:url')

function backendUrl(port) {
  const normalizedPort = Number(port)
  if (!Number.isInteger(normalizedPort) || normalizedPort < 1 || normalizedPort > 65535) {
    throw new TypeError('backend port must be an integer between 1 and 65535')
  }
  return `http://127.0.0.1:${normalizedPort}`
}

function withApiBase(frontendUrl, apiBase) {
  const target = new URL(frontendUrl)
  target.searchParams.set('apiBase', apiBase)
  return target.toString()
}

function frontendLoadOptions(apiBase) {
  return { query: { apiBase } }
}

function isTrustedNavigation(targetUrl, developmentUrl = '') {
  if (targetUrl.startsWith('file://')) return true
  if (!developmentUrl) return false
  try {
    return new URL(targetUrl).origin === new URL(developmentUrl).origin
  } catch {
    return false
  }
}

function isTrustedTronClassUrl(targetUrl) {
  try {
    const target = new URL(targetUrl)
    const host = target.hostname.toLowerCase()
    return target.protocol === 'https:' && (
      host === 'lnt.xmu.edu.cn'
      || host.endsWith('.xmu.edu.cn')
      || host === 'tronclass.com.cn'
      || host.endsWith('.tronclass.com.cn')
    )
  } catch { return false }
}

function resolveChatCompletionEndpoint(baseUrl) {
  let endpoint
  try {
    endpoint = new URL(String(baseUrl || '').trim())
    if (!endpoint.pathname.replace(/\/+$/, '').endsWith('/chat/completions')) {
      endpoint.pathname = `${endpoint.pathname.replace(/\/+$/, '')}/chat/completions`
    }
  }
  catch { throw new TypeError('model Base URL is invalid') }
  const localHttp = endpoint.protocol === 'http:' && ['127.0.0.1', 'localhost', '::1'].includes(endpoint.hostname)
  if (endpoint.protocol !== 'https:' && !localHttp) throw new TypeError('remote model endpoint must use HTTPS')
  return endpoint.toString()
}

function backendTerminationPlan(platform, pid) {
  if (!Number.isInteger(pid) || pid <= 0) throw new TypeError('pid must be a positive integer')
  return platform === 'win32'
    ? { command: 'taskkill', args: ['/PID', String(pid), '/T', '/F'] }
    : { signal: 'SIGTERM' }
}

module.exports = {
  backendTerminationPlan,
  backendUrl,
  frontendLoadOptions,
  isTrustedNavigation,
  isTrustedTronClassUrl,
  resolveChatCompletionEndpoint,
  withApiBase,
}
