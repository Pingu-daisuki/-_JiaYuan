<template>
  <div class="campus-container">
    <div class="header">
      <h2>🏫 </h2>
      <p class="subtitle">为您分虑 愿您无忧</p>
    </div>

    <el-row :gutter="20">
      <el-col :span="9">
        <el-card class="box-card" shadow="hover">
          <template #header>
            <div class="card-header" style="justify-content: space-between;">
              <div style="display: flex; align-items: center; gap: 8px;">
                <el-icon><User /></el-icon>
                <span>已认证档案</span>
              </div>
              <el-button type="primary" size="small" plain @click="openAccountDialog">
                <el-icon><Plus /></el-icon> 新增身份
              </el-button>
            </div>
          </template>
          
          <div v-if="savedAccounts.length === 0" class="empty-tip">暂无对象，请添加身份。</div>
          
          <div v-for="acc in savedAccounts" :key="acc.student_id" class="account-item">
            <div class="acc-info">
              <div class="acc-title">👤 {{ acc.real_name || '未解析姓名' }}</div>
              <div class="acc-sub">{{ acc.student_id }} | 阈值: {{ acc.answer_threshold }}人 | 轮询: {{ acc.check_interval }}s</div>
            </div>
            
            <div class="acc-actions">
              <el-button type="info" circle size="small" plain @click="openStrategyDialog(acc)" title="配置专属策略">
                <el-icon><Setting /></el-icon>
              </el-button>
              <el-popconfirm title="确定要删除该账号和所有策略吗？" @confirm="deleteAccount(acc.student_id)" confirm-button-type="danger">
                <template #reference>
                  <el-button type="danger" circle size="small" plain title="删除身份">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </template>
              </el-popconfirm>
              <el-button type="success" size="small" plain @click="openLaunchSelect(acc)">
                🚀 唤醒
              </el-button>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="15">
        <div class="terminal-monitor">
          <div class="terminal-header">🔴 🟡 🟢 运行日志 (Event Stream) {{ currentRunningUser ? `[当前挂机: ${currentRunningUser}]` : '' }}</div>
          <div class="terminal-body" ref="terminalBodyRef">
            <div v-if="logs.length === 0" class="empty-log">控制台空闲中，请选择左侧身份唤醒引擎。</div>
            <div v-for="(log, idx) in logs" :key="idx" class="log-line" :class="getLogColorClass(log)">
              {{ log }}
            </div>
          </div>
          <div class="terminal-footer" v-if="isRunning">
            <el-button type="danger" size="small" @click="stopEngine">🛑 强制终止当前托管进程</el-button>
          </div>
        </div>
      </el-col>
    </el-row>

    <el-dialog v-model="accountDialogVisible" title="新增身份" width="400px">
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

    <el-dialog v-model="strategyDialogVisible" :title="`防风控策略配置 - ${currentStrategyName}`" width="450px">
      <el-form label-position="top">
        <el-form-item label="潜伏阈值 (多少人签到才动手，0为秒签)">
          <el-input-number v-model="strategyForm.answer_threshold" :min="0" />
        </el-form-item>
        <el-form-item label="轮询频率 (秒)">
          <el-slider v-model="strategyForm.check_interval" :min="1" :max="60" show-input />
        </el-form-item>
        <el-form-item label="运行模式">
          <el-radio-group v-model="strategyForm.mode">
            <el-radio-button label="default">全天候监控</el-radio-button>
            <el-radio-button label="custom">自定义时段</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <div v-if="strategyForm.mode === 'custom'" class="time-slots-area">
          <div v-for="(slot, index) in strategyForm.time_slots" :key="index" class="time-slot-row">
            <el-time-select v-model="slot.start" start="08:00" step="00:15" end="22:00" placeholder="开始" style="width: 100px;" />
            <span class="to-text">至</span>
            <el-time-select v-model="slot.end" start="08:00" step="00:15" end="22:30" placeholder="结束" style="width: 100px;" />
            <el-button type="danger" circle size="small" plain @click="removeTimeSlot(index)" style="margin-left: 10px;">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
          <el-button type="primary" plain size="small" @click="addTimeSlot">
            <el-icon><Plus /></el-icon> 添加时段
          </el-button>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="strategyDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="isSavingStrategy" @click="submitStrategy">应用策略</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { Setting, Plus, Delete, User } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'

// --- 状态控制 ---
const savedAccounts = ref([])
const isRunning = ref(false)
const currentRunningUser = ref('')
const logs = ref([])
const terminalBodyRef = ref(null)
let eventSource = null

// --- 弹窗与表单状态 ---
const accountDialogVisible = ref(false)
const isSavingAccount = ref(false)
const accountForm = reactive({ student_id: '', password: '' })

const strategyDialogVisible = ref(false)
const isSavingStrategy = ref(false)
const currentStrategyId = ref('')
const currentStrategyName = ref('')
const strategyForm = reactive({ mode: 'default', check_interval: 5, answer_threshold: 0, time_slots: [] })

// --- 辅助函数 ---
const addTimeSlot = () => strategyForm.time_slots.push({ start: '08:00', end: '09:50' })
const removeTimeSlot = (index) => strategyForm.time_slots.splice(index, 1)

// --- 数据获取 ---
const fetchAccounts = async () => {
  const res = await fetch('http://127.0.0.1:8000/api/campus/accounts')
  if (res.ok) savedAccounts.value = await res.json()
}

// --- 操作：身份登记 ---
const openAccountDialog = () => {
  accountForm.student_id = ''
  accountForm.password = ''
  accountDialogVisible.value = true
}

const submitAccount = async () => {
  if (!accountForm.student_id || !accountForm.password) return ElMessage.warning('密码或账号不能为空！')
  isSavingAccount.value = true
  try {
    const res = await fetch('http://127.0.0.1:8000/api/campus/account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(accountForm)
    })
    const data = await res.json()
    if (res.ok) {
      ElMessage.success(data.message)
      accountDialogVisible.value = false
      fetchAccounts()
    } else {
      ElMessage.error(data.detail)
    }
  } catch (err) {
    ElMessage.error('网络通讯失败')
  } finally {
    isSavingAccount.value = false
  }
}

// --- 操作：策略配置 ---
const openStrategyDialog = (account) => {
  currentStrategyId.value = account.student_id
  currentStrategyName.value = account.real_name || account.student_id
  
  strategyForm.mode = account.mode || 'default'
  strategyForm.check_interval = account.check_interval || 5
  strategyForm.answer_threshold = account.answer_threshold || 0
  
  try {
    strategyForm.time_slots = typeof account.time_slots === 'string' ? JSON.parse(account.time_slots) : []
  } catch(e) { strategyForm.time_slots = [] }
  
  strategyDialogVisible.value = true
}

const submitStrategy = async () => {
  isSavingStrategy.value = true
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/campus/strategy/${currentStrategyId.value}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(strategyForm)
    })
    if (res.ok) {
      ElMessage.success('策略已成功更新！')
      strategyDialogVisible.value = false
      fetchAccounts() // 刷新列表以显示最新阈值
    }
  } catch (err) {
    ElMessage.error('网络通讯失败')
  } finally {
    isSavingStrategy.value = false
  }
}

// --- 操作：删除账号 ---
const deleteAccount = async (studentId) => {
  try {
    const res = await fetch(`http://127.0.0.1:8000/api/campus/account/${studentId}`, { method: 'DELETE' })
    if (res.ok) {
      ElMessage.success('账号已成功删除')
      fetchAccounts()
    }
  } catch (err) {
    ElMessage.error('删除失败')
  }
}

// --- 操作：启动监控 ---
const openLaunchSelect = (account) => {
  if (isRunning.value) return ElMessage.warning('已有进程在巡航中，请先终止当前进程。')
  
  ElMessageBox.confirm(
    `确认以 [ ${account.real_name} ] 的身份启动自动化打卡策略吗？`,
    '唤醒确认',
    { confirmButtonText: '启动', cancelButtonText: '取消', type: 'success' }
  ).then(() => startEngine(account)).catch(() => {})
}

const startEngine = (account) => {
  isRunning.value = true
  currentRunningUser.value = account.real_name
  logs.value = [`[系统] 🛰️ 正在为 ${account.real_name} 建立独占流式传输管线...`]
  
  eventSource = new EventSource(`http://127.0.0.1:8000/api/campus/stream_sign/${account.student_id}`)
  
  eventSource.onmessage = (event) => {
    logs.value.push(event.data)
    nextTick(() => { if (terminalBodyRef.value) terminalBodyRef.value.scrollTop = terminalBodyRef.value.scrollHeight })
  }
  
  eventSource.onerror = () => {
    logs.value.push('[系统] 🛑 引擎管线已安全挂起注销。')
    eventSource.close()
    isRunning.value = false
    currentRunningUser.value = ''
  }
}

const stopEngine = () => {
  if (eventSource) eventSource.close()
  isRunning.value = false
  currentRunningUser.value = ''
  logs.value.push('[系统] 🛑 强制拦截，引擎停止工作。')
}

// --- 颜色处理 ---
const getLogColorClass = (logText) => {
  if (logText.includes('[警报]') || logText.includes('❌')) return 'text-danger'
  if (logText.includes('[战果]') || logText.includes('🎉') || logText.includes('✅')) return 'text-success'
  if (logText.includes('[策略]') || logText.includes('[潜伏]')) return 'text-warning'
  if (logText.includes('[监控]') || logText.includes('[休眠]')) return 'text-muted'
  return 'text-normal'
}

onMounted(() => { fetchAccounts() })
</script>

<style scoped>
.campus-container { max-width: 1400px; margin: 0 auto; padding: 20px; animation: fadeIn 0.3s ease-out; }
.header { margin-bottom: 20px; }
.header h2 { margin: 0 0 5px 0; color: #303133; }
.subtitle { margin: 0; color: #909399; font-size: 13px; }

.box-card { border-radius: 10px; min-height: 600px; }
.card-header { display: flex; align-items: center; gap: 8px; font-weight: bold; font-size: 15px; color: #409EFF; }

/* 账号列表子项 */
.account-item { display: flex; justify-content: space-between; align-items: center; padding: 15px; background: #f8f9fa; border-radius: 8px; margin-bottom: 12px; border-left: 4px solid #409EFF; box-shadow: 0 2px 8px rgba(0,0,0,0.05); transition: all 0.2s; }
.account-item:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
.acc-title { font-size: 15px; font-weight: bold; color: #303133; margin-bottom: 4px; }
.acc-sub { font-size: 12px; color: #909399; }
.acc-actions { display: flex; gap: 8px; align-items: center; }
.empty-tip { text-align: center; color: #909399; font-size: 14px; padding: 40px; }

/* 弹窗中的策略表单 */
.threshold-desc { font-size: 12px; color: #909399; margin-bottom: 4px; }
.time-slots-area { background: #f4f4f5; padding: 12px; border-radius: 6px; margin-bottom: 15px; border: 1px dashed #dcdfe6; }
.time-slot-row { display: flex; align-items: center; margin-bottom: 8px; }
.to-text { margin: 0 8px; color: #606266; font-size: 12px; }

/* 终端 */
.terminal-monitor { background-color: #1e1e1e; border-radius: 10px; display: flex; flex-direction: column; height: 600px; box-shadow: 0 8px 24px rgba(0,0,0,0.15); }
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