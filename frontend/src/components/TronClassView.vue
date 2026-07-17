<template>
  <div class="tron-container">
    <div class="header">
      <h2>🎓</h2>
      <p class="subtitle">为您分虑 愿您无忧</p>
    </div>

    <el-alert
      v-if="!desktopAvailable"
      type="warning"
      :closable="false"
      show-icon
      title="TronClass 页面控制只在桌面 App 中可用。"
      class="top-alert"
    />

    <el-row :gutter="20">
      <el-col :span="7">
        <el-card class="box-card identity-card" shadow="hover">
          <template #header>
            <div class="identity-header">
              <div class="card-header"><el-icon><User /></el-icon><span>已认证档案（共享）</span></div>
              <el-button type="primary" size="small" plain @click="openAccountDialog"><el-icon><Plus /></el-icon> 新增身份</el-button>
            </div>
          </template>

          <div v-if="!savedAccounts.length" class="empty-tip">暂无认证身份，请先新增。</div>
          <div
            v-for="account in savedAccounts"
            :key="account.student_id"
            class="account-item"
            :class="{ selected: selectedAccount?.student_id === account.student_id }"
          >
            <div class="acc-info">
              <div class="acc-title">👤 {{ account.real_name || '未解析姓名' }}</div>
              <div class="acc-sub">{{ account.student_id }}</div>
            </div>
            <div class="acc-actions">
              <el-popconfirm title="此身份也会从 RollCall 和 OJ 中删除，确定继续吗？" confirm-button-type="danger" @confirm="deleteAccount(account.student_id)">
                <template #reference><el-button type="danger" circle size="small" plain title="删除身份"><el-icon><Delete /></el-icon></el-button></template>
              </el-popconfirm>
              <el-button :type="selectedAccount?.student_id === account.student_id ? 'success' : 'primary'" size="small" plain @click="selectedAccount = account">
                {{ selectedAccount?.student_id === account.student_id ? '已选' : '选用' }}
              </el-button>
            </div>
          </div>

          <div class="model-note">
            <span>当前激活模型</span>
            <b>{{ activeModel?.name || '尚未配置' }}</b>
            <small>{{ activeModel?.modelId || '请前往 Settings 保存并激活模型' }}</small>
          </div>

          <div class="window-status">
            <span class="status-dot" :class="{ online: status.open, running: status.running }"></span>
            <div>
              <b>{{ status.running ? '辅助运行中' : status.open ? '畅课窗口已打开' : '畅课窗口未打开' }}</b>
              <small>{{ shortUrl }}</small>
            </div>
          </div>
          <p class="login-tip">首次打开需要在畅课窗口手动登录；之后登录状态保存在本机独立会话中。</p>
          <el-button type="primary" class="block-button" :disabled="!desktopAvailable || !selectedAccount" @click="openTronClass">
            {{ status.open ? '显示畅课窗口' : '打开畅课并登录' }}
          </el-button>
          <el-button v-if="status.open" class="block-button" plain @click="closeTronClass">关闭畅课窗口</el-button>
        </el-card>
      </el-col>

      <el-col :span="17">
        <el-card class="box-card control-card" shadow="hover">
          <template #header>
            <div class="control-header">
              <div class="card-header"><el-icon><VideoPlay /></el-icon><span>题目辅助控制</span></div>
              <el-tag :type="status.running ? 'success' : 'info'">{{ status.running ? '运行中' : '空闲' }}</el-tag>
            </div>
          </template>
          <div class="control-actions">
            <el-button type="primary" :disabled="!canControl || status.running" @click="sendCommand('single')">单步识别并选择</el-button>
            <el-button type="success" :disabled="!canControl || status.running" @click="sendCommand('start')">开始连续辅助</el-button>
            <el-button type="danger" :disabled="!status.running" @click="sendCommand('stop')">暂停</el-button>
            <el-button :disabled="!status.open" @click="sendCommand('clear-history')">清空多轮记忆</el-button>
          </div>
          <p class="safety-note">仅支持选择题和判断题。程序会模拟选择选项、按安全间隔切换下一题，但不会点击最终“提交”或“交卷”。请在提交前自行核对。</p>
        </el-card>

        <div class="terminal-monitor">
          <div class="terminal-header">🔴 🟡 🟢 TronClass 运行日志</div>
          <div ref="terminalBodyRef" class="terminal-body">
            <div v-if="!logs.length" class="empty-log">请先选择左侧身份并打开畅课窗口，进入题目页面后建议先使用“单步识别并选择”。</div>
            <div v-for="(line, index) in logs" :key="index" class="log-line" :class="logClass(line)">{{ line }}</div>
          </div>
          <div class="terminal-footer"><el-button size="small" @click="logs = []">清空日志</el-button></div>
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="accountDialogVisible" title="新增身份" width="400px">
      <el-form label-position="top">
        <el-form-item label="学号（统一身份认证）"><el-input v-model="accountForm.student_id" placeholder="请输入学号" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="accountForm.password" type="password" show-password placeholder="请输入密码" @keyup.enter="submitAccount" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isSavingAccount" @click="submitAccount">验证并登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onActivated, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Delete, Plus, User, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { apiJson } from '../api/client'
import { campusAccounts as savedAccounts, refreshCampusAccounts } from '../store/useCampusAccounts'

const desktop = window.jiayuanDesktop?.tronClass
const desktopAvailable = Boolean(desktop)
const activeModel = ref(null)
const selectedAccount = ref(null)
const accountDialogVisible = ref(false)
const isSavingAccount = ref(false)
const accountForm = reactive({ student_id: '', password: '' })
const logs = ref([])
const terminalBodyRef = ref(null)
const status = reactive({ open: false, running: false, url: '' })
const options = reactive({ delayMin: 5, delayMax: 10, autoNext: true, useHistory: false, context: '' })
let removeLogListener = null
let removeStatusListener = null

const canControl = computed(() => desktopAvailable && status.open && Boolean(activeModel.value) && Boolean(selectedAccount.value))
const shortUrl = computed(() => {
  if (!status.url) return selectedAccount.value ? `当前身份：${selectedAccount.value.real_name || selectedAccount.value.student_id}` : '请选择身份'
  try { const url = new URL(status.url); return `${url.hostname}${url.pathname}` }
  catch { return status.url }
})

const loadSettings = () => {
  try {
    const saved = JSON.parse(localStorage.getItem('rag_full_settings') || '{}')
    activeModel.value = (saved.configs || []).find(model => model.name === saved.active) || null
  } catch { activeModel.value = null }
  try {
    const stored = JSON.parse(localStorage.getItem('tronclass_assistant_options') || '{}')
    Object.assign(options, stored.options || {})
  } catch { /* 使用默认参数 */ }
}

const fetchAccounts = async () => {
  try {
    const accounts = await refreshCampusAccounts()
    if (selectedAccount.value) selectedAccount.value = accounts.find(account => account.student_id === selectedAccount.value.student_id) || null
    if (!selectedAccount.value && accounts.length) selectedAccount.value = accounts[0]
  } catch (error) { ElMessage.error(error.message || '身份资料同步失败') }
}

const openAccountDialog = () => {
  accountForm.student_id = ''
  accountForm.password = ''
  accountDialogVisible.value = true
}

const submitAccount = async () => {
  if (!accountForm.student_id.trim() || !accountForm.password) return ElMessage.warning('账号和密码不能为空')
  isSavingAccount.value = true
  try {
    const result = await apiJson('/api/campus/account', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(accountForm),
    })
    ElMessage.success(result.message || '身份已验证')
    accountDialogVisible.value = false
    await fetchAccounts()
    selectedAccount.value = savedAccounts.value.find(account => account.student_id === accountForm.student_id) || selectedAccount.value
  } catch (error) { ElMessage.error(error.message || '身份验证失败') }
  finally { isSavingAccount.value = false }
}

const deleteAccount = async studentId => {
  try {
    await apiJson(`/api/campus/account/${encodeURIComponent(studentId)}`, { method: 'DELETE' })
    if (selectedAccount.value?.student_id === studentId) selectedAccount.value = null
    await fetchAccounts()
    ElMessage.success('身份已删除')
  } catch (error) { ElMessage.error(error.message || '删除失败') }
}

const configPayload = () => {
  const model = activeModel.value
  if (!model) throw new Error('请先在 Settings 保存并激活一个模型')
  if (!model.baseUrl || !model.modelId || !model.apiKey) throw new Error('当前激活模型缺少 Base URL、模型 ID 或 API Key')
  return {
    name: model.name, baseUrl: model.baseUrl, apiKey: model.apiKey, modelId: model.modelId,
    delayMin: Math.min(options.delayMin, options.delayMax), delayMax: Math.max(options.delayMin, options.delayMax),
    autoNext: options.autoNext, useHistory: options.useHistory, context: options.context,
    studentId: selectedAccount.value?.student_id || '', realName: selectedAccount.value?.real_name || '',
  }
}

const appendLog = line => {
  logs.value.push(`[${new Date().toLocaleTimeString()}] ${line}`)
  if (logs.value.length > 300) logs.value.splice(0, logs.value.length - 300)
  nextTick(() => { if (terminalBodyRef.value) terminalBodyRef.value.scrollTop = terminalBodyRef.value.scrollHeight })
}

const refreshStatus = async () => {
  if (!desktop) return
  try { Object.assign(status, await desktop.status()) }
  catch (error) { appendLog(`[错误] 无法读取窗口状态：${error.message}`) }
}

const openTronClass = async () => {
  try {
    if (!selectedAccount.value) throw new Error('请先选择已认证身份')
    await desktop.open(configPayload())
    status.open = true
    appendLog(`[系统] 已为 ${selectedAccount.value.real_name || selectedAccount.value.student_id} 打开畅课窗口`)
  } catch (error) { ElMessage.error(error.message || '无法打开畅课窗口') }
}

const closeTronClass = async () => {
  await desktop?.close()
  Object.assign(status, { open: false, running: false, url: '' })
}

const sendCommand = async command => {
  try {
    if (!status.open) throw new Error('请先打开畅课窗口')
    await desktop.command(command, configPayload())
    if (command === 'start') status.running = true
    if (command === 'stop') status.running = false
  } catch (error) { ElMessage.error(error.message || '命令执行失败') }
}

const logClass = line => line.includes('[错误]') ? 'text-danger' : line.includes('[选择]') || line.includes('[完成]') ? 'text-success' : line.includes('[模型]') ? 'text-warning' : line.includes('[系统]') || line.includes('[页面]') ? 'text-muted' : 'text-normal'

onMounted(() => {
  loadSettings(); fetchAccounts(); refreshStatus()
  if (desktop) {
    removeLogListener = desktop.onLog(appendLog)
    removeStatusListener = desktop.onStatus(next => Object.assign(status, next))
  }
})
onActivated(() => { loadSettings(); fetchAccounts(); refreshStatus() })
onBeforeUnmount(() => { removeLogListener?.(); removeStatusListener?.() })
</script>

<style scoped>
.tron-container{max-width:1400px;margin:0 auto;padding:20px;animation:fadeIn .3s ease-out}.header{margin-bottom:20px}.header h2{margin:0 0 5px;color:#303133}.subtitle{margin:0;color:#909399;font-size:13px}.top-alert{margin-bottom:16px}.box-card{border-radius:10px}.identity-card{min-height:520px}.identity-header,.card-header,.control-header{display:flex;align-items:center;gap:8px}.identity-header,.control-header{justify-content:space-between}.card-header{font-weight:bold;font-size:15px;color:#409eff}.empty-tip{text-align:center;color:#909399;padding:40px 10px}.account-item{display:flex;justify-content:space-between;align-items:center;padding:13px;background:#f8f9fa;border-radius:8px;margin-bottom:10px;border-left:4px solid #409eff;transition:.2s}.account-item.selected{border-left-color:#67c23a;background:#f0f9eb}.acc-title{font-size:14px;font-weight:bold;color:#303133}.acc-sub{font-size:12px;color:#909399;margin-top:4px}.acc-actions{display:flex;align-items:center;gap:7px}.model-note{margin-top:16px;padding:11px;background:#f7f9fc;border-radius:8px}.model-note span,.model-note b,.model-note small{display:block}.model-note span,.model-note small{font-size:11px;color:#909399}.model-note b{font-size:13px;margin:3px 0;color:#303133}.window-status{display:flex;align-items:center;gap:10px;margin-top:10px;padding:11px;background:#f7f9fc;border-radius:8px}.window-status b,.window-status small{display:block}.window-status small{color:#909399;font-size:11px;margin-top:3px;max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.status-dot{width:10px;height:10px;border-radius:50%;background:#c0c4cc}.status-dot.online{background:#409eff}.status-dot.running{background:#67c23a;box-shadow:0 0 0 4px #e1f3d8}.login-tip{font-size:11px;line-height:1.5;color:#909399;margin:10px 1px}.block-button{width:100%;margin:0 0 8px!important}.control-card{margin-bottom:20px}.control-actions{display:flex;flex-wrap:wrap;gap:8px}.control-actions .el-button{margin:0}.safety-note{margin:14px 0 0;padding:10px 12px;border-radius:8px;background:#fff7e6;color:#b26b00;font-size:12px;line-height:1.55}.terminal-monitor{height:430px;background:#1e1e1e;border-radius:10px;display:flex;flex-direction:column;box-shadow:0 8px 24px rgba(0,0,0,.15)}.terminal-header{background:#2d2d2d;color:#858585;padding:10px 15px;font:13px monospace;border-bottom:1px solid #3d3d3d}.terminal-body{padding:15px;flex:1;overflow-y:auto;font:13px/1.6 Consolas,monospace}.terminal-footer{padding:9px 15px;background:#1a1a1a;border-top:1px solid #2d2d2d;text-align:right}.empty-log{color:#666;font-style:italic;text-align:center;margin-top:80px;line-height:1.8}.log-line{margin-bottom:4px;word-break:break-word;white-space:pre-wrap}.text-normal{color:#4af626}.text-success{color:#e6a23c;font-weight:bold}.text-danger{color:#f56c6c;font-weight:bold}.text-warning{color:#409eff}.text-muted{color:#67c23a;opacity:.75}@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
</style>
