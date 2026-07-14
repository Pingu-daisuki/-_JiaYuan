<template>
  <div class="chat-container">
    <el-scrollbar ref="scrollbarRef" class="message-list">
      <div class="message-center-wrapper">
        
        <div v-for="(msg, index) in messages" :key="index" class="message-block">
          <div class="avatar" :class="msg.role">
            <el-icon v-if="msg.role === 'assistant'"><Platform /></el-icon>
            <el-icon v-else><User /></el-icon>
          </div>
          <div class="message-content">
            <div class="author-name">{{ msg.role === 'assistant' ? 'RAG 引擎' : '你' }}</div>
            <div class="markdown-body" v-html="renderMarkdown(msg.content)"></div>
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
              </button>
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
          check-strictly
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

          <div v-if="pendingFiles.length" class="pending-file-list">
            <div v-for="item in pendingFiles" :key="item.key" class="pending-file-item" :title="item.error || ''">
              <div class="pending-file-info">
                <el-icon><Document /></el-icon>
                <div>
                  <div class="pending-file-name">{{ item.file.name }}</div>
                  <div class="pending-file-meta">{{ formatFileSize(item.file.size) }} · {{ documentTypeLabel(item.documentType) }}</div>
                </div>
              </div>
              <div class="pending-file-status">
                <el-tag size="small" :type="importStatusType(item.status)">{{ importStatusLabel(item.status) }}</el-tag>
                <el-button v-if="!isUploading" text type="danger" @click="removePendingFile(item.key)">移除</el-button>
              </div>
            </div>
          </div>
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
        check-strictly
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

  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted } from 'vue'
import { Platform, User, Paperclip, Position, Document, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'
import MarkdownIt from 'markdown-it'
import texmath from 'markdown-it-texmath'
import katex from 'katex'
import 'katex/dist/katex.min.css'
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

const buildRetrievalFolderTree = (folders) => {
  const root = [{ id: 0, label: '根目录', value: 0, children: [] }]
  const lookup = {}
  folders.forEach((folder) => {
    lookup[folder.id] = {
      id: folder.id,
      label: folder.course_name,
      value: folder.id,
      children: [],
    }
  })
  folders.forEach((folder) => {
    if (folder.parent_id && lookup[folder.parent_id]) {
      lookup[folder.parent_id].children.push(lookup[folder.id])
    } else {
      root.push(lookup[folder.id])
    }
  })
  return root
}

const loadRetrievalFolders = async () => {
  try {
    const response = await fetch('http://127.0.0.1:8000/api/library/folders')
    if (!response.ok) throw new Error('无法加载课程目录')
    retrievalFolderTree.value = buildRetrievalFolderTree(await response.json())
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
  const response = await fetch(`http://127.0.0.1:8000/api/library/files/${courseId}`)
  if (!response.ok) throw new Error('无法加载课程文件')
  retrievalFiles.value = await response.json()
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

const loadUploadTree = () => {
  const cachedTree = localStorage.getItem('rag_library_tree')
  if (cachedTree) {
    try {
      uploadTreeData.value = JSON.parse(cachedTree)
    } catch {
      uploadTreeData.value = [{ id: 0, label: '根目录', value: 0, children: [] }]
    }
  } else {
    uploadTreeData.value = [{ id: 0, label: '根目录', value: 0, children: [] }]
  }
}

const openImportDialog = () => {
  loadUploadTree()
  uploadDialogVisible.value = true
}

const addPendingFiles = (files) => {
  const existingKeys = new Set(pendingFiles.value.map(item => item.key))
  for (const file of files) {
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
    pendingFiles.value.push({ key, file, documentType, status: 'queued', error: '' })
  }
}

const handleFileSelect = (uploadFile) => {
  if (uploadFile.raw) addPendingFiles([uploadFile.raw])
}

const removePendingFile = (key) => {
  pendingFiles.value = pendingFiles.value.filter(item => item.key !== key)
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
const handleFileDrop = (event) => {
  isDraggingFiles.value = false
  if (loading.value || isUploading.value) return
  const files = Array.from(event.dataTransfer?.files || [])
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

const uploadOneDocument = async (item, engine) => {
  item.status = 'processing'
  uploadLogs.value.push(`[队列] 开始导入：${item.file.name}`)
  const formData = new FormData()
  formData.append('file', item.file)
  formData.append('course_id', uploadTargetFolderId.value)
  formData.append('engine', engine)
  const response = await fetch('http://127.0.0.1:8000/api/rag/upload', {
    method: 'POST',
    body: formData,
  })
  if (!response.ok) throw new Error(await parseHttpError(response))
  if (await readUploadResponse(response)) throw new Error('后端解析失败，请查看处理日志')
  item.status = 'ready'
}

const importOneUrl = async (engine) => {
  urlImportStatus.value = 'processing'
  uploadLogs.value.push(`[队列] 开始导入网页：${pendingUrl.value.trim()}`)
  const response = await fetch('http://127.0.0.1:8000/api/rag/import-url', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      url: pendingUrl.value.trim(),
      course_id: uploadTargetFolderId.value,
      engine,
    }),
  })
  if (!response.ok) throw new Error(await parseHttpError(response))
  if (await readUploadResponse(response)) throw new Error('网页解析失败，请查看处理日志')
  urlImportStatus.value = 'ready'
}

const executeImport = async () => {
  if (!canStartImport.value) return
  isUploading.value = true
  uploadLogs.value = []
  const engine = currentDocumentEngine()
  let succeeded = 0
  let failed = 0

  try {
    if (importMode.value === 'files') {
      for (const item of pendingFiles.value.filter(entry => entry.status !== 'ready')) {
        try {
          await uploadOneDocument(item, engine)
          succeeded += 1
        } catch (error) {
          item.status = 'failed'
          item.error = error.message
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
  const response = await fetch(`http://127.0.0.1:8000/api/library/documents/${source.file_id}/preview`)
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
  if (['markdown', 'html'].includes(source.document_type)) {
    try {
      await showDocumentPreview(source)
    } catch (error) {
      ElMessage.error(error.message || '无法打开文档预览')
    }
    return
  }
  const locationIndex = source.location_index || source.page
  const pageFragment = source.document_type === 'pdf' && locationIndex ? `#page=${locationIndex}` : ''
  const url = `http://127.0.0.1:8000/api/library/documents/${source.file_id}/content${pageFragment}`
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
    content: '你好！我是你的本地 RAG 课件助理。你可以拖入 PDF、DOCX、PPTX、Markdown、HTML，点击 📎 导入网页，或者直接向我提问。'
  }
])

// --- 🚀 核心功能 2：流式读取大模型对话 ---
const handleEnter = (e) => {
  if (!e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

const sendMessage = async () => {
  if (!userInput.value.trim() || loading.value || isUploading.value) return;
  
  const userText = userInput.value;
  messages.value.push({ role: 'user', content: userText });
  userInput.value = '';
  loading.value = true;
  scrollToBottom();

  const savedSettings = localStorage.getItem('rag_full_settings');
  if (!savedSettings) {
    ElMessage.warning('请先去左侧“引擎与模型设置”中添加并激活模型！');
    loading.value = false;
    return;
  }

  const { configs, active } = JSON.parse(savedSettings);
  const currentConfig = configs.find(c => c.name === active);

  if (!currentConfig) {
    ElMessage.error('未找到当前激活的模型配置，请检查设置面板。');
    loading.value = false;
    return;
  }

  try {
    // 📢 步骤 A：拿着问题去本地知识库寻找相关课件片段
    const retrieveRes = await fetch('http://127.0.0.1:8000/api/rag/retrieve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildRetrievePayload(userText))
    });
    if (!retrieveRes.ok) throw new Error(`检索失败: ${retrieveRes.statusText}`)
    const retrieveData = await retrieveRes.json();
    if (retrieveData.has_sufficient_evidence === false) {
      messages.value.push({
        role: 'assistant',
        content: retrieveData.message || '资料库没有足够依据',
        sources: []
      })
      return
    }
    const context = retrieveData.context;

    // 📢 步骤 B：推入一个空的助理消息占位，准备接收流式数据
    messages.value.push({
      role: 'assistant',
      content: '',
      sources: retrieveData.sources || []
    });
    const currentMsgIndex = messages.value.length - 1;

    // 📢 步骤 C：发起流式聊天请求
    const chatRes = await fetch('http://127.0.0.1:8000/api/chat/', {
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
      })
    });

    if (!chatRes.ok) throw new Error(`大模型请求失败: ${chatRes.statusText}`);

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

  } catch (error) {
    console.error("请求报错:", error);
    ElMessage.error(error.message || '系统请求失败，请检查网络或后端状态。');
  } finally {
    loading.value = false;
    scrollToBottom();
  }
}

const scrollToBottom = async () => {
  await nextTick();
  const scrollWrap = scrollbarRef.value?.wrapRef;
  if (scrollWrap) {
    scrollWrap.scrollTop = scrollWrap.scrollHeight;
  }
}

onMounted(() => {
  loadRetrievalFolders()
})
</script>

<style scoped>
.chat-container { display: flex; flex-direction: column; height: 100%; width: 100%; position: relative; }
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
.pending-file-list { max-height: 210px; margin-top: 14px; overflow-y: auto; border: 1px solid #ebeef5; border-radius: 8px; }
.pending-file-item { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 10px 12px; border-bottom: 1px solid #f0f2f5; }
.pending-file-item:last-child { border-bottom: none; }
.pending-file-info { display: flex; align-items: center; gap: 9px; min-width: 0; }
.pending-file-name { max-width: 320px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #303133; font-size: 13px; }
.pending-file-meta, .url-security-tip { margin-top: 3px; color: #909399; font-size: 11px; }
.pending-file-status { display: flex; align-items: center; flex: 0 0 auto; }
.url-security-tip { margin: 8px 0 12px; }
.upload-target-select { margin-top: 4px; }
.document-preview { max-height: 60vh; margin: 0; padding: 16px; overflow: auto; border-radius: 8px; background: #f7f8fa; color: #303133; font-family: inherit; font-size: 13px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }

/* ✨ 极客风控制台样式 */
.terminal-monitor { max-width: 800px; margin: 0 auto 15px auto; background-color: #1e1e1e; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.2); border: 1px solid #333; }
.terminal-header { background-color: #2d2d2d; color: #a1a1aa; padding: 8px 12px; font-size: 12px; font-family: monospace; display: flex; align-items: center; gap: 8px; border-bottom: 1px solid #333; }
.terminal-body { padding: 12px; max-height: 150px; overflow-y: auto; font-family: 'Courier New', Courier, monospace; font-size: 13px; color: #4ade80; line-height: 1.6; }
.log-line { border-left: 2px solid #4ade80; padding-left: 8px; margin-bottom: 4px; word-break: break-all; }

@keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
</style>

<style>
.katex { font-size: 1.2em; color: #000; }
</style>
