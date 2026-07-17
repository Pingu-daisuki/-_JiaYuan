<template>
  <div class="campus-container">
    <div class="header">
      <h2>💻 </h2>
      <p class="subtitle">为您分虑 愿您无忧</p>
    </div>

    <el-row :gutter="20">
      <el-col :span="6">
        <el-card class="box-card left-card" shadow="hover">
          <template #header>
            <div class="card-header" style="justify-content: space-between;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <el-icon><User /></el-icon>
                <span>已认证档案 (共享)</span>
              </div>
              <el-button type="primary" size="small" plain @click="openAccountDialog">
                <el-icon><Plus /></el-icon> 新增
              </el-button>
            </div>
          </template>
          
          <div v-if="savedAccounts.length === 0" class="empty-tip">暂无对象，请添加身份。</div>
          
          <div 
            v-for="acc in savedAccounts" 
            :key="acc.student_id" 
            class="account-item"
            :class="{ 'is-selected': selectedAccount?.student_id === acc.student_id }"
          >
            <div class="acc-info">
              <div class="acc-title">👤 {{ acc.real_name || '未解析' }}</div>
              <div class="acc-sub">{{ acc.student_id }}</div>
            </div>
            
            <div class="acc-actions">
              <el-popconfirm title="确定要删除该全局账号吗？" @confirm="deleteAccount(acc.student_id)" confirm-button-type="danger">
                <template #reference>
                  <el-button type="danger" circle size="small" plain title="删除身份">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-popconfirm>
              
              <el-button 
                :type="selectedAccount?.student_id === acc.student_id ? 'success' : 'primary'" 
                size="small" 
                plain 
                @click="selectedAccount = acc"
              >
                {{ selectedAccount?.student_id === acc.student_id ? '🎯 已选' : '选用' }}
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="18">
        
        <el-card class="box-card config-card" shadow="hover" style="min-height: auto; margin-bottom: 20px;">
          <template #header>
            <div class="card-header">
              <span>⚙️ 引擎控制与参数调度</span>
            </div>
          </template>
          
          <el-form :inline="true" class="engine-form">
            <el-form-item label="大模型">
              <el-select v-model="selectedModel" placeholder="选择大模型" style="width: 150px" :disabled="isRunning">
                <el-option v-for="model in availableModels" :key="model.name" :label="model.name" :value="model.name" />
              </el-select>
            </el-form-item>

            <el-form-item label="实验 ID">
              <el-input v-model="contestId" placeholder="如: 359" style="width: 90px" :disabled="isRunning" />
            </el-form-item>
            
            <el-form-item label="密码">
              <el-input v-model="contestPassword" type="password" show-password placeholder="可空" style="width: 100px" :disabled="isRunning" />
            </el-form-item>

            <el-form-item label="间隔(秒)">
              <el-input-number v-model="solveInterval" :min="1" :max="300" style="width: 100px" :disabled="isRunning" />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" :disabled="isRunning" @click="startEngine">
                🚀 {{ isRunning ? '攻破中...' : '启动破题' }}
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>

        <div class="terminal-monitor" style="height: 440px;"> 
          <div class="terminal-header">
            🔴 🟡 🟢 运行日志 (Event Stream) {{ currentRunningUser ? `[当前任务: ${currentRunningUser}]` : '' }}
          </div>
          <div class="terminal-body" ref="terminalBodyRef">
            <div v-if="logs.length === 0" class="empty-log">
              引擎空闲中。<br><br>请在左侧【选用】一个身份，输入实验参数后启动。
            </div>
            <div v-for="(log, idx) in logs" :key="idx" class="log-line" :class="getLogColorClass(log)">
              {{ log }}
            </div>
          </div>
          <div class="terminal-footer" v-if="isRunning">
            <el-button type="danger" size="small" @click="stopEngine">🛑 强制终止当前破题进程</el-button>
          </div>
        </div>
        
      </el-col>
    </el-row>

    <el-dialog v-model="accountDialogVisible" title="新增全局身份 (两端同步)" width="400px">
      <el-form label-position="top">
        <el-form-item label="学号 (统一身份认证)">
          <el-input v-model="accountForm.student_id" placeholder="请输入学号" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="accountForm.password" type="password" show-password placeholder="请输入密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="accountDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isSavingAccount" @click="submitAccount">验证并登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onActivated, nextTick } from 'vue'
import { Plus, Delete, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { campusAccounts as savedAccounts, refreshCampusAccounts } from '../store/useCampusAccounts'
import { apiEventSource, apiFetch } from '../api/client'

const selectedAccount = ref(null) 
const accountDialogVisible = ref(false)
const isSavingAccount = ref(false)
const accountForm = reactive({ student_id: '', password: '' })

const availableModels = ref([])
const selectedModel = ref('')
const contestId = ref('')
const contestPassword = ref('')
const solveInterval = ref(5)
const isRunning = ref(false)
const currentRunningUser = ref('')
const logs = ref([])
const terminalBodyRef = ref(null)
let eventSource = null

const loadModelConfigs = () => {
  const savedSettings = localStorage.getItem('rag_full_settings')
  if (!savedSettings) {
    availableModels.value = []
    selectedModel.value = ''
    return
  }

  try {
    const parsed = JSON.parse(savedSettings)
    availableModels.value = Array.isArray(parsed.configs) ? parsed.configs : []
    if (parsed.active && availableModels.value.some(model => model.name === parsed.active)) {
      selectedModel.value = parsed.active
    } else if (!selectedModel.value && availableModels.value.length > 0) {
      selectedModel.value = availableModels.value[0].name
    }
  } catch (e) {
    console.error('读取模型配置失败', e)
    availableModels.value = []
    selectedModel.value = ''
  }
}

const fetchAccounts = async () => {
  try {
    const accounts = await refreshCampusAccounts()
    if (selectedAccount.value) {
      selectedAccount.value = accounts.find(
        account => account.student_id === selectedAccount.value.student_id
      ) || null
    }
    if (accounts.length > 0 && !selectedAccount.value) {
      selectedAccount.value = accounts[0]
    }
  } catch (e) {
    console.error('同步身份数据失败', e)
  }
}

onActivated(() => {
  fetchAccounts()
  loadModelConfigs()
})
onMounted(() => {
  fetchAccounts()
  loadModelConfigs()
})

const openAccountDialog = () => {
  accountForm.student_id = ''
  accountForm.password = ''
  accountDialogVisible.value = true
}

const submitAccount = async () => {
  if (!accountForm.student_id || !accountForm.password) return ElMessage.warning('密码或账号不能为空！')
  isSavingAccount.value = true
  try {
    const res = await apiFetch('/api/campus/account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(accountForm)
    })
    const data = await res.json()
    if (res.ok) {
      ElMessage.success(data.message)
      accountDialogVisible.value = false
      await fetchAccounts()
    } else {
      ElMessage.error(data.detail)
    }
  } catch {
    ElMessage.error('网络通讯失败')
  } finally {
    isSavingAccount.value = false
  }
}

const deleteAccount = async (studentId) => {
  try {
    const res = await apiFetch(`/api/campus/account/${encodeURIComponent(studentId)}`, { method: 'DELETE' })
    if (res.ok) {
      ElMessage.success('全局账号已成功删除')
      if (selectedAccount.value?.student_id === studentId) selectedAccount.value = null
      await fetchAccounts()
    }
  } catch {
    ElMessage.error('删除失败')
  }
}

const startEngine = () => {
  if (!selectedAccount.value) return ElMessage.warning('请先在左侧选择要执行任务的身份！')
  if (!contestId.value) return ElMessage.warning('请输入实验 ID！')
  if (!selectedModel.value) return ElMessage.warning('请先在设置页保存并选择一个模型！')
  if (isRunning.value) return ElMessage.warning('已有进程在运行中！')

  loadModelConfigs()
  const currentModel = availableModels.value.find(model => model.name === selectedModel.value)
  if (!currentModel) return ElMessage.warning('未找到当前模型配置，请先在设置页保存模型。')

  isRunning.value = true
  currentRunningUser.value = selectedAccount.value.real_name || selectedAccount.value.student_id
  logs.value = []
  
  logs.value.push(`[系统] 🛰️ 正在为 ${currentRunningUser.value} 建立 OJ 自动破题管线...`)
  logs.value.push(`[配置] 加载模型: ${currentModel.name} (${currentModel.modelId}) | 目标实验: ${contestId.value}`)

  const params = new URLSearchParams({
    contest_id: contestId.value,
    contest_password: contestPassword.value,
    student_id: selectedAccount.value.student_id,
    model: currentModel.name,
    model_id: currentModel.modelId || currentModel.name,
    model_type: currentModel.type || 'cloud',
    base_url: currentModel.baseUrl || '',
    api_key: currentModel.apiKey || '',
    interval: String(solveInterval.value)
  })
  eventSource = apiEventSource(`/api/oj/stream_solve?${params.toString()}`)

  eventSource.onmessage = (event) => {
    logs.value.push(event.data)
    nextTick(() => { if (terminalBodyRef.value) terminalBodyRef.value.scrollTop = terminalBodyRef.value.scrollHeight })
    
    if (event.data.includes('任务完成') || event.data.includes('执行异常')) {
      stopEngine()
    }
  }

  eventSource.onerror = () => {
    logs.value.push('[系统] 🛑 引擎流式管线意外断开。')
    stopEngine()
  }
}

const stopEngine = () => {
  if (eventSource) eventSource.close()
  isRunning.value = false
  currentRunningUser.value = ''
}

const getLogColorClass = (logText) => {
  if (logText.includes('[错误]') || logText.includes('❌') || logText.includes('异常')) return 'text-danger'
  if (logText.includes('[成功]') || logText.includes('🎉') || logText.includes('✅') || logText.includes('[认证]')) return 'text-success'
  if (logText.includes('[处理]') || logText.includes('⚔️') || logText.includes('[提交]')) return 'text-warning'
  if (logText.includes('[系统]')) return 'text-muted'
  return 'text-normal'
}
</script>

<style scoped>
.campus-container { max-width: 1400px; margin: 0 auto; padding: 20px; animation: fadeIn 0.3s ease-out; }
.header { margin-bottom: 20px; }
.header h2 { margin: 0 0 5px 0; color: #303133; }
.subtitle { margin: 0; color: #909399; font-size: 13px; }

.box-card { border-radius: 10px; }
.left-card { min-height: 200px; } /* 解除了左边强制 600px 的限制 */
.card-header { display: flex; align-items: center; gap: 8px; font-weight: bold; font-size: 15px; color: #409EFF; }

.account-item { display: flex; justify-content: space-between; align-items: center; padding: 15px; background: #f8f9fa; border-radius: 8px; margin-bottom: 12px; border-left: 4px solid #409EFF; box-shadow: 0 2px 8px rgba(0,0,0,0.05); transition: all 0.2s; }
.account-item:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.acc-title { font-size: 15px; font-weight: bold; color: #303133; margin-bottom: 4px; }
.acc-sub { font-size: 12px; color: #909399; }
.acc-actions { display: flex; gap: 8px; align-items: center; }
.empty-tip { text-align: center; color: #909399; font-size: 14px; padding: 40px; }

.is-selected { border-left: 4px solid #67c23a; background-color: #f0f9eb; }

.config-card { min-height: auto; }
.engine-form { display: flex; flex-wrap: wrap; align-items: flex-end; margin-bottom: -18px; }

.terminal-monitor { background-color: #1e1e1e; border-radius: 10px; display: flex; flex-direction: column; box-shadow: 0 8px 24px rgba(0,0,0,0.15); }
.terminal-header { background-color: #2d2d2d; color: #858585; padding: 10px 15px; font-size: 13px; font-family: monospace; border-bottom: 1px solid #3d3d3d; }
.terminal-body { padding: 15px; flex: 1; overflow-y: auto; font-family: 'Consolas', monospace; font-size: 13px; line-height: 1.6; }
.terminal-footer { padding: 10px 15px; background: #1a1a1a; border-top: 1px solid #2d2d2d; text-align: right; }
.empty-log { color: #555; font-style: italic; text-align: center; margin-top: 50px; }

.log-line { margin-bottom: 4px; word-break: break-all; white-space: pre-wrap; }
.text-normal { color: #4af626; }
.text-success { color: #e6a23c; font-weight: bold; }
.text-danger { color: #f56c6c; font-weight: bold; }
.text-warning { color: #409EFF; }
.text-muted { color: #67c23a; opacity: 0.6; }

@keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
</style>
