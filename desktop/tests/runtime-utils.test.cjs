const assert = require('node:assert/strict')
const test = require('node:test')

const {
  backendTerminationPlan,
  backendUrl,
  frontendLoadOptions,
  isTrustedNavigation,
  isTrustedTronClassUrl,
  resolveChatCompletionEndpoint,
  withApiBase,
} = require('../runtime-utils.cjs')

test('desktop API base uses the selected private backend port', () => {
  assert.equal(backendUrl(8765), 'http://127.0.0.1:8765')
  assert.throws(() => backendUrl(0), /backend port/)
})

test('development and packaged frontend receive the same API base', () => {
  const apiBase = backendUrl(8765)
  const development = new URL(withApiBase('http://127.0.0.1:5173/?mode=dev', apiBase))
  assert.equal(development.searchParams.get('mode'), 'dev')
  assert.equal(development.searchParams.get('apiBase'), apiBase)
  assert.deepEqual(frontendLoadOptions(apiBase), { query: { apiBase } })
})

test('navigation trust uses exact origin instead of a vulnerable prefix', () => {
  const dev = 'http://127.0.0.1:5173'
  assert.equal(isTrustedNavigation('file:///app/index.html', dev), true)
  assert.equal(isTrustedNavigation('http://127.0.0.1:5173/page', dev), true)
  assert.equal(isTrustedNavigation('http://127.0.0.1:5173.evil.example/page', dev), false)
  assert.equal(isTrustedNavigation('https://example.com', dev), false)
})

test('Windows backend shutdown terminates the complete process tree', () => {
  assert.deepEqual(backendTerminationPlan('win32', 1234), {
    command: 'taskkill', args: ['/PID', '1234', '/T', '/F'],
  })
  assert.deepEqual(backendTerminationPlan('linux', 1234), { signal: 'SIGTERM' })
})

test('TronClass window only trusts XMU and TronClass HTTPS pages', () => {
  assert.equal(isTrustedTronClassUrl('https://lnt.xmu.edu.cn/course/1'), true)
  assert.equal(isTrustedTronClassUrl('https://ids.xmu.edu.cn/auth'), true)
  assert.equal(isTrustedTronClassUrl('https://foo.tronclass.com.cn/quiz'), true)
  assert.equal(isTrustedTronClassUrl('http://lnt.xmu.edu.cn/'), false)
  assert.equal(isTrustedTronClassUrl('https://xmu.edu.cn.evil.example/'), false)
})

test('model proxy requires HTTPS except for loopback services', () => {
  assert.equal(resolveChatCompletionEndpoint('https://api.deepseek.com/v1'), 'https://api.deepseek.com/v1/chat/completions')
  assert.equal(resolveChatCompletionEndpoint('https://api.deepseek.com/v1/chat/completions'), 'https://api.deepseek.com/v1/chat/completions')
  assert.equal(resolveChatCompletionEndpoint('http://127.0.0.1:11434/v1/'), 'http://127.0.0.1:11434/v1/chat/completions')
  assert.throws(() => resolveChatCompletionEndpoint('http://example.com/v1'), /HTTPS/)
})
