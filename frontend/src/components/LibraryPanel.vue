<template>
  <div class="library-panel">
    <div class="header">
      <div class="header-copy">
        <h3>📚 我的文库 </h3>
        <p class="subtitle">为您分虑 愿您无忧</p>
      </div>
      <el-button type="primary" size="small" plain @click="openFolderDialog">
        <el-icon><FolderAdd /></el-icon> 新建文件夹
      </el-button>
    </div>

    <div class="search-container">
      <el-input
        v-model="searchQuery"
        clearable
        placeholder="模糊搜索课程或文件，例如：电路原理"
        @input="scheduleSearch"
        @clear="resetSearch"
        @keyup.enter="searchLibrary"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <span class="search-hint">在整个文库中搜索</span>
    </div>

    <div v-if="!isSearchMode" class="breadcrumb-container">
      <el-breadcrumb separator="/">
        <el-breadcrumb-item 
          v-for="(step, index) in currentPath" 
          :key="step.id"
        >
          <a @click.prevent="navigateTo(index)" class="breadcrumb-link" :class="{ 'is-active': index === currentPath.length - 1 }">
            {{ step.course_name }}
          </a>
        </el-breadcrumb-item>
      </el-breadcrumb>
    </div>

    <div v-loading="searching" class="explorer-container">
      <template v-if="isSearchMode">
        <div v-if="!searching && searchResults.length === 0" class="empty-tip">
          未找到匹配项，可尝试缩短关键词或检查错字
        </div>

        <div
          v-for="result in searchResults"
          :key="`search-${result.type}-${result.id}`"
          class="explorer-item search-item"
          @click="openSearchResult(result)"
        >
          <div class="item-info">
            <el-icon v-if="result.type === 'folder'" class="icon folder-icon"><Folder /></el-icon>
            <el-icon v-else class="icon pdf-icon"><Document /></el-icon>
            <div class="file-summary">
              <span class="name" :title="result.name">{{ result.name }}</span>
              <div class="file-metadata">
                <el-tag size="small" effect="plain">
                  {{ result.type === 'folder' ? '课程' : '文件' }}
                </el-tag>
                <el-tag
                  v-if="result.type === 'file'"
                  size="small"
                  :type="statusTagType(result.status)"
                >
                  {{ statusLabel(result.status) }}
                </el-tag>
                <span class="search-path" :title="result.path">{{ result.path }}</span>
              </div>
            </div>
          </div>
          <span class="match-score">匹配 {{ Math.round(result.score * 100) }}%</span>
        </div>
      </template>

      <template v-else>
        <div v-if="visibleFolders.length === 0 && files.length === 0" class="empty-tip">
          当前目录为空
        </div>
        
        <div
          v-for="folder in visibleFolders"
          :key="'folder-' + folder.id"
          class="explorer-item folder-item"
          @click="enterFolder(folder)"
        >
          <div class="item-info">
            <el-icon class="icon folder-icon"><Folder /></el-icon>
            <span class="name">{{ folder.course_name }}</span>
          </div>

          <div class="item-actions">
            <el-button type="primary" circle size="small" plain class="action-btn" @click.stop="promptRenameFolder(folder)">
              <el-icon><Edit /></el-icon>
            </el-button>

            <el-popconfirm
              title="删除文件夹？(内部文件将退回根目录)"
              confirm-button-type="danger"
              @confirm="deleteFolder(folder.id)"
            >
              <template #reference>
                <el-button type="danger" circle size="small" plain class="action-btn" @click.stop>
                  <el-icon><Delete /></el-icon>
                </el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>

        <div
          v-for="file in files"
          :key="'file-' + file.id"
          class="explorer-item file-item"
          @click="openDocument(file)"
        >
          <div class="item-info">
            <el-icon class="icon pdf-icon"><Document /></el-icon>
            <div class="file-summary">
              <span class="name" :title="file.file_name">{{ file.file_name }}</span>
              <div class="file-metadata">
                <el-tooltip
                  v-if="file.status === 'failed'"
                  :content="file.error_message || '入库失败'"
                  placement="top"
                >
                  <el-tag size="small" :type="statusTagType(file.status)">
                    {{ statusLabel(file.status) }}
                  </el-tag>
                </el-tooltip>
                <el-tag v-else size="small" :type="statusTagType(file.status)">
                  {{ statusLabel(file.status) }}
              </el-tag>
              <span v-if="file.status === 'ready'" class="metric-text">
                  {{ formatUnitMetric(file) }} · {{ file.chunk_count || 0 }} 块
                  <template v-if="file.engine"> · {{ file.engine }}</template>
                  <template v-if="file.elapsed_ms"> · {{ formatElapsed(file.elapsed_ms) }}</template>
                </span>
              </div>
            </div>
          </div>
          
          <div class="item-actions">
            <el-button type="primary" circle size="small" plain class="action-btn" @click.stop="openMoveDialog(file)">
              <el-icon><Setting /></el-icon>
            </el-button>

            <el-popconfirm
              title="彻底删除该课件及向量记忆？"
              confirm-button-type="danger"
              @confirm="deleteFile(file.id)"
            >
              <template #reference>
                <el-button type="danger" circle size="small" plain class="action-btn" @click.stop>
                  <el-icon><Delete /></el-icon>
                </el-button>
              </template>
            </el-popconfirm>
          </div>
        </div>
      </template>
    </div>

    <el-dialog v-model="folderDialogVisible" title="新建文件夹" width="400px">
      <el-form label-position="top">
        <el-form-item label="文件夹名称">
          <el-input v-model="newFolderName" placeholder="例如：期末复习资料" @keydown.enter="submitNewFolder" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="folderDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitNewFolder">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="moveDialogVisible" title="更改文件存放位置" width="400px">
      <div style="margin-bottom: 15px; color: #606266;">
        正在移动: <strong>{{ currentMoveFile?.file_name }}</strong>
      </div>
      <el-tree-select
        v-model="targetMoveFolderId"
        :data="treeData"
        node-key="value"
        check-strictly
        default-expand-all
        :render-after-expand="false"
        placeholder="请选择目标分类"
        style="width: 100%"
      />
      <template #footer>
        <el-button @click="moveDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitMoveFile">确认移动</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewDialogVisible" :title="previewTitle" width="720px">
      <pre class="document-preview">{{ previewText }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { FolderAdd, Folder, Document, Delete, Setting, Edit, Search } from '@element-plus/icons-vue' // ✨ 导入 Edit 图标
import { ElMessage, ElMessageBox } from 'element-plus' // ✨ 导入 MessageBox 用于重命名输入框
import { buildFolderTree } from '../store/folderTree'
import { apiFetch, apiJson, apiUrl } from '../api/client'

// --- 核心状态 ---
const allFolders = ref([]) 
const files = ref([])
const currentPath = ref([{ id: 0, course_name: '根目录' }])
const currentFolderId = computed(() => currentPath.value[currentPath.value.length - 1].id)

const visibleFolders = computed(() => {
  return allFolders.value.filter(f => (f.parent_id || 0) === currentFolderId.value)
})

const treeData = ref([])
const folderDialogVisible = ref(false)
const moveDialogVisible = ref(false)
const currentMoveFile = ref(null)
const targetMoveFolderId = ref(0)
const newFolderName = ref('')
const previewDialogVisible = ref(false)
const previewTitle = ref('文档预览')
const previewText = ref('')
const searchQuery = ref('')
const searchResults = ref([])
const searching = ref(false)
const isSearchMode = computed(() => searchQuery.value.trim().length > 0)
let searchTimer = null
let searchRequestVersion = 0

const STATUS_LABELS = {
  uploaded: '已上传',
  parsing: '解析中',
  indexing: '索引中',
  ready: '可检索',
  failed: '失败',
}

const statusLabel = (status) => STATUS_LABELS[status] || '未知状态'
const statusTagType = (status) => ({
  uploaded: 'info',
  parsing: 'warning',
  indexing: 'warning',
  ready: 'success',
  failed: 'danger',
}[status] || 'info')
const formatElapsed = (elapsedMs) => {
  if (!elapsedMs) return '0 秒'
  if (elapsedMs < 1000) return `${elapsedMs} ms`
  return `${(elapsedMs / 1000).toFixed(1)} 秒`
}
const formatUnitMetric = (file) => {
  const count = file.unit_count || file.page_count || 0
  const labels = {
    page: '页',
    slide: '张幻灯片',
    heading: '个章节',
    web_section: '个网页章节',
  }
  return `${count} ${labels[file.unit_type] || '个单元'}`
}

// --- 数据获取与处理 ---
const fetchFolders = async () => {
  allFolders.value = await apiJson('/api/library/folders')
  treeData.value = buildFolderTree(allFolders.value)
}

const fetchFiles = async (folderId) => {
  files.value = await apiJson(`/api/library/files/${folderId}`)
}

const resetSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = null
  searchRequestVersion += 1
  searchResults.value = []
  searching.value = false
}

const searchLibrary = async () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = null
  const query = searchQuery.value.trim()
  if (!query) {
    resetSearch()
    return
  }

  const requestVersion = ++searchRequestVersion
  searching.value = true
  try {
    const data = await apiJson(`/api/library/search?q=${encodeURIComponent(query)}&limit=30`)
    if (requestVersion === searchRequestVersion && query === searchQuery.value.trim()) {
      searchResults.value = data.results || []
    }
  } catch (error) {
    if (requestVersion === searchRequestVersion) {
      searchResults.value = []
      ElMessage.error(error.message || '文库搜索失败')
    }
  } finally {
    if (requestVersion === searchRequestVersion) searching.value = false
  }
}

const scheduleSearch = () => {
  if (searchTimer) clearTimeout(searchTimer)
  if (!searchQuery.value.trim()) {
    resetSearch()
    return
  }
  searchTimer = setTimeout(searchLibrary, 250)
}

// --- 导航操作 ---
const enterFolder = (folder) => {
  currentPath.value.push(folder)
  fetchFiles(folder.id)
}
const navigateTo = (index) => {
  currentPath.value = currentPath.value.slice(0, index + 1)
  fetchFiles(currentFolderId.value)
}

const buildPathToFolder = (folderId) => {
  const lookup = new Map(allFolders.value.map(folder => [folder.id, folder]))
  const path = []
  const visited = new Set()
  let currentId = folderId
  while (currentId && !visited.has(currentId)) {
    visited.add(currentId)
    const folder = lookup.get(currentId)
    if (!folder) break
    path.unshift(folder)
    currentId = folder.parent_id || 0
  }
  return [{ id: 0, course_name: '根目录' }, ...path]
}

const openSearchResult = (result) => {
  if (result.type === 'file') {
    openDocument(result)
    return
  }
  searchQuery.value = ''
  resetSearch()
  currentPath.value = buildPathToFolder(result.id)
  fetchFiles(result.id)
}

// --- 📁 文件夹的重命名与删除 (新核心逻辑) ---
const promptRenameFolder = (folder) => {
  ElMessageBox.prompt('请输入新的文件夹名称', '重命名文件夹', {
    confirmButtonText: '保存',
    cancelButtonText: '取消',
    inputValue: folder.course_name,
  }).then(async ({ value }) => {
    if (!value.trim() || value === folder.course_name) return;
    
    await apiJson(`/api/library/folders/${folder.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: value })
    });
    
    ElMessage.success('重命名成功');
    await fetchFolders(); // 刷新全部数据
  }).catch(() => {});
}

const deleteFolder = async (folderId) => {
  const res = await apiFetch(`/api/library/folders/${folderId}`, { method: 'DELETE' });
  if (res.ok) {
    ElMessage.success('文件夹已删除，内部文件已退回上层');
    await fetchFolders();
    fetchFiles(currentFolderId.value); // 重新加载当前目录的文件
  }
}

// --- 其他原有操作 ---
const openFolderDialog = () => {
  newFolderName.value = ''
  folderDialogVisible.value = true
}

const submitNewFolder = async () => {
  if (!newFolderName.value.trim()) return
  const response = await apiFetch('/api/library/folders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ course_name: newFolderName.value, parent_id: currentFolderId.value })
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    ElMessage.error(data.detail || `文件夹创建失败（HTTP ${response.status}）`)
    return
  }
  ElMessage.success('文件夹创建成功')
  folderDialogVisible.value = false
  await fetchFolders()
}

const openMoveDialog = (file) => {
  currentMoveFile.value = file
  targetMoveFolderId.value = file.course_id || 0
  moveDialogVisible.value = true
}

const submitMoveFile = async () => {
  const response = await apiFetch(`/api/library/files/${currentMoveFile.value.id}/move`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ course_id: targetMoveFolderId.value })
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    ElMessage.error(data.detail || `文件移动失败（HTTP ${response.status}）`)
    return
  }
  ElMessage.success('文件位置已更新')
  moveDialogVisible.value = false
  fetchFiles(currentFolderId.value)
}

const deleteFile = async (fileId) => {
  const res = await apiFetch(`/api/library/files/${fileId}`, { method: 'DELETE' })
  if (res.ok) {
    ElMessage.success('课件及向量记忆已删除')
    fetchFiles(currentFolderId.value)
  }
}
const openDocument = async (file) => {
  if (file.source_kind === 'url' && file.source_url) {
    window.open(file.source_url, '_blank', 'noopener,noreferrer')
    return
  }
  if (['markdown', 'html'].includes(file.document_type)) {
    try {
      const response = await apiFetch(`/api/library/documents/${file.id}/preview`)
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(data.detail || `预览失败（HTTP ${response.status}）`)
      previewTitle.value = data.file_name || file.file_name
      previewText.value = data.text || ''
      previewDialogVisible.value = true
    } catch (error) {
      ElMessage.error(error.message || '无法打开文档预览')
    }
    return
  }
  const fileUrl = apiUrl(`/api/library/documents/${file.id}/content`)
  window.open(fileUrl, '_blank', 'noopener,noreferrer')
}

onMounted(() => {
  fetchFolders()
  fetchFiles(0)
})

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<style scoped>
.library-panel { width: 100%; height: 100%; display: flex; flex-direction: column; background: #ffffff; border-right: 1px solid #ebeef5; }
.header { padding: 15px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #ebeef5; }
.header-copy { display: flex; flex-direction: column; align-items: flex-start; gap: 5px; }
.header h3 { margin: 0; font-size: 16px; color: #303133; }
.header .subtitle { margin: 0; color: #909399; font-size: 13px; font-weight: 400; line-height: 1.4; white-space: nowrap; }

.search-container { padding: 12px 20px 9px; border-bottom: 1px solid #ebeef5; }
.search-hint { display: block; margin-top: 5px; color: #a0a4ac; font-size: 11px; }

.breadcrumb-container { padding: 12px 20px; background-color: #f8f9fa; border-bottom: 1px solid #ebeef5; }
.breadcrumb-link { cursor: pointer; font-weight: 500; color: #606266; transition: color 0.2s; }
.breadcrumb-link:hover { color: #409EFF; }
.breadcrumb-link.is-active { color: #303133; cursor: default; }

.explorer-container { flex: 1; overflow-y: auto; padding: 10px; }
.empty-tip { text-align: center; color: #909399; font-size: 14px; margin-top: 40px; }

.explorer-item { 
  display: flex; justify-content: space-between; align-items: center; 
  padding: 12px 15px; border-bottom: 1px solid #f0f2f5; border-radius: 6px;
  margin-bottom: 2px; transition: all 0.2s; 
}
.explorer-item:hover { background-color: #f5f7fa; }
.item-info { display: flex; align-items: center; gap: 12px; overflow: hidden; min-width: 0; }
.icon { font-size: 20px; }
.folder-icon { color: #E6A23C; } 
.pdf-icon { color: #F56C6C; }    
.name { font-size: 14px; color: #303133; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 300px; user-select: none; }
.file-summary { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.file-metadata { display: flex; align-items: center; gap: 7px; min-height: 20px; }
.metric-text { color: #909399; font-size: 11px; white-space: nowrap; }
.search-item { cursor: pointer; }
.search-item:hover .name { color: #409EFF; }
.search-path { color: #909399; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 230px; }
.match-score { flex: 0 0 auto; margin-left: 10px; color: #909399; font-size: 11px; }
.document-preview { max-height: 60vh; margin: 0; padding: 16px; overflow: auto; border-radius: 8px; background: #f7f8fa; color: #303133; font-family: inherit; font-size: 13px; line-height: 1.7; white-space: pre-wrap; word-break: break-word; }

/* 找到并修改 .file-item 样式 */
.file-item { cursor: pointer; } /* ✨ 核心：让文件行也变成可点击的小手 */
.file-item:hover .name { color: #409EFF; } /* 悬浮时文件名变成深蓝色提示 */

/* 悬浮操作按钮区 */
.item-actions { opacity: 0; display: flex; gap: 8px; transition: opacity 0.2s; }
.explorer-item:hover .item-actions { opacity: 1; }
</style>
