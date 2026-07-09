<template>
  <div class="library-panel">
    <div class="header">
      <h3>📚 知识文库</h3>
      <el-button type="primary" size="small" plain @click="openFolderDialog">
        <el-icon><FolderAdd /></el-icon> 新建文件夹
      </el-button>
    </div>

    <div class="breadcrumb-container">
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

    <div class="explorer-container">
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
        @click="openPdf(file)"
      >
        <div class="item-info">
          <el-icon class="icon pdf-icon"><Document /></el-icon>
          <span class="name" :title="file.file_name">{{ file.file_name }}</span>
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
        check-strictly
        placeholder="请选择目标分类"
        style="width: 100%"
      />
      <template #footer>
        <el-button @click="moveDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitMoveFile">确认移动</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { FolderAdd, Folder, Document, Delete, Setting, Edit } from '@element-plus/icons-vue' // ✨ 导入 Edit 图标
import { ElMessage, ElMessageBox } from 'element-plus' // ✨ 导入 MessageBox 用于重命名输入框

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

// --- 数据获取与处理 ---
const buildTree = (items) => {
  const root = [{ id: 0, label: '根目录', value: 0, children: [] }];
  const lookup = {};
  items.forEach(item => {
    lookup[item.id] = { id: item.id, label: item.course_name, value: item.id, children: [] };
  });
  items.forEach(item => {
    if (item.parent_id && lookup[item.parent_id]) {
      lookup[item.parent_id].children.push(lookup[item.id]);
    } else {
      root.push(lookup[item.id]);
    }
  });
  return root;
}

const fetchFolders = async () => {
  const res = await fetch('http://127.0.0.1:8000/api/library/folders')
  allFolders.value = await res.json()
  treeData.value = buildTree(allFolders.value)
  localStorage.setItem('rag_library_tree', JSON.stringify(treeData.value))
}

const fetchFiles = async (folderId) => {
  const res = await fetch(`http://127.0.0.1:8000/api/library/files/${folderId}`)
  files.value = await res.json()
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

// --- 📁 文件夹的重命名与删除 (新核心逻辑) ---
const promptRenameFolder = (folder) => {
  ElMessageBox.prompt('请输入新的文件夹名称', '重命名文件夹', {
    confirmButtonText: '保存',
    cancelButtonText: '取消',
    inputValue: folder.course_name,
  }).then(async ({ value }) => {
    if (!value.trim() || value === folder.course_name) return;
    
    await fetch(`http://127.0.0.1:8000/api/library/folders/${folder.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_name: value })
    });
    
    ElMessage.success('重命名成功');
    await fetchFolders(); // 刷新全部数据
  }).catch(() => {});
}

const deleteFolder = async (folderId) => {
  const res = await fetch(`http://127.0.0.1:8000/api/library/folders/${folderId}`, { method: 'DELETE' });
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
  await fetch('http://127.0.0.1:8000/api/library/folders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ course_name: newFolderName.value, parent_id: currentFolderId.value })
  })
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
  await fetch(`http://127.0.0.1:8000/api/library/files/${currentMoveFile.value.id}/move`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ course_id: targetMoveFolderId.value })
  })
  ElMessage.success('文件位置已更新')
  moveDialogVisible.value = false
  fetchFiles(currentFolderId.value)
}

const deleteFile = async (fileId) => {
  const res = await fetch(`http://127.0.0.1:8000/api/library/files/${fileId}`, { method: 'DELETE' })
  if (res.ok) {
    ElMessage.success('课件及向量记忆已删除')
    fetchFiles(currentFolderId.value)
  }
}
// ✨ 新增：调用浏览器原生能力在新标签页秒开 PDF 文件
const openPdf = (file) => {
  const fileUrl = `http://127.0.0.1:8000/api/uploads/${encodeURIComponent(file.file_name)}`;
  window.open(fileUrl, '_blank');
}

onMounted(() => {
  fetchFolders()
  fetchFiles(0)
})
</script>

<style scoped>
.library-panel { width: 100%; height: 100%; display: flex; flex-direction: column; background: #ffffff; border-right: 1px solid #ebeef5; }
.header { padding: 15px 20px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #ebeef5; }
.header h3 { margin: 0; font-size: 16px; color: #303133; }

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
.item-info { display: flex; align-items: center; gap: 12px; overflow: hidden; }
.icon { font-size: 20px; }
.folder-icon { color: #E6A23C; } 
.pdf-icon { color: #F56C6C; }    
.name { font-size: 14px; color: #303133; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 300px; user-select: none; }

/* 找到并修改 .file-item 样式 */
.file-item { cursor: pointer; } /* ✨ 核心：让文件行也变成可点击的小手 */
.file-item:hover .name { color: #409EFF; } /* 悬浮时文件名变成深蓝色提示 */

/* 悬浮操作按钮区 */
.item-actions { opacity: 0; display: flex; gap: 8px; transition: opacity 0.2s; }
.explorer-item:hover .item-actions { opacity: 1; }
</style>