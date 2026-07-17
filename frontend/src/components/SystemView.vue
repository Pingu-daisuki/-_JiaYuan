<template>
  <div class="system-view">
    <div class="page-header">
      <div>
        <h2>运行与数据中心</h2>
        <p>统一管理后台任务、数据健康和备份恢复。</p>
      </div>
      <el-button @click="refreshAll" :loading="refreshing">刷新</el-button>
    </div>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="任务中心" name="tasks">
        <el-alert
          v-if="activeTasks.length"
          :title="`${activeTasks.length} 个任务正在运行或等待处理`"
          type="info"
          show-icon
          :closable="false"
          class="section-alert"
        />
        <el-empty v-if="!tasks.length" description="暂无后台任务" />
        <div v-else class="task-list">
          <el-card v-for="task in tasks" :key="task.id" shadow="never" class="task-card">
            <div class="task-heading">
              <div>
                <strong>{{ task.title }}</strong>
                <span class="task-time">{{ formatTime(task.updated_at) }}</span>
              </div>
              <el-tag :type="statusType(task.status)">{{ statusLabel(task.status) }}</el-tag>
            </div>
            <el-progress
              :percentage="task.progress || 0"
              :status="progressStatus(task.status)"
              :stroke-width="8"
            />
            <div class="task-message">{{ task.message || '等待更新' }}</div>
            <div class="task-actions">
              <el-button
                v-if="isActive(task.status)"
                size="small"
                type="danger"
                plain
                @click="cancelTask(task)"
              >取消</el-button>
              <el-button
                v-if="task.retryable && !isActive(task.status)"
                size="small"
                type="primary"
                plain
                @click="retryTask(task)"
              >重试</el-button>
            </div>
          </el-card>
        </div>
      </el-tab-pane>

      <el-tab-pane label="数据自检" name="diagnostics">
        <div class="toolbar">
          <el-button type="primary" @click="runDiagnostics(false)" :loading="checking">快速自检</el-button>
          <el-button @click="runDiagnostics(true)" :loading="checking">深度检查向量库</el-button>
        </div>
        <el-empty v-if="!diagnostics" description="尚未执行数据自检" />
        <template v-else>
          <el-result
            :icon="diagnostics.healthy ? 'success' : 'warning'"
            :title="diagnostics.healthy ? '数据状态正常' : '发现需要处理的问题'"
            :sub-title="`检查时间：${formatTime(diagnostics.checked_at)}`"
          />
          <el-descriptions border :column="2" class="stats">
            <el-descriptions-item label="数据库完整性">{{ diagnostics.stats.database_integrity }}</el-descriptions-item>
            <el-descriptions-item label="资料记录">{{ diagnostics.stats.file_records || 0 }}</el-descriptions-item>
            <el-descriptions-item label="已就绪资料">{{ diagnostics.stats.ready_files || 0 }}</el-descriptions-item>
            <el-descriptions-item label="向量片段">{{ diagnostics.stats.vector_chunks ?? '未深度检查' }}</el-descriptions-item>
            <el-descriptions-item label="数据占用">{{ formatBytes(diagnostics.stats.data_size_bytes) }}</el-descriptions-item>
            <el-descriptions-item label="磁盘剩余">{{ formatBytes(diagnostics.stats.disk_free_bytes) }}</el-descriptions-item>
          </el-descriptions>
          <el-alert
            v-for="issue in diagnostics.issues"
            :key="issue.code"
            :title="issue.message"
            :type="issue.level === 'error' ? 'error' : 'warning'"
            show-icon
            :closable="false"
            class="issue"
          />
        </template>
      </el-tab-pane>

      <el-tab-pane label="备份与恢复" name="backups">
        <el-alert
          v-if="pendingRestore"
          title="恢复任务已排队：完全退出并重新打开 App 后生效。"
          type="warning"
          show-icon
          :closable="false"
          class="section-alert"
        />
        <div class="toolbar">
          <el-button type="primary" @click="createBackup">创建完整备份</el-button>
          <el-button @click="chooseBackup">导入备份包</el-button>
          <input ref="backupInput" type="file" accept=".zip" hidden @change="importBackup" />
        </div>
        <el-table :data="backups" empty-text="暂无备份">
          <el-table-column prop="name" label="备份文件" min-width="280" />
          <el-table-column label="大小" width="120">
            <template #default="scope">{{ formatBytes(scope.row.size) }}</template>
          </el-table-column>
          <el-table-column label="创建时间" width="190">
            <template #default="scope">{{ formatTime(scope.row.modified_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="190" fixed="right">
            <template #default="scope">
              <el-button link type="primary" @click="downloadBackup(scope.row)">下载</el-button>
              <el-button link type="warning" @click="restoreBackup(scope.row)">恢复</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onActivated, onDeactivated, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch, apiJson } from '../api/client'

const activeTab = ref('tasks')
const tasks = ref([])
const backups = ref([])
const pendingRestore = ref(null)
const diagnostics = ref(null)
const backupInput = ref(null)
const refreshing = ref(false)
const checking = ref(false)
let pollTimer = null

const activeTasks = computed(() => tasks.value.filter(task => isActive(task.status)))
const isActive = status => ['queued', 'running', 'cancelling'].includes(status)
const statusLabel = status => ({
  queued: '等待中', running: '运行中', cancelling: '停止中', completed: '已完成',
  failed: '失败', cancelled: '已取消', interrupted: '已中断',
}[status] || status)
const statusType = status => ({
  completed: 'success', failed: 'danger', cancelled: 'info', interrupted: 'warning',
  running: 'primary', cancelling: 'warning', queued: 'info',
}[status] || 'info')
const progressStatus = status => status === 'failed' ? 'exception' : status === 'completed' ? 'success' : undefined
const formatTime = value => value ? new Date(value).toLocaleString() : '-'
const formatBytes = value => {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

const fetchTasks = async () => {
  const data = await apiJson('/api/tasks?limit=100', { cache: 'no-store' })
  const previousActive = activeTasks.value.length
  tasks.value = data.tasks || []
  if (previousActive && !activeTasks.value.length) await fetchBackups()
}

const fetchBackups = async () => {
  const data = await apiJson('/api/system/backups', { cache: 'no-store' })
  backups.value = data.backups || []
  pendingRestore.value = data.pending_restore || null
}

const refreshAll = async () => {
  refreshing.value = true
  try {
    await Promise.all([fetchTasks(), fetchBackups()])
  } catch (error) {
    ElMessage.error(error.message || '运行中心刷新失败')
  } finally {
    refreshing.value = false
  }
}

const runDiagnostics = async deep => {
  checking.value = true
  try {
    diagnostics.value = await apiJson(`/api/system/diagnostics?deep=${deep}`, {
      timeoutMs: deep ? 120000 : 30000,
    })
    ElMessage.success('数据自检完成')
  } catch (error) {
    ElMessage.error(error.message || '数据自检失败')
  } finally {
    checking.value = false
  }
}

const cancelTask = async task => {
  try {
    await apiJson(`/api/tasks/${task.id}/cancel`, { method: 'POST' })
    await fetchTasks()
  } catch (error) {
    ElMessage.error(error.message || '取消任务失败')
  }
}

const retryTask = async task => {
  try {
    await apiJson(`/api/tasks/${task.id}/retry`, { method: 'POST' })
    ElMessage.success('已创建重试任务')
    await fetchTasks()
  } catch (error) {
    ElMessage.error(error.message || '重试失败')
  }
}

const createBackup = async () => {
  try {
    await apiJson('/api/system/backups', { method: 'POST' })
    ElMessage.success('备份任务已进入后台')
    activeTab.value = 'tasks'
    await fetchTasks()
  } catch (error) {
    ElMessage.error(error.message || '无法创建备份')
  }
}

const chooseBackup = () => backupInput.value?.click()
const importBackup = async event => {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  try {
    await apiJson('/api/system/backups/import', { method: 'POST', body: form, timeoutMs: 120000 })
    ElMessage.success('备份包校验并导入成功')
    await fetchBackups()
  } catch (error) {
    ElMessage.error(error.message || '备份包导入失败')
  }
}

const downloadBackup = async backup => {
  try {
    const response = await apiFetch(`/api/system/backups/${encodeURIComponent(backup.name)}`, { timeoutMs: 0 })
    if (!response.ok) throw new Error(`下载失败（HTTP ${response.status}）`)
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = backup.name
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(error.message || '备份下载失败')
  }
}

const restoreBackup = async backup => {
  try {
    await ElMessageBox.confirm(
      `将在下次启动时用“${backup.name}”替换当前资料库。建议先创建当前数据备份，是否继续？`,
      '确认恢复数据',
      { type: 'warning', confirmButtonText: '排队恢复', cancelButtonText: '取消' },
    )
    const result = await apiJson(`/api/system/backups/${encodeURIComponent(backup.name)}/restore`, { method: 'POST' })
    pendingRestore.value = result.restore
    ElMessage.warning(result.message)
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error.message || '恢复排队失败')
  }
}

const startPolling = () => {
  if (pollTimer) return
  pollTimer = setInterval(() => fetchTasks().catch(() => {}), 3000)
}
const stopPolling = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

onMounted(() => { refreshAll(); startPolling() })
onActivated(startPolling)
onDeactivated(stopPolling)
</script>

<style scoped>
.system-view { height: 100%; overflow-y: auto; box-sizing: border-box; padding: 28px 34px; background: #f6f8fb; }
.page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
.page-header h2 { margin: 0 0 6px; color: #303133; }
.page-header p { margin: 0; color: #909399; }
.section-alert { margin-bottom: 16px; }
.task-list { display: grid; gap: 12px; }
.task-card { border-radius: 10px; }
.task-heading { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.task-time { margin-left: 12px; color: #909399; font-size: 12px; font-weight: normal; }
.task-message { margin-top: 9px; color: #606266; font-size: 13px; white-space: pre-wrap; word-break: break-word; }
.task-actions { margin-top: 10px; text-align: right; }
.toolbar { display: flex; gap: 10px; margin-bottom: 18px; }
.stats { margin-bottom: 16px; }
.issue { margin-top: 10px; }
</style>
