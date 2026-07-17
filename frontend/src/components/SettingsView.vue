<template>
  <div class="settings-container">
    <div class="header">
      <h2>⚙️ 引擎与模型设置</h2>
      <p class="subtitle">为您分虑 愿您无忧</p>
    </div>

    <el-card class="setting-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <el-icon><Document /></el-icon>
          <span>文档解析引擎</span>
        </div>
      </template>
      
      <div class="engine-setting-block">
        <div class="setting-label">选择解析内核：</div>
        <el-select 
          v-model="pdfEngine" 
          placeholder="请选择解析引擎" 
          class="engine-select"
          @change="handleEngineChange"
        >
          <el-option value="pymupdf" label="PyMuPDF">
            <span class="engine-title">PyMuPDF</span>
            <span class="engine-desc">默认 · 轻量级 · 扫描件 OCR 兜底</span>
          </el-option>
          <el-option value="marker" label="Marker">
            <span class="engine-title">Marker</span>
            <span class="engine-desc">平衡 · 适合批量多次快速提问</span>
          </el-option>
          <el-option value="mineru" label="MinerU">
            <span class="engine-title">MinerU</span>
            <span class="engine-desc">硬核 · 认真地回答 (死磕复杂排版)</span>
          </el-option>
        </el-select>
      </div>

      <!-- 已初始化引擎的运行设备徽标（不可编辑，只是展示） -->
      <div class="engine-setting-block" v-if="(pdfEngine === 'marker' || pdfEngine === 'mineru') && currentEngineDevice">
        <span class="device-badge">
          当前 {{ pdfEngine.toUpperCase() }} 已初始化为 {{ currentEngineDevice === 'cuda' ? 'GPU' : 'CPU' }} 运行
        </span>
      </div>

      <div class="setting-tip">提示：PDF 可使用全部引擎；DOCX/PPTX 会在选择 Marker/MinerU 时使用高级解析，Markdown 始终走轻量原生解析，HTML 仅 Marker 使用高级解析。</div>
    </el-card>

    <!-- ✨ 首次启用引擎：下载前的设备选择弹窗 -->
    <el-dialog
      v-model="deviceChoiceDialogVisible"
      title="选择运行设备"
      width="480px"
      :close-on-click-modal="false"
    >
      <p style="margin: 0 0 16px; color: #606266; font-size: 14px;">
        您是初次选择 <strong>{{ pendingEngine ? pendingEngine.toUpperCase() : '' }}</strong> 引擎，请选择该引擎的运行设备（选定后将开始下载对应版本的依赖，仅首次需要）：
      </p>
      <p v-if="currentEngineDevice" style="margin: 0 0 16px; color: #909399; font-size: 13px;">
        当前已验证为 {{ currentEngineDevice === 'cuda' ? 'GPU' : 'CPU' }}；选择新设备后会重新执行扫描件验证。
      </p>
      <el-radio-group v-model="useGpu" class="device-choice-group">
          <el-radio :value="true" class="device-choice-item">
            <div class="device-choice-title">GPU（CUDA）</div>
            <div class="device-choice-desc">适合 NVIDIA 显卡。若现有 PyTorch 不支持该显卡架构，系统会安装官方 CUDA 版 PyTorch 后进行真实扫描件验证；验证失败不会假装以 CPU 成功。</div>
          </el-radio>
          <el-radio :value="false" class="device-choice-item">
            <div class="device-choice-title">CPU<span class="recommend-tag">默认推荐</span></div>
            <div class="device-choice-desc">兼容性最好，几乎不会出兼容性问题，但解析速度明显更慢（一份几页的 PDF 可能要几分钟到十几分钟）。</div>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button @click="cancelDeviceChoice">取消</el-button>
        <el-button type="primary" @click="confirmDeviceChoice">开始下载</el-button>
      </template>
    </el-dialog>

    <!-- ✨ 引擎初始化下载进度弹窗 -->
    <el-dialog
      v-model="initDialogVisible"
      title="引擎初始化"
      width="560px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      :show-close="initDone"
    >
      <div class="init-log-box">
        <div v-for="(line, idx) in initLogs" :key="idx" class="init-log-line">{{ line }}</div>
      </div>
      <template #footer>
        <el-button v-if="initDone" type="primary" @click="initDialogVisible = false">完成</el-button>
        <el-button v-else-if="initFailed" type="warning" @click="initDialogVisible = false">关闭</el-button>
        <div v-else class="init-running-actions">
          <span class="init-progress-tip">
            {{ initCancelling ? '正在停止并清理子进程...' : '初始化正在进行，可随时安全取消' }}
          </span>
          <el-button
            type="danger"
            plain
            :loading="initCancelling"
            :disabled="initCancelling"
            @click="cancelEngineInit"
          >取消初始化</el-button>
        </div>
      </template>
    </el-dialog>

    <el-card class="setting-card" shadow="hover">
      <template #header>
        <div class="card-header">
          <el-icon><Cpu /></el-icon>
          <span>API配置</span>
        </div>
      </template>

      <div class="model-selector-area">
        <div class="setting-label">当前激活模型：</div>
        <el-select 
          v-model="activeModelName" 
          placeholder="请选择或添加模型" 
          class="model-select"
          no-data-text="暂无模型，请在下方添加"
        >
          <el-option 
            v-for="model in savedConfigs" 
            :key="model.name" 
            :label="model.name" 
            :value="model.name"
          >
            <div class="custom-option">
              <span class="model-name">{{ model.name }}</span>
              <div class="model-actions">
                <el-tag size="small" :type="model.type === 'cloud' ? 'primary' : 'success'" effect="light">
                  {{ model.type === 'cloud' ? 'Cloud' : 'Local' }}
                </el-tag>
                <el-button 
                  type="danger" 
                  circle 
                  size="small" 
                  text
                  @click.stop="confirmDeleteModel(model.name)"
                >
                  <el-icon><Close /></el-icon>
                </el-button>
              </div>
            </div>
          </el-option>
        </el-select>
      </div>

      <el-divider border-style="dashed" />

      <div class="add-model-area">
        <h4 class="form-title"><el-icon><Plus /></el-icon> 录入新模型</h4>
        <el-form label-position="top" size="small" class="new-model-form">
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="自定义标识名称 (不可重复)">
                <el-input v-model="newModel.name" placeholder="例：云端 DeepSeek-V3" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="模型类型">
                <el-radio-group v-model="newModel.type">
                  <el-radio-button label="cloud">☁️ Cloud (云端)</el-radio-button>
                  <el-radio-button label="local">💻 Local (本地)</el-radio-button>
                </el-radio-group>
              </el-form-item>
            </el-col>
          </el-row>
          
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="模型 ID (Model ID)">
                <el-input v-model="newModel.modelId" placeholder="例：deepseek-chat 或 qwen2.5:7b" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="API Base URL (接口地址)">
                <el-input v-model="newModel.baseUrl" placeholder="例：https://api.deepseek.com/v1" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item label="API Key (密钥 - Local 模型可填随意字符)">
            <el-input v-model="newModel.apiKey" type="password" show-password placeholder="sk-..." />
          </el-form-item>

          <el-button type="success" plain @click="saveNewModel">
            <el-icon><CirclePlus /></el-icon> 将此模型永久存入列表
          </el-button>
        </el-form>
      </div>
    </el-card>

    <div class="footer-actions">
      <el-button type="primary" size="large" @click="saveAllSettings">
        <el-icon><Select /></el-icon> 保存并激活当前配置
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { Document, Cpu, Select, Close, Plus, CirclePlus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { apiFetch } from '../api/client'

// --- 状态数据 ---
const pdfEngine = ref('pymupdf')
const previousEngine = ref('pymupdf') // 用于用户取消/下载失败时回退选择
const activeModelName = ref('')
const savedConfigs = ref([]) // 永久保存的模型列表

// --- 引擎初始化下载弹窗状态 ---
const initDialogVisible = ref(false)
const initLogs = ref([])
const initDone = ref(false)
const initFailed = ref(false)
const initCancelling = ref(false)
const initializingEngine = ref(null)
let initAbortController = null

// --- ✨ 新增：GPU/CPU 运行设备选择 ---
const useGpu = ref(false) // 默认 CPU，避免在 CUDA/PyTorch 不匹配时初始化失败
const currentEngineDevice = ref(null) // 当前选中引擎已初始化的设备，null 表示还没初始化过
const deviceChoiceDialogVisible = ref(false) // 下载前的设备选择弹窗
const pendingEngine = ref(null) // 正在等待用户选设备确认下载的引擎名
const ENGINE_INIT_SUCCESS_TOKEN = '___ENGINE_INIT_SUCCESS___'
const ENGINE_INIT_FAILURE_TOKEN = '___ENGINE_INIT_FAILED___'

// 新增模型的表单绑定数据
const newModel = ref({
  name: '',
  type: 'cloud', // 默认云端
  modelId: '',
  baseUrl: '',
  apiKey: ''
})

// --- 方法：查询某引擎在后端是否已经完成过初始化（同时拿到已使用的运行设备）---
const checkEngineStatus = async (engineValue) => {
  try {
    const res = await apiFetch(`/api/engine/status/${engineValue}`)
    const data = await res.json()
    if (!res.ok || typeof data.initialized !== 'boolean') {
      throw new Error(data.detail || `HTTP ${res.status}`)
    }
    return data // { engine, initialized, device }
  } catch (e) {
    console.error('查询引擎状态失败', e)
    return { engine: engineValue, initialized: false, device: null }
  }
}

// --- 方法：真正触发后端流式下载，并把进度实时塞进弹窗 ---
const runEngineInit = async (engineValue, gpuChoice) => {
  initLogs.value = []
  initDone.value = false
  initFailed.value = false
  initCancelling.value = false
  initializingEngine.value = engineValue
  initDialogVisible.value = true
  const controller = new AbortController()
  initAbortController = controller

  try {
    const res = await apiFetch(
      `/api/engine/init/${engineValue}?use_gpu=${gpuChoice}`,
      { signal: controller.signal, timeoutMs: 0 }
    )
    if (!res.ok || !res.body) {
      throw new Error(`后端初始化接口返回 HTTP ${res.status}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let pendingText = ''
    let receivedSuccess = false
    let receivedFailure = false

    const appendLines = (text, flush = false) => {
      pendingText += text
      const lines = pendingText.split('\n')
      pendingText = flush ? '' : lines.pop()
      lines.forEach((line) => {
        const normalizedLine = line.trimEnd()
        if (!normalizedLine.trim()) return
        if (normalizedLine.includes(ENGINE_INIT_SUCCESS_TOKEN)) {
          receivedSuccess = true
          return
        }
        if (normalizedLine.includes(ENGINE_INIT_FAILURE_TOKEN)) {
          receivedFailure = true
          return
        }
        initLogs.value.push(normalizedLine)
      })
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      appendLines(decoder.decode(value, { stream: true }))
    }
    appendLines(decoder.decode(), true)

    // 成功 token 只会在后端完成扫描 PDF -> 非空 Markdown 验证并写入标记后发出。
    const verifiedStatus = receivedSuccess && !receivedFailure
      ? await checkEngineStatus(engineValue)
      : { initialized: false, device: null }
    const expectedDevice = gpuChoice ? 'cuda' : 'cpu'
    if (!receivedSuccess || receivedFailure || !verifiedStatus.initialized || verifiedStatus.device !== expectedDevice) {
      if (!receivedFailure) {
        initLogs.value.push('[错误] 未收到后端初始化成功确认，不会启用该引擎。')
      }
      initFailed.value = true
      ElMessage.error(`${engineValue.toUpperCase()} 初始化失败，请查看弹窗中的日志排查`)
      pdfEngine.value = previousEngine.value // 回退选择
    } else {
      initDone.value = true
      previousEngine.value = engineValue
      currentEngineDevice.value = verifiedStatus.device
      ElMessage.success(`${engineValue.toUpperCase()} 初始化完成（${verifiedStatus.device === 'cuda' ? 'GPU' : 'CPU'}），可以开始使用！`)
    }
  } catch (e) {
    if (e?.name === 'AbortError') {
      initLogs.value.push('[取消] 初始化连接已关闭，后端正在回收相关进程。')
      initFailed.value = true
      pdfEngine.value = previousEngine.value
      ElMessage.info(`${engineValue.toUpperCase()} 初始化已取消`)
      return
    }
    initLogs.value.push(`[前端异常] 连接后端失败: ${e}`)
    initFailed.value = true
    pdfEngine.value = previousEngine.value
    ElMessage.error('无法连接后端，初始化失败')
  } finally {
    if (initAbortController === controller) initAbortController = null
    if (initializingEngine.value === engineValue) initializingEngine.value = null
    initCancelling.value = false
  }
}

// 用户不必被迫等待硬超时：先通知后端设置取消事件，再断开当前流。
// 后端无论收到显式取消还是浏览器断流，都会在 finally 中回收完整子进程树。
const cancelEngineInit = async () => {
  const engineValue = initializingEngine.value
  if (!engineValue || initCancelling.value) return
  initCancelling.value = true
  initLogs.value.push(`[取消] 正在请求安全停止 ${engineValue.toUpperCase()} 初始化...`)

  try {
    const res = await apiFetch(`/api/engine/cancel/${engineValue}`, {
      method: 'POST'
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`)
    initLogs.value.push(`[取消] ${data.message || '后端已收到取消请求'}。`)
  } catch (e) {
    initLogs.value.push(`[取消警告] 后端取消接口未确认：${e}；将通过断开流触发兜底清理。`)
  } finally {
    initAbortController?.abort()
  }
}

// --- 方法：PDF 引擎切换拦截（首次选中 Marker/MinerU 时弹出设备选择弹窗） ---
const handleEngineChange = async (engineValue) => {
  if (engineValue !== 'marker' && engineValue !== 'mineru') {
    previousEngine.value = engineValue
    currentEngineDevice.value = null
    return
  }

  const status = await checkEngineStatus(engineValue)
  if (status.initialized && status.device === 'cpu') {
    // 已验证过 CPU 的引擎仍可显式切换至 GPU；后端会重新跑扫描件探针。
    currentEngineDevice.value = status.device
    pendingEngine.value = engineValue
    useGpu.value = true
    deviceChoiceDialogVisible.value = true
    return
  }
  if (status.initialized) {
    // 已经初始化过，直接放行，不再弹窗、不再下载；把已用设备展示出来
    previousEngine.value = engineValue
    currentEngineDevice.value = status.device
    return
  }

  // 还没初始化过 → 弹出"选设备 + 确认下载"弹窗
  currentEngineDevice.value = null
  pendingEngine.value = engineValue
  useGpu.value = false // 每次弹出默认 CPU，用户可主动切换到 GPU
  deviceChoiceDialogVisible.value = true
}

// --- 方法：设备选择弹窗 - 确认，开始下载 ---
const confirmDeviceChoice = () => {
  deviceChoiceDialogVisible.value = false
  runEngineInit(pendingEngine.value, useGpu.value)
}

// --- 方法：设备选择弹窗 - 取消，回退引擎选择 ---
const cancelDeviceChoice = () => {
  deviceChoiceDialogVisible.value = false
  pdfEngine.value = previousEngine.value
  pendingEngine.value = null
}

// --- 方法：录入并永久保存新模型 ---
const saveNewModel = () => {
  if (!newModel.value.name || !newModel.value.modelId || !newModel.value.baseUrl) {
    ElMessage.warning('名称、模型ID、接口地址不能为空！')
    return
  }
  
  // 检查名字是否重复
  if (savedConfigs.value.find(c => c.name === newModel.value.name)) {
    ElMessage.error('该模型名称已存在，请换一个名称！')
    return
  }

  // 深拷贝压入列表
  savedConfigs.value.push(JSON.parse(JSON.stringify(newModel.value)))
  
  // 自动将新加的模型设置为当前激活状态
  activeModelName.value = newModel.value.name
  
  // 清空表单
  newModel.value = { name: '', type: 'cloud', modelId: '', baseUrl: '', apiKey: '' }
  
  // 立即将列表持久化到 localStorage
  syncToLocalStorage()
  ElMessage.success('模型已成功存入列表！')
}

// --- 方法：删除模型 (带警告) ---
const confirmDeleteModel = (targetName) => {
  ElMessageBox.confirm(
    `确定要永久移除名为 "${targetName}" 的模型配置吗？此操作无法撤销。`,
    '删除警告',
    {
      confirmButtonText: '确认删除',
      cancelButtonText: '取消',
      type: 'error',
    }
  ).then(() => {
    savedConfigs.value = savedConfigs.value.filter(c => c.name !== targetName)
    // 如果删除的是当前激活的模型，则清空激活状态
    if (activeModelName.value === targetName) {
      activeModelName.value = ''
    }
    syncToLocalStorage()
    ElMessage.success('模型配置已删除')
  }).catch(() => {}) // 取消不做操作
}

// --- 方法：数据持久化 ---
const syncToLocalStorage = () => {
  const dataToSave = {
    pdfEngine: pdfEngine.value,
    active: activeModelName.value,
    configs: savedConfigs.value
  }
  localStorage.setItem('rag_full_settings', JSON.stringify(dataToSave))
}

const saveAllSettings = () => {
  if (savedConfigs.value.length > 0 && !activeModelName.value) {
    ElMessage.warning('请在下拉框中指定一个要激活的模型！')
    return
  }
  syncToLocalStorage()
  ElMessage.success('配置已保存！知识库和聊天界面已应用最新设置。')
}

const loadSettings = () => {
  const savedData = localStorage.getItem('rag_full_settings')
  if (savedData) {
    try {
      const parsed = JSON.parse(savedData)
      if (parsed.pdfEngine) {
        // 兼容旧版保存的 pypdf 标识，实际引擎一直是 PyMuPDF。
        const normalizedEngine = parsed.pdfEngine === 'pypdf' ? 'pymupdf' : parsed.pdfEngine
        pdfEngine.value = normalizedEngine
        previousEngine.value = normalizedEngine
      }
      if (parsed.configs) savedConfigs.value = parsed.configs
      if (parsed.active) activeModelName.value = parsed.active
    } catch (e) {
      console.error('配置解析失败', e)
    }
  }
}

onMounted(async () => {
  loadSettings()
  // 页面刷新后，如果之前已经选中了 marker/mineru，把设备徽标补显示出来
  if (pdfEngine.value === 'marker' || pdfEngine.value === 'mineru') {
    const status = await checkEngineStatus(pdfEngine.value)
    if (status.initialized) {
      currentEngineDevice.value = status.device
      useGpu.value = status.device === 'cuda'
    }
  }
})

onBeforeUnmount(() => {
  // 用户切走设置页面时不让不可见的安装任务继续占用网络和磁盘。
  if (initializingEngine.value) {
    void apiFetch(`/api/engine/cancel/${initializingEngine.value}`, {
      method: 'POST'
    }).catch(() => {})
    initAbortController?.abort()
  }
})
</script>

<style scoped>
.settings-container {
  max-width: 800px;
  margin: 0 auto;
  padding: 30px;
  animation: fadeIn 0.3s ease-out;
}

.header { margin-bottom: 30px; }
.header h2 { margin: 0 0 8px 0; color: #303133; }
.subtitle { margin: 0; color: #909399; font-size: 14px; }

.setting-card { margin-bottom: 25px; border-radius: 10px; }
.card-header { display: flex; align-items: center; gap: 8px; font-weight: bold; font-size: 16px; color: #409EFF; }

/* 引擎设置区 */
.engine-setting-block { display: flex; align-items: center; gap: 15px; margin-bottom: 15px; }
.setting-label { font-size: 14px; color: #606266; font-weight: 500; }
.engine-select { width: 400px; }
.engine-title { float: left; font-weight: bold; }
.engine-desc { float: right; color: #909399; font-size: 12px; }
.setting-tip { font-size: 12px; color: #E6A23C; background: #fdf6ec; padding: 8px 12px; border-radius: 4px; }
.device-badge {
  display: inline-block;
  margin-left: 8px;
  font-size: 12px;
  color: #67c23a;
  background: #f0f9eb;
  padding: 2px 8px;
  border-radius: 10px;
}
.device-choice-group { display: flex; flex-direction: column; gap: 12px; width: 100%; }
.device-choice-item {
  align-items: flex-start;
  height: auto;
  white-space: normal;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px 14px;
  margin-right: 0;
  width: 100%;
  box-sizing: border-box;
}
.device-choice-title { font-weight: 600; color: #303133; margin-bottom: 4px; }
.device-choice-desc { font-size: 12px; color: #909399; line-height: 1.5; white-space: normal; }
.recommend-tag {
  display: inline-block;
  margin-left: 8px;
  font-size: 11px;
  font-weight: normal;
  color: #fff;
  background: #f56c6c;
  padding: 1px 6px;
  border-radius: 10px;
  vertical-align: middle;
}

/* 模型管理区 */
.model-selector-area { display: flex; align-items: center; gap: 15px; margin-bottom: 20px; }
.model-select { width: 400px; }

/* ✨ 下拉框内的自定义排版 */
.custom-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}
.model-name { font-weight: 500; }
.model-actions { display: flex; align-items: center; gap: 10px; }

/* 新增模型表单区 */
.add-model-area { background-color: #f8f9fa; padding: 20px; border-radius: 8px; border: 1px solid #ebeef5; }
.form-title { margin-top: 0; margin-bottom: 15px; color: #606266; display: flex; align-items: center; gap: 5px; }

.footer-actions { display: flex; justify-content: flex-end; margin-top: 30px; }

/* 引擎初始化下载弹窗 */
.init-log-box {
  max-height: 320px;
  overflow-y: auto;
  background: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Consolas', 'Courier New', monospace;
  font-size: 12px;
  padding: 12px 14px;
  border-radius: 6px;
  line-height: 1.6;
}
.init-log-line { white-space: pre-wrap; word-break: break-all; }
.init-progress-tip { color: #E6A23C; font-size: 13px; }
.init-running-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 14px;
  width: 100%;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
