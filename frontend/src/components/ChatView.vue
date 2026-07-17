<template>
  <div class="chat-container">
    <aside class="conversation-sidebar">
      <div class="conversation-toolbar">
        <el-button type="primary" class="new-chat-button" @click="newConversation">＋ 新对话</el-button>
        <el-input v-model="conversationSearch" clearable placeholder="搜索历史问题" @input="debouncedLoadConversations" />
        <el-tree-select v-model="conversationCourseFilter" :data="retrievalFolderTree" node-key="value" check-strictly clearable placeholder="按课程筛选" @change="loadConversations" />
      </div>
      <el-scrollbar class="conversation-list">
        <button v-for="item in conversations" :key="item.id" class="conversation-item" :class="{ active: item.id === currentConversationId }" @click="openConversation(item.id)">
          <span class="conversation-title">{{ item.pinned ? '📌 ' : '' }}{{ item.title }}</span>
          <small>{{ item.course_name || scopeSummary(item.retrieval_scope) }} · {{ item.message_count || 0 }} 条</small>
        </button>
        <el-empty v-if="!conversations.length" description="还没有历史对话" :image-size="45" />
      </el-scrollbar>
    </aside>

    <div class="chat-main">
      <header class="chat-header">
        <div><b>{{ currentConversation?.title || '新对话' }}</b><small>{{ scopeSummary(currentScope) }}</small></div>
        <div v-if="currentConversationId" class="chat-header-actions">
          <el-button size="small" @click="renameConversation">重命名</el-button>
          <el-button size="small" @click="toggleConversationPin">{{ currentConversation?.pinned ? '取消固定' : '固定' }}</el-button>
          <el-dropdown @command="exportConversation">
            <el-button size="small">导出⌄</el-button>
            <template #dropdown><el-dropdown-menu><el-dropdown-item command="md">Markdown</el-dropdown-item><el-dropdown-item command="pdf">打印 / PDF</el-dropdown-item></el-dropdown-menu></template>
          </el-dropdown>
          <el-button size="small" type="danger" plain @click="removeConversation">删除</el-button>
        </div>
      </header>
      <el-scrollbar ref="scrollbarRef" class="message-list">
      <div class="message-center-wrapper">
        
        <div v-for="(msg, index) in messages" :key="index" class="message-block">
          <div class="avatar" :class="msg.role">
            <el-icon v-if="msg.role === 'assistant'"><Platform /></el-icon>
            <el-icon v-else><User /></el-icon>
          </div>
          <div class="message-content">
            <div class="author-name">{{ msg.role === 'assistant' ? 'RAG 引擎' : '你' }}</div>
            <div v-if="msg.role === 'assistant'" class="fact-label"><span>模型总结</span><span v-if="msg.sources?.length" class="source-fact-label">已关联原文事实</span></div>
            <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
            <div v-if="msg.insufficient" class="evidence-warning">
              当前资料范围缺少可靠依据。
              <el-button link type="primary" @click="retrievalScopeMode = 'all'">改为全部资料</el-button>
            </div>
            <div v-if="msg.role === 'assistant' && msg.sources?.length" class="source-list">
              <div class="source-list-title">引用来源</div>
              <button
                v-for="source in msg.sources"
                :key="`${source.reference_id}-${source.file_id}-${source.chunk_index}`"
                type="button"
                class="source-chip"
                @click="openSource(source)"
              >
                <el-icon><Document /></el-icon>
                <span>{{ source.file_name }}</span>
                <span v-if="sourceLocationLabel(source)">· {{ sourceLocationLabel(source) }}</span>
                <span v-if="source.score">· {{ Math.round(source.score * 100) }}%</span>
              </button>
            </div>
            <div v-if="msg.id" class="message-actions">
              <el-button link size="small" @click="toggleMessagePin(msg)">{{ msg.pinned ? '取消固定' : '固定回答' }}</el-button>
              <el-button v-if="msg.role === 'assistant'" link size="small" @click="regenerateMessage(index)">重新生成</el-button>
              <el-button link size="small" type="danger" @click="removeMessage(index, msg)">删除</el-button>
            </div>
          </div>
        </div>

      </div>
      </el-scrollbar>

    <div class="input-area">
      <div v-if="uploadLogs.length > 0" class="terminal-monitor">
        <div class="terminal-header">🔴 🟡 🟢 课件向量化控制台 (Terminal)</div>
        <div class="terminal-body" ref="terminalBodyRef">
          <div v-for="(log, idx) in uploadLogs" :key="idx" class="log-line">
            {{ log }}
          </div>
        </div>
      </div>

      <div class="retrieval-scope">
        <span class="scope-label">检索范围</span>
        <el-radio-group v-model="retrievalScopeMode" size="small" @change="handleScopeModeChange">
          <el-radio-button label="all">全部资料</el-radio-button>
          <el-radio-button label="course">指定课程</el-radio-button>
          <el-radio-button label="files">指定文件</el-radio-button>
        </el-radio-group>
        <el-tree-select
          v-if="retrievalScopeMode !== 'all'"
          v-model="retrievalCourseId"
          :data="retrievalFolderTree"
          node-key="value"
          check-strictly
          default-expand-all
          :render-after-expand="false"
          clearable
          placeholder="选择课程或根目录"
          class="scope-course-select"
          @change="handleScopeCourseChange"
        />
        <el-select
          v-if="retrievalScopeMode === 'files'"
          v-model="retrievalFileIds"
          multiple
          collapse-tags
          collapse-tags-tooltip
          :disabled="retrievalCourseId === null || retrievalCourseId === undefined"
          placeholder="选择一个或多个文件"
          class="scope-file-select"
        >
          <el-option
            v-for="file in retrievalFiles"
            :key="file.id"
            :label="file.file_name"
            :value="file.id"
          />
        </el-select>
      </div>

      <div
        class="input-box-wrapper"
        :class="{ 'is-disabled': loading || isUploading, 'is-dragging': isDraggingFiles }"
        @dragenter.prevent="handleDragEnter"
        @dragover.prevent="handleDragOver"
        @dragleave.prevent="handleDragLeave"
        @drop.prevent="handleFileDrop"
      >
        <div v-if="isDraggingFiles" class="drop-overlay">
          <el-icon><UploadFilled /></el-icon>
          <span>释放以导入文档</span>
        </div>
        <el-input
          v-model="userInput"
          type="textarea"
          :autosize="{ minRows: 1, maxRows: 8 }"
          placeholder="给课件知识库发送消息... (Shift + Enter 换行)"
          @keydown.enter="handleEnter"
          resize="none"
          class="claude-input"
          :disabled="loading || isUploading"
        />
        <div class="input-actions">
          
          <el-tooltip content="导入文档或网页" placement="top">
            <el-button circle plain size="small" :disabled="loading || isUploading" @click="openImportDialog">
              <el-icon><Paperclip /></el-icon>
            </el-button>
          </el-tooltip>

          <el-button 
            type="primary" 
            circle 
            size="small"
            :disabled="!userInput.trim() || loading || isUploading"
            :loading="loading"
            @click="sendMessage"
          >
            <el-icon><Position /></el-icon>
          </el-button>
        </div>
      </div>
      <div class="footer-tip">AI 可能会产生误导性信息，请核实重要内容。</div>
    </div>
    </div>

    <el-dialog
      v-model="uploadDialogVisible"
      title="导入知识文档"
      width="600px"
      center
      :close-on-click-modal="!isUploading"
      :close-on-press-escape="!isUploading"
      :show-close="!isUploading"
    >
      <el-tabs v-model="importMode" :disabled="isUploading" class="import-tabs">
        <el-tab-pane label="本地文件" name="files">
          <el-upload
            drag
            multiple
            action=""
            :auto-upload="false"
            :show-file-list="false"
            :on-change="handleFileSelect"
            :disabled="isUploading"
            accept=".pdf,.docx,.pptx,.md,.markdown,.html,.htm"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖拽文件到这里，或 <em>点击选择</em></div>
            <template #tip>
              <div class="el-upload__tip">支持 PDF、DOCX、PPTX、Markdown、HTML；单个文件不超过 100 MB</div>
            </template>
          </el-upload>
          <div class="folder-import-actions">
            <input ref="folderInputRef" type="file" webkitdirectory multiple hidden @change="handleFolderSelect" />
            <el-button size="small" @click="folderInputRef?.click()">选择整个文件夹</el-button>
            <el-button size="small" :type="watchedDirectoryHandle ? 'success' : 'default'" :disabled="!supportsFolderWatch" @click="chooseWatchedDirectory">{{ watchedDirectoryHandle ? `监控中：${watchedDirectoryHandle.name}` : '监控文件夹' }}</el-button>
            <span>将自动保留原文件夹层级</span>
          </div>

          <div v-if="pendingFiles.length" class="pending-file-list">
            <div v-for="item in pendingFiles" :key="item.key" class="pending-file-item" :title="item.error || ''">
              <div class="pending-file-info">
                <el-icon><Document /></el-icon>
                <div>
                  <div class="pending-file-name">{{ item.relativePath || item.file.name }}</div>
                  <div class="pending-file-meta">
                    {{ formatFileSize(item.file.size) }} · {{ documentTypeLabel(item.documentType) }}
                    <template v-if="item.estimate"> · 约 {{ item.estimate.pages ? item.estimate.pages + ' 页 / ' : '' }}{{ item.estimate.seconds }} 秒 · 占用 {{ formatFileSize(item.estimate.disk_bytes) }}</template>
                  </div>
                  <div v-if="item.duplicate" class="duplicate-hint">已存在完全相同文件：{{ item.duplicate.file_name }}，导入时将复用</div>
                  <div v-else-if="item.versions?.length" class="version-hint">检测到 {{ item.versions.length }} 个同名版本，将作为新版本导入</div>
                </div>
              </div>
              <div class="pending-file-status">
                <el-tag size="small" :type="importStatusType(item.status)">{{ importStatusLabel(item.status) }}</el-tag>
                <el-button v-if="item.status === 'failed' && !isUploading" text type="primary" @click="retryPendingFile(item)">重试</el-button>
                <el-button v-if="!isUploading" text type="danger" @click="removePendingFile(item.key)">移除</el-button>
              </div>
            </div>
          </div>
          <div v-if="pendingFiles.length" class="import-estimate-summary">共 {{ pendingFiles.length }} 个文件 · {{ formatFileSize(totalImportBytes) }} · 预计约 {{ totalImportSeconds }} 秒（实际取决于 OCR 与设备性能）</div>
        </el-tab-pane>

        <el-tab-pane label="网页链接" name="url">
          <el-input
            v-model="pendingUrl"
            placeholder="https://example.com/article"
            clearable
            :disabled="isUploading"
            @input="urlImportStatus = 'idle'"
          />
          <div class="url-security-tip">仅支持无需登录、服务端可直接访问的 HTTP/HTTPS 静态网页。</div>
          <el-tag v-if="urlImportStatus !== 'idle'" size="small" :type="importStatusType(urlImportStatus)">
            {{ importStatusLabel(urlImportStatus) }}
          </el-tag>
        </el-tab-pane>
      </el-tabs>

      <el-tree-select
        v-model="uploadTargetFolderId"
        :data="uploadTreeData"
        node-key="value"
        check-strictly
        default-expand-all
        :render-after-expand="false"
        placeholder="请选择要存放的分类 (默认未分类)"
        style="width: 100%"
        class="upload-target-select"
        :disabled="isUploading"
      />
      <template #footer>
        <el-button @click="uploadDialogVisible = false" :disabled="isUploading">取消</el-button>
        <el-button type="primary" @click="executeImport" :loading="isUploading" :disabled="!canStartImport">
          确认并导入
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewDialogVisible" :title="previewTitle" width="720px">
      <pre class="document-preview">{{ previewText }}</pre>
    </el-dialog>

    <el-drawer v-model="citationDrawerVisible" size="44%" direction="rtl" class="citation-drawer">
      <template #header><div><b>{{ citationData?.file?.file_name || activeSource?.file_name || '引用原文' }}</b><div class="citation-subtitle">{{ sourceLocationLabel(activeSource) }} · 相关度 {{ activeSource?.score ? Math.round(activeSource.score * 100) + '%' : '未评分' }}</div></div></template>
      <el-skeleton v-if="citationLoading" :rows="8" animated />
      <template v-else>
        <el-alert type="info" :closable="false" title="下面是知识库中的原文片段；回答正文属于模型总结。" />
        <section v-for="(chunk, index) in citationData?.chunks || []" :key="index" class="citation-chunk">
          <div class="citation-chunk-meta">{{ chunk.metadata?.section || '正文' }} · {{ sourceLocationLabel(chunk.metadata) }}</div>
          <div class="citation-text" v-html="highlightCitation(chunk.text)"></div>
        </section>
        <el-empty v-if="!citationData?.chunks?.length" description="未找到该引用的原文片段" />
        <section v-if="citationData?.related_files?.length" class="related-files"><h4>同一课程的相关资料</h4><el-tag v-for="file in citationData.related_files" :key="file.id" class="related-tag">{{ file.file_name }}</el-tag></section>
        <div class="citation-footer"><el-button @click="openOriginalSource">打开原文件并定位</el-button></div>
      </template>
    </el-drawer>

  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { Platform, User, Paperclip, Position, Document, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { buildFolderTree } from '../store/folderTree'
import { apiFetch, apiJson, apiUrl } from '../api/client'
import { loadImportQueue, saveImportQueue, loadWatchedDirectory, saveWatchedDirectory } from '../store/importQueue'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'
import MarkdownIt from 'markdown-it'
import texmath from 'markdown-it-texmath'
import katex from 'katex'
import 'katex/dist/katex.min.css'
const props = defineProps({ requestedConversationId: { type: String, default: '' } })
// ... 原有的 ref 变量下新增 ...
const uploadDialogVisible = ref(false)
const pendingFiles = ref([])
const pendingUrl = ref('')
const importMode = ref('files')
const urlImportStatus = ref('idle')
const isDraggingFiles = ref(false)
const previewDialogVisible = ref(false)
const previewTitle = ref('文档预览')
const previewText = ref('')
const uploadTargetFolderId = ref(0)
const uploadTreeData = ref([])
const retrievalScopeMode = ref('all')
const retrievalCourseId = ref(null)
const retrievalFileIds = ref([])
const retrievalFiles = ref([])
const retrievalFolderTree = ref([])
const folderInputRef = ref(null)
const uploadFolders = ref([])
const watchedDirectoryHandle = ref(null)
const watchedSnapshot = new Map()
const supportsFolderWatch = 'showDirectoryPicker' in window
let watchedDirectoryTimer = null
const conversations = ref([])
const currentConversationId = ref('')
const currentConversation = ref(null)
const conversationSearch = ref('')
const conversationCourseFilter = ref(null)
const citationDrawerVisible = ref(false)
const citationLoading = ref(false)
const citationData = ref(null)
const activeSource = ref(null)
let conversationSearchTimer = null

const currentScope = computed(() => ({
  mode: retrievalScopeMode.value,
  course_id: retrievalCourseId.value,
  file_ids: [...retrievalFileIds.value],
}))

const scopeSummary = scope => {
  if (!scope || scope.mode === 'all') return '全部资料'
  if (scope.mode === 'files') return `${scope.file_ids?.length || 0} 个指定文件`
  return '指定课程'
}

const loadConversations = async () => {
  const params = new URLSearchParams()
  if (conversationSearch.value.trim()) params.set('q', conversationSearch.value.trim())
  if (conversationCourseFilter.value !== null && conversationCourseFilter.value !== undefined) params.set('course_id', conversationCourseFilter.value)
  const payload = await apiJson(`/api/workspace/conversations${params.toString() ? `?${params}` : ''}`, { cache: 'no-store' })
  conversations.value = payload.conversations || []
  currentConversation.value = conversations.value.find(item => item.id === currentConversationId.value) || currentConversation.value
}

const debouncedLoadConversations = () => {
  clearTimeout(conversationSearchTimer)
  conversationSearchTimer = setTimeout(() => loadConversations().catch(error => ElMessage.error(error.message)), 250)
}

const applyConversationScope = async scope => {
  const normalized = scope || { mode: 'all' }
  retrievalScopeMode.value = normalized.mode || 'all'
  retrievalCourseId.value = normalized.course_id ?? null
  retrievalFileIds.value = normalized.file_ids || []
  if (retrievalCourseId.value !== null) await loadRetrievalFiles(retrievalCourseId.value)
}

const openConversation = async id => {
  if (!id || id === currentConversationId.value) return
  try {
    const data = await apiJson(`/api/workspace/conversations/${id}`, { cache: 'no-store' })
    currentConversationId.value = id
    currentConversation.value = data.conversation
    messages.value = data.messages || []
    await applyConversationScope(data.conversation.retrieval_scope)
    scrollToBottom()
  } catch (error) { ElMessage.error(error.message || '无法打开对话') }
}

const newConversation = () => {
  currentConversationId.value = ''
  currentConversation.value = null
  messages.value = [{ role: 'assistant', content: '新对话已准备好。检索范围会独立保存在本次对话中。' }]
  retrievalScopeMode.value = 'all'
  retrievalCourseId.value = null
  retrievalFileIds.value = []
}

const ensureConversation = async firstQuestion => {
  if (currentConversationId.value) return currentConversationId.value
  const title = String(firstQuestion || '新对话').replace(/\s+/g, ' ').slice(0, 32)
  const created = await apiJson('/api/workspace/conversations', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, course_id: retrievalCourseId.value || null, retrieval_scope: currentScope.value }),
  })
  currentConversationId.value = created.id
  currentConversation.value = created
  await loadConversations()
  return created.id
}

const saveMessage = async message => {
  if (!currentConversationId.value) return message
  const saved = await apiJson(`/api/workspace/conversations/${currentConversationId.value}/messages`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: message.role, content: message.content, sources: message.sources || [] }),
  })
  Object.assign(message, saved)
  return message
}

const renameConversation = async () => {
  try {
    const { value } = await ElMessageBox.prompt('输入新的对话标题', '重命名', { inputValue: currentConversation.value?.title || '', inputValidator: value => !!value.trim() || '标题不能为空' })
    currentConversation.value = await apiJson(`/api/workspace/conversations/${currentConversationId.value}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: value }) })
    await loadConversations()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || '重命名失败') }
}

const toggleConversationPin = async () => {
  const pinned = !currentConversation.value?.pinned
  currentConversation.value = await apiJson(`/api/workspace/conversations/${currentConversationId.value}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pinned }) })
  await loadConversations()
}

const removeConversation = async () => {
  try {
    await ElMessageBox.confirm('删除后无法恢复，确定删除这段对话吗？', '删除对话', { type: 'warning' })
    await apiJson(`/api/workspace/conversations/${currentConversationId.value}`, { method: 'DELETE' })
    newConversation()
    await loadConversations()
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || '删除失败') }
}

const exportConversation = async format => {
  if (format === 'md') {
    const response = await apiFetch(`/api/workspace/conversations/${currentConversationId.value}/export.md`)
    if (!response.ok) throw new Error(await parseHttpError(response))
    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `${currentConversation.value?.title || '对话'}.md`; anchor.click(); URL.revokeObjectURL(url)
    return
  }
  const safeTitle = md.utils.escapeHtml(currentConversation.value?.title || '对话')
  const body = messages.value.map(msg => `<h2>${msg.role === 'user' ? '你' : 'JiaYuan'}</h2>${renderMarkdown(msg.content)}`).join('')
  const html = `<html><head><meta charset="utf-8"><title>${safeTitle}</title><style>body{font:15px/1.7 system-ui;max-width:800px;margin:40px auto;padding:0 24px;color:#263244}pre{white-space:pre-wrap;background:#f5f5f5;padding:12px}h2{margin-top:28px;border-bottom:1px solid #ddd}</style></head><body><h1>${safeTitle}</h1>${body}</body></html>`
  if (window.jiayuanDesktop?.exportPdf) {
    const result = await window.jiayuanDesktop.exportPdf({ title: currentConversation.value?.title || '对话', html })
    if (!result?.canceled) ElMessage.success('PDF 已导出')
    return
  }
  const printWindow = window.open('', '_blank')
  if (!printWindow) return ElMessage.warning('浏览器阻止了打印窗口')
  printWindow.document.write(html)
  printWindow.document.close(); printWindow.print()
}

const toggleMessagePin = async msg => {
  const result = await apiJson(`/api/workspace/messages/${msg.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pinned: !msg.pinned }) })
  msg.pinned = result.pinned
}

const removeMessage = async (index, msg) => {
  try {
    await ElMessageBox.confirm('确定删除这条消息吗？', '删除消息', { type: 'warning' })
    await apiJson(`/api/workspace/messages/${msg.id}`, { method: 'DELETE' })
    messages.value.splice(index, 1)
  } catch (error) { if (error !== 'cancel' && error !== 'close') ElMessage.error(error.message || '删除失败') }
}

const regenerateMessage = async index => {
  const previous = [...messages.value.slice(0, index)].reverse().find(msg => msg.role === 'user')
  if (!previous) return
  const target = messages.value[index]
  if (target.id) await apiJson(`/api/workspace/messages/${target.id}`, { method: 'DELETE' })
  messages.value.splice(index, 1)
  await sendMessage(previous.content, true)
}

const SUPPORTED_DOCUMENT_TYPES = {
  pdf: 'PDF',
  docx: 'DOCX',
  pptx: 'PPTX',
  md: 'Markdown',
  markdown: 'Markdown',
  html: 'HTML',
  htm: 'HTML',
}
const MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
const totalImportBytes = computed(() => pendingFiles.value.reduce((sum, item) => sum + (item.estimate?.disk_bytes || item.file.size), 0))
const totalImportSeconds = computed(() => pendingFiles.value.reduce((sum, item) => sum + (item.estimate?.seconds || Math.max(2, Math.round(item.file.size / 1048576))), 0))

const documentTypeFromName = (name) => {
  const extension = String(name || '').split('.').pop()?.toLowerCase()
  return SUPPORTED_DOCUMENT_TYPES[extension] ? extension : null
}
const documentTypeLabel = (type) => SUPPORTED_DOCUMENT_TYPES[type] || type?.toUpperCase() || '未知格式'
const formatFileSize = (size) => {
  if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
const IMPORT_STATUS_LABELS = {
  idle: '等待导入',
  queued: '等待导入',
  processing: '解析入库中',
  ready: '已入库',
  failed: '失败',
}
const importStatusLabel = (status) => IMPORT_STATUS_LABELS[status] || status
const importStatusType = (status) => ({
  idle: 'info',
  queued: 'info',
  processing: 'warning',
  ready: 'success',
  failed: 'danger',
}[status] || 'info')

const loadRetrievalFolders = async () => {
  try {
    retrievalFolderTree.value = buildFolderTree(await apiJson('/api/library/folders'))
  } catch (error) {
    console.warn('加载检索范围失败:', error)
    retrievalFolderTree.value = [{ id: 0, label: '根目录', value: 0, children: [] }]
  }
}

const loadRetrievalFiles = async (courseId) => {
  if (courseId === null || courseId === undefined) {
    retrievalFiles.value = []
    return
  }
  retrievalFiles.value = await apiJson(`/api/library/files/${courseId}`)
}

const handleScopeModeChange = () => {
  if (retrievalScopeMode.value === 'all') {
    retrievalCourseId.value = null
    retrievalFileIds.value = []
    retrievalFiles.value = []
  }
}

const handleScopeCourseChange = async (courseId) => {
  retrievalFileIds.value = []
  try {
    await loadRetrievalFiles(courseId)
  } catch (error) {
    retrievalFiles.value = []
    ElMessage.error(error.message || '无法加载课程文件')
  }
}

const loadUploadTree = async () => {
  uploadFolders.value = await apiJson('/api/library/folders', { cache: 'no-store' })
  uploadTreeData.value = buildFolderTree(uploadFolders.value)
}

const openImportDialog = async () => {
  uploadDialogVisible.value = true
  try {
    await loadUploadTree()
  } catch (error) {
    uploadTreeData.value = buildFolderTree([])
    ElMessage.error(error.message || '无法加载存放目录')
  }
}

const calculateSha256 = async file => {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('')
}

const preflightPendingFile = async item => {
  try {
    const file_sha256 = await calculateSha256(item.file)
    const result = await apiJson('/api/rag/preflight', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_name: item.file.name, file_size: item.file.size, file_sha256, course_id: uploadTargetFolderId.value || 0 }),
    })
    item.fileSha256 = file_sha256
    item.estimate = result.estimate
    item.duplicate = result.exact_duplicate
    item.versions = result.same_name_versions || []
  } catch (error) {
    item.estimate = { pages: null, seconds: Math.max(2, Math.round(item.file.size / 1048576)), disk_bytes: Math.round(item.file.size * 1.35) }
    console.warn('导入预检失败，将继续允许导入:', error)
  }
  saveImportQueue(pendingFiles.value).catch(error => console.warn('保存导入队列失败:', error))
}

const addPendingFiles = (entries) => {
  const existingKeys = new Set(pendingFiles.value.map(item => item.key))
  const added = []
  for (const entry of entries) {
    const file = entry?.file || entry
    const relativePath = entry?.relativePath || file.webkitRelativePath || ''
    const documentType = documentTypeFromName(file.name)
    if (!documentType) {
      ElMessage.error(`${file.name}：不支持该格式`)
      continue
    }
    if (!file.size || file.size > MAX_DOCUMENT_BYTES) {
      ElMessage.error(`${file.name}：文件为空或超过 100 MB`)
      continue
    }
    const key = `${file.name}-${file.size}-${file.lastModified}`
    if (existingKeys.has(key)) continue
    existingKeys.add(key)
    const item = { key, file, documentType, relativePath, status: 'queued', error: '', estimate: null, duplicate: null, versions: [], targetFolderId: null }
    pendingFiles.value.push(item)
    added.push(item)
    preflightPendingFile(item)
  }
  saveImportQueue(pendingFiles.value).catch(error => ElMessage.warning(`暂存导入队列失败：${error.message}`))
  return added
}

const handleFileSelect = (uploadFile) => {
  if (uploadFile.raw) addPendingFiles([uploadFile.raw])
}

const handleFolderSelect = event => {
  addPendingFiles(Array.from(event.target.files || []).map(file => ({ file, relativePath: file.webkitRelativePath })))
  event.target.value = ''
}

const removePendingFile = (key) => {
  pendingFiles.value = pendingFiles.value.filter(item => item.key !== key)
  saveImportQueue(pendingFiles.value).catch(() => {})
}

const retryPendingFile = async item => {
  item.status = 'queued'; item.error = ''
  await executeImport([item])
}

const handleDragEnter = () => {
  if (!loading.value && !isUploading.value) isDraggingFiles.value = true
}
const handleDragOver = () => {
  if (!loading.value && !isUploading.value) isDraggingFiles.value = true
}
const handleDragLeave = (event) => {
  if (!event.currentTarget.contains(event.relatedTarget)) isDraggingFiles.value = false
}
const readEntry = async (entry, prefix = '') => {
  if (entry.isFile) return new Promise(resolve => entry.file(file => resolve([{ file, relativePath: `${prefix}${file.name}` }])))
  if (!entry.isDirectory) return []
  const children = await new Promise((resolve, reject) => {
    const reader = entry.createReader(); const all = []
    const read = () => reader.readEntries(items => { if (!items.length) resolve(all); else { all.push(...items); read() } }, reject)
    read()
  })
  const nested = await Promise.all(children.map(child => readEntry(child, `${prefix}${entry.name}/`)))
  return nested.flat()
}

const scanDirectoryHandle = async (handle, prefix = '') => {
  const entries = []
  for await (const child of handle.values()) {
    if (child.kind === 'file') {
      const file = await child.getFile()
      entries.push({ file, relativePath: `${prefix}${file.name}` })
    } else {
      entries.push(...await scanDirectoryHandle(child, `${prefix}${child.name}/`))
    }
  }
  return entries
}

const pollWatchedDirectory = async (initial = false) => {
  if (!watchedDirectoryHandle.value || isUploading.value) return
  try {
    const entries = await scanDirectoryHandle(watchedDirectoryHandle.value, `${watchedDirectoryHandle.value.name}/`)
    const changed = entries.filter(entry => {
      if (!documentTypeFromName(entry.file.name)) return false
      const signature = `${entry.file.size}-${entry.file.lastModified}`
      const old = watchedSnapshot.get(entry.relativePath)
      watchedSnapshot.set(entry.relativePath, signature)
      return !initial && old !== signature
    })
    if (changed.length) {
      importMode.value = 'files'
      const added = addPendingFiles(changed)
      if (added.length) {
        uploadDialogVisible.value = true
        await loadUploadTree()
        await executeImport(added)
      }
    }
  } catch (error) { console.warn('监控文件夹扫描失败:', error) }
}

const startWatchingDirectory = async handle => {
  watchedDirectoryHandle.value = handle
  watchedSnapshot.clear()
  await pollWatchedDirectory(true)
  clearInterval(watchedDirectoryTimer)
  watchedDirectoryTimer = setInterval(() => pollWatchedDirectory(false), 15000)
}

const chooseWatchedDirectory = async () => {
  try {
    const handle = await window.showDirectoryPicker({ mode: 'read' })
    await saveWatchedDirectory(handle)
    await startWatchingDirectory(handle)
    ElMessage.success('已开始监控；文件变化后会自动重新导入和索引')
  } catch (error) { if (error?.name !== 'AbortError') ElMessage.error(`无法监控文件夹：${error.message}`) }
}

const handleFileDrop = async event => {
  isDraggingFiles.value = false
  if (loading.value || isUploading.value) return
  const entries = Array.from(event.dataTransfer?.items || []).map(item => item.webkitGetAsEntry?.()).filter(Boolean)
  const files = entries.length ? (await Promise.all(entries.map(entry => readEntry(entry)))).flat() : Array.from(event.dataTransfer?.files || [])
  if (!files.length) return
  importMode.value = 'files'
  addPendingFiles(files)
  openImportDialog()
}

const currentDocumentEngine = () => {
  const savedSettings = localStorage.getItem('rag_full_settings')
  if (savedSettings) {
    try {
      return normalizePdfEngine(JSON.parse(savedSettings).pdfEngine)
    } catch {
      return 'pymupdf'
    }
  }
  return 'pymupdf'
}

const parseHttpError = async (response) => {
  const payload = await response.json().catch(() => ({}))
  return payload.detail || `后端返回 HTTP ${response.status}`
}

const ensureRelativeFolder = async item => {
  const parts = String(item.relativePath || '').replace(/\\/g, '/').split('/').filter(Boolean)
  parts.pop()
  let parentId = Number(item.targetFolderId ?? uploadTargetFolderId.value ?? 0)
  for (const name of parts) {
    const existing = uploadFolders.value.find(folder => Number(folder.parent_id || 0) === parentId && String(folder.course_name).toLowerCase() === name.toLowerCase())
    if (existing) { parentId = Number(existing.id); continue }
    const created = await apiJson('/api/library/folders', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ course_name: name, parent_id: parentId }),
    })
    parentId = Number(created.id)
    uploadFolders.value.push({ id: parentId, course_name: name, parent_id: Number(created.parent_id || 0) || null })
  }
  return parentId
}

const uploadOneDocument = async (item, engine) => {
  item.status = 'processing'
  item.error = ''
  await saveImportQueue(pendingFiles.value).catch(() => {})
  uploadLogs.value.push(`[队列] 开始导入：${item.file.name}`)
  const formData = new FormData()
  formData.append('file', item.file)
  formData.append('course_id', await ensureRelativeFolder(item))
  formData.append('engine', engine)
  const response = await apiFetch('/api/rag/upload', {
    method: 'POST',
    body: formData,
    timeoutMs: 0,
  })
  if (!response.ok) throw new Error(await parseHttpError(response))
  if (await readUploadResponse(response)) throw new Error('后端解析失败，请查看处理日志')
  item.status = 'ready'
  await saveImportQueue(pendingFiles.value).catch(() => {})
}

const importOneUrl = async (engine) => {
  urlImportStatus.value = 'processing'
  uploadLogs.value.push(`[队列] 开始导入网页：${pendingUrl.value.trim()}`)
  const response = await apiFetch('/api/rag/import-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url: pendingUrl.value.trim(),
      course_id: uploadTargetFolderId.value,
      engine,
    }),
    timeoutMs: 0,
  })
  if (!response.ok) throw new Error(await parseHttpError(response))
  if (await readUploadResponse(response)) throw new Error('网页解析失败，请查看处理日志')
  urlImportStatus.value = 'ready'
}

const sendImportNotification = (succeeded, failed) => {
  if (!('Notification' in window)) return
  const show = () => new Notification('JiaYuan 导入完成', { body: `成功 ${succeeded} 个，失败 ${failed} 个`, silent: false })
  if (Notification.permission === 'granted') show()
  else if (Notification.permission === 'default') Notification.requestPermission().then(permission => { if (permission === 'granted') show() })
}

const executeImport = async (selectedItems = null) => {
  if (!canStartImport.value) return
  isUploading.value = true
  uploadLogs.value = []
  const engine = currentDocumentEngine()
  let succeeded = 0
  let failed = 0

  try {
    if (importMode.value === 'files') {
      const queue = selectedItems || pendingFiles.value.filter(entry => entry.status !== 'ready')
      for (const item of queue) {
        try {
          await uploadOneDocument(item, engine)
          succeeded += 1
        } catch (error) {
          item.status = 'failed'
          item.error = error.message
          await saveImportQueue(pendingFiles.value).catch(() => {})
          failed += 1
          uploadLogs.value.push(`[致命错误] ❌ ${item.file.name}：${error.message}`)
        }
      }
    } else {
      try {
        await importOneUrl(engine)
        succeeded = 1
      } catch (error) {
        urlImportStatus.value = 'failed'
        failed = 1
        uploadLogs.value.push(`[致命错误] ❌ 网页导入失败：${error.message}`)
      }
    }

    if (succeeded) {
      ElMessage.success(`已成功入库 ${succeeded} 个文档`)
      await loadRetrievalFolders()
      if (
        retrievalScopeMode.value === 'files'
        && retrievalCourseId.value !== null
        && retrievalCourseId.value !== undefined
      ) {
        await loadRetrievalFiles(retrievalCourseId.value)
      }
    }
    if (failed) ElMessage.error(`${failed} 个文档导入失败，请检查日志`)
    sendImportNotification(succeeded, failed)
  } finally {
    isUploading.value = false
    setTimeout(() => {
      if (!isUploading.value) uploadLogs.value = []
    }, 8000)
  }
}

// --- Markdown 与 LaTeX 渲染配置 ---
const md = new MarkdownIt({
  // 检索内容和网页正文均属于不可信输入，禁止模型输出中的原生 HTML 进入 v-html。
  html: false,
  linkify: true,
  typographer: true,
  highlight: function (str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(str, { language: lang }).value; } catch { return '' }
    }
    return '';
  }
});

md.use(texmath, {
  engine: katex,
  delimiters: 'dollars',
  katexOptions: { throwOnError: false }
});

const renderMarkdown = (text) => {
  return md.render(text);
}

// --- 状态管理 ---
const userInput = ref('')
const scrollbarRef = ref(null)
const terminalBodyRef = ref(null)
const loading = ref(false) // 对话 loading
const isUploading = ref(false) // 上传 loading
const uploadLogs = ref([]) // 终端日志
const canStartImport = computed(() => {
  if (isUploading.value) return false
  if (importMode.value === 'files') {
    return pendingFiles.value.some(item => item.status !== 'ready')
  }
  return /^https?:\/\//i.test(pendingUrl.value.trim()) && urlImportStatus.value !== 'ready'
})

const normalizePdfEngine = (engine) => {
  if (!engine || engine === 'pypdf') return 'pymupdf'
  return engine
}

const buildRetrievePayload = (query) => {
  const payload = { query }
  if (retrievalScopeMode.value === 'all') return payload

  if (retrievalCourseId.value === null || retrievalCourseId.value === undefined) {
    throw new Error('请先选择要检索的课程或根目录')
  }

  payload.course_id = retrievalCourseId.value
  if (retrievalScopeMode.value === 'files') {
    if (!retrievalFileIds.value.length) {
      throw new Error('请至少选择一个要检索的文件')
    }
    payload.file_ids = retrievalFileIds.value
  }
  return payload
}

const sourceLocationLabel = (source) => {
  const index = source?.location_index || source?.page
  if (source?.location_type === 'page' && index) return `第 ${index} 页`
  if (source?.location_type === 'slide' && index) return `第 ${index} 张幻灯片`
  if (source?.section && source.section !== '正文') return `章节：${source.section}`
  if (source?.location_type === 'web_section' && index) return `网页章节 ${index}`
  return ''
}

const showDocumentPreview = async (source) => {
  const response = await apiFetch(`/api/library/documents/${source.file_id}/preview`)
  if (!response.ok) throw new Error(await parseHttpError(response))
  const data = await response.json()
  previewTitle.value = data.file_name || source.file_name || '文档预览'
  previewText.value = data.text || ''
  previewDialogVisible.value = true
}

const openSource = async (source) => {
  if (source?.source_kind === 'url' && source.source_url) {
    window.open(source.source_url, '_blank', 'noopener,noreferrer')
    return
  }
  if (!source?.file_id) return
  apiJson('/api/workspace/activity', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ item_type: 'file', item_id: String(source.file_id), title: source.file_name || '资料', course_id: source.course_id || null }),
  }).catch(() => {})
  activeSource.value = source
  citationDrawerVisible.value = true
  citationLoading.value = true
  citationData.value = null
  try {
    const params = new URLSearchParams()
    if (source.chunk_index !== null && source.chunk_index !== undefined) params.set('chunk_index', source.chunk_index)
    if (source.location_index || source.page) params.set('location_index', source.location_index || source.page)
    if (source.query) params.set('query', source.query)
    citationData.value = await apiJson(`/api/workspace/citations/${source.file_id}/context?${params}`)
  } catch (error) { ElMessage.error(error.message || '无法读取引用原文') }
  finally { citationLoading.value = false }
}

const highlightCitation = text => {
  let safe = md.utils.escapeHtml(String(text || ''))
  for (const term of citationData.value?.highlight_terms || []) {
    const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    safe = safe.replace(new RegExp(escaped, 'gi'), match => `<mark>${match}</mark>`)
  }
  return safe.replace(/\n/g, '<br>')
}

const openOriginalSource = () => {
  const source = activeSource.value
  if (!source?.file_id) return
  const locationIndex = source.location_index || source.page
  const pageFragment = source.document_type === 'pdf' && locationIndex ? `#page=${locationIndex}` : ''
  const url = apiUrl(`/api/library/documents/${source.file_id}/content${pageFragment}`)
  window.open(url, '_blank', 'noopener,noreferrer')
}

// StreamingResponse 一旦开始返回，后端业务异常仍然可能是 HTTP 200。
// 因此需要完整读取日志，以 [错误]/[致命异常] 作为最终成败信号。
const readUploadResponse = async (response) => {
  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let pendingText = ''
  let backendFailed = false

  const appendLines = (text, flush = false) => {
    pendingText += text
    const splitLines = pendingText.split('\n')
    pendingText = flush ? '' : splitLines.pop()
    const lines = splitLines
      .map(line => line.trimEnd())
      .filter(line => line.trim() !== '')

    if (lines.some(line => line.includes('[错误]') || line.includes('[致命异常]'))) {
      backendFailed = true
    }
    uploadLogs.value.push(...lines)

    nextTick(() => {
      if (terminalBodyRef.value) {
        terminalBodyRef.value.scrollTop = terminalBodyRef.value.scrollHeight
      }
    })
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    appendLines(decoder.decode(value, { stream: true }))
  }
  appendLines(decoder.decode(), true)
  return backendFailed
}

const messages = ref([
  {
    role: 'assistant',
    content: '你好！我是你专属的厦大_RAG助理。你可以拖入 PDF、DOCX、PPTX、Markdown、HTML，点击 📎 导入网页，或者直接向我提问。'
  }
])

// --- 🚀 核心功能 2：流式读取大模型对话 ---
const handleEnter = (e) => {
  if (!e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

const sendMessage = async (overrideText = null, reuseUser = false) => {
  const userText = String(overrideText ?? userInput.value).trim()
  if (!userText || loading.value || isUploading.value) return
  loading.value = true
  if (!reuseUser) {
    const userMessage = { role: 'user', content: userText }
    messages.value.push(userMessage)
    userInput.value = ''
    try {
      await ensureConversation(userText)
      await saveMessage(userMessage)
    } catch (error) {
      loading.value = false
      return ElMessage.error(`对话保存失败：${error.message}`)
    }
  }
  scrollToBottom()

  const savedSettings = localStorage.getItem('rag_full_settings');
  if (!savedSettings) {
    ElMessage.warning('请先去左侧“引擎与模型设置”中添加并激活模型！');
    loading.value = false
    return
  }

  const { configs, active } = JSON.parse(savedSettings);
  const currentConfig = configs.find(c => c.name === active);

  if (!currentConfig) {
    ElMessage.error('未找到当前激活的模型配置，请检查设置面板。');
    loading.value = false
    return
  }

  try {
    // 📢 步骤 A：拿着问题去本地知识库寻找相关课件片段
    const retrieveRes = await apiFetch('/api/rag/retrieve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildRetrievePayload(userText))
    });
    if (!retrieveRes.ok) throw new Error(`资料检索失败（HTTP ${retrieveRes.status}）。请检查资料是否已入库，或切换检索范围后重试。`)
    const retrieveData = await retrieveRes.json();
    if (retrieveData.has_sufficient_evidence === false) {
      const insufficientMessage = {
        role: 'assistant',
        content: retrieveData.message || '资料库没有足够依据',
        sources: [],
        insufficient: true,
      }
      messages.value.push(insufficientMessage)
      await saveMessage(insufficientMessage)
      await loadConversations()
      return
    }
    const context = retrieveData.context;

    // 📢 步骤 B：推入一个空的助理消息占位，准备接收流式数据
    const assistantMessage = {
      role: 'assistant',
      content: '',
      sources: (retrieveData.sources || []).map(source => ({ ...source, query: userText })),
    }
    messages.value.push(assistantMessage)
    const currentMsgIndex = messages.value.length - 1;

    // 📢 步骤 C：发起流式聊天请求
    const chatRes = await apiFetch('/api/chat/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: userText,
        config: {
          name: currentConfig.name,
          type: currentConfig.type,
          apiKey: currentConfig.apiKey,
          baseUrl: currentConfig.baseUrl,
          modelId: currentConfig.modelId
        },
        context: context
      }),
      timeoutMs: 0,
    });

    if (!chatRes.ok) throw new Error(`模型服务请求失败（HTTP ${chatRes.status}）。请到“引擎与模型设置”检查地址、密钥和模型名称。`)

    // 解析流式打字机效果
    const reader = chatRes.body.getReader();
    const decoder = new TextDecoder('utf-8');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      const chunk = decoder.decode(value, { stream: true });
      messages.value[currentMsgIndex].content += chunk;
      scrollToBottom();
    }
    await saveMessage(messages.value[currentMsgIndex])
    await loadConversations()

  } catch (error) {
    console.error("请求报错:", error);
    const errorMessage = { role: 'assistant', content: `处理失败：${error.message || '未知错误'}\n\n你可以重试本条回答，或调整检索范围后再次发送。`, sources: [] }
    messages.value.push(errorMessage)
    try { if (currentConversationId.value) await saveMessage(errorMessage) } catch { /* 原始错误优先展示 */ }
    ElMessage.error(error.message || '系统请求失败，请检查网络或后端状态。')
  } finally {
    loading.value = false
    scrollToBottom()
  }
}

const scrollToBottom = async () => {
  await nextTick();
  const scrollWrap = scrollbarRef.value?.wrapRef;
  if (scrollWrap) {
    scrollWrap.scrollTop = scrollWrap.scrollHeight;
  }
}

watch(currentScope, async scope => {
  if (!currentConversationId.value) return
  try {
    await apiJson(`/api/workspace/conversations/${currentConversationId.value}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ retrieval_scope: scope, course_id: scope.course_id || null }),
    })
  } catch (error) { console.warn('保存检索范围失败:', error) }
}, { deep: true })

watch(() => props.requestedConversationId, id => { if (id) openConversation(id) }, { immediate: true })

onMounted(async () => {
  await loadRetrievalFolders()
  await loadConversations()
  try {
    const restored = await loadImportQueue()
    if (restored.length) {
      pendingFiles.value = restored.map(item => ({ ...item, status: item.status === 'processing' ? 'queued' : item.status }))
      ElMessage.info(`已恢复 ${restored.length} 个上次未完成的导入文件`)
    }
  } catch (error) { console.warn('恢复导入队列失败:', error) }
  if (supportsFolderWatch) {
    try {
      const handle = await loadWatchedDirectory()
      if (handle && await handle.queryPermission({ mode: 'read' }) === 'granted') await startWatchingDirectory(handle)
    } catch (error) { console.warn('恢复监控文件夹失败:', error) }
  }
  if (props.requestedConversationId) await openConversation(props.requestedConversationId)
})
</script>

<style scoped>
.chat-container { display: flex; flex-direction: row; height: 100%; width: 100%; position: relative; }
.conversation-sidebar { width: 248px; min-width: 248px; display: flex; flex-direction: column; border-right: 1px solid #e5e7eb; background: #f8fafc; }
.conversation-toolbar { display: grid; gap: 9px; padding: 13px; border-bottom: 1px solid #e5e7eb; }
.new-chat-button { width: 100%; }
.conversation-list { flex: 1; padding: 8px; }
.conversation-item { display: block; width: 100%; border: 0; border-radius: 8px; background: transparent; padding: 10px; text-align: left; cursor: pointer; color: #334155; margin-bottom: 3px; }
.conversation-item:hover { background: #eef2f7; }
.conversation-item.active { background: #e0efff; color: #1d4ed8; }
.conversation-title { display: block; font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conversation-item small { display: block; color: #8491a3; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-main { min-width: 0; flex: 1; display: flex; flex-direction: column; }
.chat-header { height: 58px; box-sizing: border-box; padding: 10px 18px; border-bottom: 1px solid #eef0f3; display: flex; align-items: center; justify-content: space-between; gap: 14px; }
.chat-header b, .chat-header small { display: block; }
.chat-header small { font-size: 11px; color: #8b95a5; margin-top: 2px; }
.chat-header-actions { display: flex; gap: 6px; align-items: center; }
.message-list { flex: 1; padding: 20px 0; }
.message-center-wrapper { max-width: 800px; margin: 0 auto; padding: 0 20px; }
.message-block { display: flex; margin-bottom: 30px; animation: fadeIn 0.3s ease-out; }
.avatar { width: 28px; height: 28px; border-radius: 4px; display: flex; align-items: center; justify-content: center; margin-right: 16px; flex-shrink: 0; color: white; }
.avatar.assistant { background-color: #10a37f; }
.avatar.user { background-color: #707070; }
.message-content { flex: 1; overflow: hidden; }
.author-name { font-size: 14px; font-weight: 600; color: #333; margin-bottom: 4px; }
.markdown-body :deep(p) { margin-top: 0; line-height: 1.6; color: #374151; }
.markdown-body :deep(pre) { background-color: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }
.fact-label { display: flex; gap: 6px; margin-bottom: 7px; font-size: 10px; color: #64748b; }
.fact-label span { background: #f1f5f9; border-radius: 999px; padding: 2px 7px; }
.fact-label .source-fact-label { color: #047857; background: #ecfdf5; }
.message-actions { opacity: 0; display: flex; gap: 3px; margin-top: 5px; }
.message-block:hover .message-actions { opacity: 1; }
.evidence-warning { margin-top: 10px; border: 1px solid #fed7aa; background: #fff7ed; color: #9a3412; border-radius: 8px; padding: 9px 11px; font-size: 12px; }
.source-list { margin-top: 12px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.source-list-title { width: 100%; font-size: 12px; color: #71717a; }
.source-chip { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; border: 1px solid #bfdbfe; border-radius: 999px; padding: 5px 9px; background: #eff6ff; color: #1d4ed8; font-size: 12px; cursor: pointer; }
.source-chip:hover { background: #dbeafe; border-color: #93c5fd; }
.source-chip span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.input-area { padding: 20px; background: linear-gradient(0deg, white 60%, rgba(255,255,255,0)); }
.retrieval-scope { max-width: 800px; margin: 0 auto 10px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.scope-label { color: #71717a; font-size: 12px; white-space: nowrap; }
.scope-course-select { width: 190px; }
.scope-file-select { min-width: 190px; flex: 1; }
.input-box-wrapper { position: relative; max-width: 800px; margin: 0 auto; background-color: #f4f4f5; border-radius: 16px; padding: 10px; border: 1px solid #e4e4e7; transition: all 0.2s; }
.input-box-wrapper:focus-within { background-color: white; border-color: #d4d4d8; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
.input-box-wrapper.is-disabled { opacity: 0.7; cursor: not-allowed; }
.input-box-wrapper.is-dragging { border-color: #409eff; background: #ecf5ff; }
.drop-overlay { position: absolute; inset: 0; z-index: 5; display: flex; align-items: center; justify-content: center; gap: 8px; border: 2px dashed #409eff; border-radius: 16px; background: rgba(236, 245, 255, 0.96); color: #409eff; font-weight: 600; pointer-events: none; }
.claude-input :deep(.el-textarea__inner) { background: transparent; box-shadow: none; border: none; padding: 8px 12px; font-size: 15px; color: #333; }
.claude-input :deep(.el-textarea__inner:focus) { box-shadow: none; }
.input-actions { display: flex; justify-content: space-between; align-items: center; padding: 0 10px 4px 10px; margin-top: 8px; }
.footer-tip { text-align: center; font-size: 12px; color: #a1a1aa; margin-top: 12px; }
.import-tabs { margin-bottom: 18px; }
.import-tabs :deep(.el-upload), .import-tabs :deep(.el-upload-dragger) { width: 100%; }
.folder-import-actions { display: flex; align-items: center; gap: 9px; margin-top: 9px; color: #8491a3; font-size: 11px; }
.pending-file-list { max-height: 210px; margin-top: 14px; overflow-y: auto; border: 1px solid #ebeef5; border-radius: 8px; }
.pending-file-item { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 12px; border-bottom: 1px solid #f0f2f5; }
.pending-file-item:last-child { border-bottom: none; }
.pending-file-info { display: flex; align-items: center; gap: 9px; min-width: 0; }
.pending-file-name { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #303133; font-size: 13px; }
.pending-file-meta, .url-security-tip { margin-top: 3px; color: #909399; font-size: 11px; }
.duplicate-hint, .version-hint { margin-top: 3px; color: #b45309; font-size: 11px; }.duplicate-hint { color: #047857; }
.import-estimate-summary { margin: 9px 0 3px; color: #64748b; font-size: 11px; }
.pending-file-status { display: flex; align-items: center; flex: 0 0 auto; }
.url-security-tip { margin: 8px 0 12px; }
.upload-target-select { margin-top: 4px; }
.document-preview { max-height: 60vh; margin: 0; padding: 16px; overflow: auto; border-radius: 8px; background: #f7f8fa; color: #303133; font-family: inherit; font-size: 13px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }
.citation-subtitle { margin-top: 4px; font-size: 12px; color: #8491a3; }
.citation-chunk { margin-top: 14px; border: 1px solid #dbeafe; border-radius: 10px; overflow: hidden; }
.citation-chunk-meta { background: #eff6ff; color: #1d4ed8; padding: 7px 10px; font-size: 11px; }
.citation-text { padding: 13px; white-space: normal; word-break: break-word; line-height: 1.75; color: #334155; }
.citation-text :deep(mark) { background: #fde68a; padding: 1px 2px; border-radius: 2px; }
.related-files { margin-top: 20px; }
.related-tag { margin: 0 6px 6px 0; }
.citation-footer { position: sticky; bottom: 0; padding: 14px 0; background: white; text-align: right; }

/* ✨ 极客风控制台样式 */
.terminal-monitor { max-width: 800px; margin: 0 auto 15px auto; background-color: #1e1e1e; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.2); border: 1px solid #333; }
.terminal-header { background-color: #2d2d2d; color: #a1a1aa; padding: 8px 12px; font-size: 12px; font-family: monospace; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #333; }
.terminal-body { padding: 12px; max-height: 150px; overflow-y: auto; font-family: 'Courier New', Courier, monospace; font-size: 13px; color: #4ade80; line-height: 1.6; }
.log-line { border-left: 2px solid #4ade80; padding-left: 8px; margin-bottom: 4px; word-break: break-all; }

@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
@media (max-width: 900px) { .conversation-sidebar { width: 205px; min-width: 205px; } .chat-header-actions .el-button:nth-child(2) { display: none; } }
</style>

<style>
.katex { font-size: 1.2em; color: #000; }
</style>
