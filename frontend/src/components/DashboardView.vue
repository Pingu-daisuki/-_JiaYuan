<template>
  <div class="dashboard-page" v-loading="loading">
    <header class="dashboard-header">
      <div>
        <h1>{{ greeting }}，今天从这里开始</h1>
        <p>Deadline、资料处理、对话和签到监控都集中在一个页面。</p>
      </div>
      <el-button :loading="loading" @click="loadDashboard">刷新</el-button>
    </header>

    <el-alert v-if="error" type="error" :closable="false" show-icon>
      <template #title>仪表盘暂时无法加载</template>
      {{ error }}。请确认本地服务已启动，或前往“运行与数据”查看自检结果。
    </el-alert>

    <section class="summary-grid">
      <button class="summary-card blue" @click="$emit('navigate', 'deadlines')">
        <span>未来 7 天 Deadline</span><strong>{{ data.deadlines?.length || 0 }}</strong><small>查看时间安排</small>
      </button>
      <button class="summary-card amber" @click="$emit('navigate', 'system')">
        <span>正在处理</span><strong>{{ data.task_summary?.active || 0 }}</strong><small>后台任务</small>
      </button>
      <button class="summary-card red" @click="$emit('navigate', 'system')">
        <span>失败 / 待重试</span><strong>{{ (data.task_summary?.failed || 0) + failedDocuments }}</strong><small>立即处理</small>
      </button>
      <button class="summary-card green" @click="$emit('navigate', 'library')">
        <span>资料库健康</span><strong>{{ data.health?.healthy ? '正常' : '需处理' }}</strong><small>{{ formatBytes(data.health?.stats?.data_size_bytes) }} 已占用</small>
      </button>
    </section>

    <section class="dashboard-grid">
      <article class="panel deadlines-panel">
        <div class="panel-title"><h2>今天与未来 7 天</h2><el-button link type="primary" @click="$emit('navigate', 'deadlines')">全部</el-button></div>
        <el-empty v-if="!data.deadlines?.length" description="未来 7 天没有待完成任务" :image-size="54" />
        <button v-for="item in data.deadlines" :key="item.id" class="list-row" @click="$emit('navigate', 'deadlines')">
          <span class="date-badge">{{ dayLabel(item.deadline) }}</span>
          <span class="row-main"><b>{{ item.task_name }}</b><small>{{ item.course_name || '未分类课程' }}</small></span>
          <span class="row-meta">{{ timeLabel(item.deadline) }}</span>
        </button>
      </article>

      <article class="panel">
        <div class="panel-title"><h2>文档处理</h2><el-button link type="primary" @click="$emit('navigate', 'system')">任务中心</el-button></div>
        <el-empty v-if="!data.documents?.length" description="没有处理中或失败的文档" :image-size="54" />
        <div v-for="item in data.documents" :key="item.id" class="list-row static-row">
          <span class="status-dot" :class="item.status"></span>
          <span class="row-main"><b>{{ item.file_name }}</b><small>{{ item.error_message || statusLabel(item.status) }}</small></span>
          <el-tag size="small" :type="item.status === 'failed' ? 'danger' : 'warning'">{{ statusLabel(item.status) }}</el-tag>
        </div>
      </article>

      <article class="panel">
        <div class="panel-title"><h2>最近资料</h2><el-button link type="primary" @click="$emit('navigate', 'library')">资料库</el-button></div>
        <el-empty v-if="!data.recent_files?.length" description="还没有导入资料" :image-size="54" />
        <button v-for="item in data.recent_files" :key="item.id" class="list-row" @click="$emit('navigate', 'library')">
          <span class="file-icon">{{ fileIcon(item.file_name) }}</span>
          <span class="row-main"><b>{{ item.file_name }}</b><small>{{ item.course_name || '根目录' }}</small></span>
          <el-tag size="small" :type="item.status === 'ready' ? 'success' : 'warning'">{{ statusLabel(item.status) }}</el-tag>
        </button>
      </article>

      <article class="panel">
        <div class="panel-title"><h2>最近对话</h2><el-button link type="primary" @click="$emit('navigate', 'chat')">新对话</el-button></div>
        <el-empty v-if="!data.conversations?.length" description="还没有保存的对话" :image-size="54" />
        <button v-for="item in data.conversations" :key="item.id" class="list-row" @click="openConversation(item.id)">
          <span class="file-icon">💬</span>
          <span class="row-main"><b>{{ item.title }}</b><small>{{ item.course_name || '全部资料' }} · {{ item.message_count }} 条消息</small></span>
          <span v-if="item.pinned">📌</span>
        </button>
      </article>

      <article class="panel">
        <div class="panel-title"><h2>待复习知识点</h2><span class="panel-note">未来 7 天</span></div>
        <el-empty v-if="!data.reviews?.length" description="没有到期复习项，可在回答中固定后创建" :image-size="54" />
        <div v-for="item in data.reviews" :key="item.id" class="list-row static-row">
          <span class="file-icon">🧠</span>
          <span class="row-main"><b>{{ item.title }}</b><small>{{ item.course_name || '未分类' }} · {{ dateTime(item.due_at) }}</small></span>
          <el-button link type="success" @click="completeReview(item)">完成</el-button>
        </div>
      </article>

      <article class="panel">
        <div class="panel-title"><h2>RollCall 监控</h2><el-button link type="primary" @click="$emit('navigate', 'campus')">管理</el-button></div>
        <el-empty v-if="!data.rollcall?.length" description="当前没有监控记录" :image-size="54" />
        <button v-for="item in data.rollcall" :key="item.id" class="list-row" @click="$emit('navigate', 'campus')">
          <span class="status-dot" :class="item.status"></span>
          <span class="row-main"><b>{{ item.title }}</b><small>{{ item.message || '等待状态更新' }}</small></span>
          <el-tag size="small" :type="taskType(item.status)">{{ taskLabel(item.status) }}</el-tag>
        </button>
      </article>
    </section>

    <section class="health-bar" :class="{ warning: !data.health?.healthy }">
      <div><b>资料库健康状态</b><span>{{ healthText }}</span></div>
      <div class="health-numbers">
        <span>{{ data.health?.stats?.ready_files || 0 }} 份可检索资料</span>
        <span>{{ formatBytes(data.health?.stats?.disk_free_bytes) }} 磁盘可用</span>
        <el-button size="small" @click="$emit('navigate', 'system')">查看详情</el-button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onActivated, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { apiJson } from '../api/client'

const emit = defineEmits(['navigate', 'open-conversation'])
const loading = ref(false)
const error = ref('')
const data = ref({})
const greeting = computed(() => new Date().getHours() < 12 ? '早上好' : new Date().getHours() < 18 ? '下午好' : '晚上好')
const failedDocuments = computed(() => data.value.documents?.filter(item => item.status === 'failed').length || 0)
const healthText = computed(() => data.value.health?.healthy ? '数据库、源文件和目录结构状态正常' : (data.value.health?.issues?.[0]?.message || '发现需要处理的问题'))

const loadDashboard = async () => {
  loading.value = true
  error.value = ''
  try { data.value = await apiJson('/api/workspace/dashboard', { cache: 'no-store' }) }
  catch (e) { error.value = e.message || '未知错误' }
  finally { loading.value = false }
}
const openConversation = id => emit('open-conversation', id)
const completeReview = async item => {
  try {
    await apiJson(`/api/workspace/reviews/${item.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'completed' }) })
    data.value.reviews = data.value.reviews.filter(row => row.id !== item.id)
    ElMessage.success('已标记为完成')
  } catch (e) { ElMessage.error(e.message || '更新失败') }
}
const statusLabel = status => ({ uploaded: '等待解析', parsing: '解析中', indexing: '索引中', ready: '可检索', failed: '失败' }[status] || status)
const taskLabel = status => ({ queued: '等待', running: '监控中', cancelling: '停止中', completed: '已完成', failed: '失败', interrupted: '已中断', cancelled: '已停止' }[status] || status)
const taskType = status => status === 'running' ? 'success' : ['failed', 'interrupted'].includes(status) ? 'danger' : 'info'
const formatBytes = bytes => !bytes ? '0 MB' : bytes >= 1073741824 ? `${(bytes / 1073741824).toFixed(1)} GB` : `${(bytes / 1048576).toFixed(0)} MB`
const dateTime = value => value ? new Date(value).toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '未设置'
const dayLabel = value => { const date = new Date(value); const today = new Date(); const delta = Math.round((new Date(date.toDateString()) - new Date(today.toDateString())) / 86400000); return delta === 0 ? '今天' : delta === 1 ? '明天' : `${date.getMonth() + 1}/${date.getDate()}` }
const timeLabel = value => value ? new Date(value).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : ''
const fileIcon = name => ({ pdf: '📕', docx: '📘', pptx: '📙', md: '📝', markdown: '📝', html: '🌐' }[String(name).split('.').pop().toLowerCase()] || '📄')

onMounted(loadDashboard)
onActivated(loadDashboard)
</script>

<style scoped>
.dashboard-page { height: 100%; overflow-y: auto; box-sizing: border-box; padding: 28px 32px 36px; background: #f6f8fb; color: #1f2937; }
.dashboard-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 22px; }
.dashboard-header h1 { margin: 0 0 6px; font-size: 26px; }
.dashboard-header p { margin: 0; color: #6b7280; }
.summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin: 18px 0; }
.summary-card { border: 1px solid #e5e7eb; border-radius: 14px; background: white; padding: 16px 18px; text-align: left; cursor: pointer; box-shadow: 0 2px 8px rgba(15,23,42,.04); }
.summary-card:hover { transform: translateY(-1px); box-shadow: 0 7px 20px rgba(15,23,42,.08); }
.summary-card span,.summary-card small { display: block; color: #64748b; }.summary-card strong { display: block; font-size: 27px; margin: 8px 0 3px; }.summary-card.blue strong{color:#2563eb}.summary-card.amber strong{color:#d97706}.summary-card.red strong{color:#dc2626}.summary-card.green strong{color:#059669}
.dashboard-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.panel { background: white; border: 1px solid #e5e7eb; border-radius: 14px; padding: 17px; min-height: 210px; }
.panel-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }.panel-title h2 { margin: 0; font-size: 16px; }.panel-note{font-size:12px;color:#94a3b8}
.list-row { width: 100%; display: flex; align-items: center; gap: 10px; border: 0; border-top: 1px solid #f1f5f9; padding: 11px 2px; background: transparent; text-align: left; cursor: pointer; color: inherit; }.list-row:hover{background:#f8fafc}.static-row{cursor:default}.row-main{flex:1;min-width:0}.row-main b,.row-main small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.row-main b{font-size:13px;font-weight:600}.row-main small,.row-meta{font-size:11px;color:#8491a3;margin-top:3px}.date-badge{min-width:42px;padding:5px;border-radius:7px;background:#eff6ff;color:#2563eb;text-align:center;font-size:12px}.file-icon{font-size:19px}.status-dot{width:9px;height:9px;border-radius:50%;background:#f59e0b}.status-dot.failed,.status-dot.interrupted{background:#ef4444}.status-dot.running{background:#10b981;box-shadow:0 0 0 4px #d1fae5}.status-dot.completed{background:#3b82f6}
.health-bar { margin-top: 16px; display: flex; align-items: center; justify-content: space-between; background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 13px; padding: 15px 18px; }.health-bar.warning{background:#fff7ed;border-color:#fed7aa}.health-bar b,.health-bar span{display:block}.health-bar div>span{font-size:12px;color:#64748b;margin-top:3px}.health-numbers{display:flex;align-items:center;gap:22px}.health-numbers span{margin:0!important}
@media (max-width: 1050px){.summary-grid{grid-template-columns:repeat(2,1fr)}.dashboard-grid{grid-template-columns:1fr}}
</style>
