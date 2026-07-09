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

      <div class="input-box-wrapper" :class="{ 'is-disabled': loading || isUploading }">
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
          
          <el-upload
            action=""
            :auto-upload="false" 
            :show-file-list="false"
            :on-change="handleFileSelect"
            :disabled="loading || isUploading"
            accept=".pdf"
          >
            <el-tooltip content="上传本地课件" placement="top">
              <el-button circle plain size="small" :disabled="loading || isUploading">
                <el-icon><Paperclip /></el-icon>
              </el-button>
            </el-tooltip>
          </el-upload>

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

    <el-dialog v-model="uploadDialogVisible" title="选择入库位置" width="400px" center>
      <div style="text-align: center; margin-bottom: 20px; color: #606266;">
        <el-icon class="is-loading" v-if="isUploading"><Loading /></el-icon>
        即将导入: <strong>{{ pendingFile?.name }}</strong>
      </div>
      <el-tree-select
        v-model="uploadTargetFolderId"
        :data="uploadTreeData"
        check-strictly
        placeholder="请选择要存放的分类 (默认未分类)"
        style="width: 100%"
        :disabled="isUploading"
      />
      <template #footer>
        <el-button @click="uploadDialogVisible = false" :disabled="isUploading">取消</el-button>
        <el-button type="primary" @click="executeUpload" :loading="isUploading">确认并上传</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { Platform, User, Paperclip, Position } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'
import MarkdownIt from 'markdown-it'
import texmath from 'markdown-it-texmath'
import katex from 'katex'
import 'katex/dist/katex.min.css'
// ... 原有的 ref 变量下新增 ...
const uploadDialogVisible = ref(false)
const pendingFile = ref(null)
const uploadTargetFolderId = ref(0)
const uploadTreeData = ref([])

// 拦截文件选择，弹出对话框
const handleFileSelect = (uploadFile) => {
  if (uploadFile.raw.type !== 'application/pdf') {
    ElMessage.error('仅支持 PDF 格式！');
    return;
  }
  pendingFile.value = uploadFile.raw;
  uploadTargetFolderId.value = 0;
  // 从本地缓存读取刚刚在图书馆生成的树形结构
  const cachedTree = localStorage.getItem('rag_library_tree');
  if (cachedTree) uploadTreeData.value = JSON.parse(cachedTree);
  uploadDialogVisible.value = true;
}

// 确认目标后，正式触发上传 (这其实就是你原来的 customUpload，我略微改了名字和参数)
// frontend/src/components/ChatView.vue 里面的 executeUpload 函数
const executeUpload = async () => {
  // 1. 开启上传状态，清空上一次的终端残余日志
  isUploading.value = true;
  uploadLogs.value = []; 
  
  // 2. 从本地缓存获取用户选的引擎
  let currentEngine = 'pypdf';
  const savedSettings = localStorage.getItem('rag_full_settings');
  if (savedSettings) {
    try { currentEngine = JSON.parse(savedSettings).pdfEngine || 'pypdf'; } catch(e) {}
  }

  // 3. 组装表单数据
  const formData = new FormData();
  formData.append('file', pendingFile.value);
  formData.append('course_id', uploadTargetFolderId.value); 
  formData.append('engine', currentEngine);

  // 4. ✨ 核心改变：先关闭弹窗，把舞台让给背后的终端控制台
  uploadDialogVisible.value = false;

  try {
    const response = await fetch('http://127.0.0.1:8000/api/rag/upload', {
      method: 'POST',
      body: formData
    });

    if (!response.ok) throw new Error(`后端返回错误: ${response.statusText}`);

    // 5. 🔥 接管后端的 SSE 流式数据管道
    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      // 解码后端 yield 出来的文本段
      const chunk = decoder.decode(value, { stream: true });
      // 按换行符切割，并过滤掉空行
      const lines = chunk.split('\n').filter(line => line.trim() !== '');
      
      // 实时追加到终端日志数组中
      uploadLogs.value.push(...lines);
      
      // ✨ 自动滚动终端滚轮，保持最新进度永远在视野最下方
      nextTick(() => {
        if (terminalBodyRef.value) {
          terminalBodyRef.value.scrollTop = terminalBodyRef.value.scrollHeight;
        }
      });
    }
    
    // 6. 🎉 【用户痛点解决】：当流彻底读完走出循环后，主动弹窗告知！
    ElMessage({
      message: '📖 课件解析归档并向量化成功！已彻底融入知识库记忆。',
      type: 'success',
      duration: 5000,
      showClose: true
    });

  } catch (error) {
    uploadLogs.value.push(`[致命错误] ❌ 通讯中断：${error.message}`);
    ElMessage.error('上传解析失败，请检查终端日志。');
  } finally {
    isUploading.value = false;
    // 保持终端日志留存 8 秒，让用户能看清最后的成功提示，随后自动收起
    setTimeout(() => { 
      if (!isUploading.value) uploadLogs.value = []; 
    }, 8000);
  }
}

// --- Markdown 与 LaTeX 渲染配置 ---
const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  highlight: function (str, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try { return hljs.highlight(str, { language: lang }).value; } catch (__) {}
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

const messages = ref([
  {
    role: 'assistant',
    content: '你好！我是你的本地 RAG 课件助理。你可以点击输入框左下角的 📎 上传 PDF，或者直接向我提问。'
  }
])

// --- 🚀 核心功能 1：流式读取后端终端日志 (上传 PDF) ---
// frontend/src/components/ChatView.vue 里面的 customUpload 函数
const customUpload = async (options) => {
  if (options.file.type !== 'application/pdf') {
    ElMessage.error('目前仅支持解析 PDF 格式的课件！');
    return;
  }

  isUploading.value = true;
  uploadLogs.value = []; 
  
  // ✨ 新增：从配置中读取用户当前选中的引擎，如果没有则默认 pypdf
  let currentEngine = 'pypdf';
  const savedSettings = localStorage.getItem('rag_full_settings');
  if (savedSettings) {
    try {
      const parsed = JSON.parse(savedSettings);
      if (parsed.pdfEngine) currentEngine = parsed.pdfEngine;
    } catch(e) { console.error(e); }
  }

  const formData = new FormData();
  formData.append('file', options.file);
  formData.append('course_id', '0'); // 以后可以根据 UI 变成动态科目 ID
  formData.append('engine', currentEngine); // ✨ 关键：把引擎名字注入表单发给后端！

  try {
    const response = await fetch('http://127.0.0.1:8000/api/rag/upload', {
      method: 'POST',
      body: formData
    });

    if (!response.ok) throw new Error(`后端返回错误: ${response.statusText}`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      
      const chunk = decoder.decode(value, { stream: true });
      const lines = chunk.split('\n').filter(line => line.trim() !== '');
      uploadLogs.value.push(...lines);
      
      nextTick(() => {
        if (terminalBodyRef.value) {
          terminalBodyRef.value.scrollTop = terminalBodyRef.value.scrollHeight;
        }
      });
    }
    
    ElMessage.success('课件已成功存入本地知识库！');
  } catch (error) {
    uploadLogs.value.push(`[致命错误] ❌ 通讯中断：${error.message}`);
    ElMessage.error('上传解析失败，请检查终端日志。');
  } finally {
    isUploading.value = false;
    setTimeout(() => { uploadLogs.value = []; }, 5000);
  }
}

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
      body: JSON.stringify({ query: userText })
    });
    const retrieveData = await retrieveRes.json();
    const context = retrieveData.context;

    // 📢 步骤 B：推入一个空的助理消息占位，准备接收流式数据
    messages.value.push({ role: 'assistant', content: '' });
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
.input-area { padding: 20px; background: linear-gradient(0deg, white 60%, rgba(255,255,255,0)); }
.input-box-wrapper { max-width: 800px; margin: 0 auto; background-color: #f4f4f5; border-radius: 16px; padding: 10px; border: 1px solid #e4e4e7; transition: all 0.2s; }
.input-box-wrapper:focus-within { background-color: white; border-color: #d4d4d8; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
.input-box-wrapper.is-disabled { opacity: 0.7; cursor: not-allowed; }
.claude-input :deep(.el-textarea__inner) { background: transparent; box-shadow: none; border: none; padding: 8px 12px; font-size: 15px; color: #333; }
.claude-input :deep(.el-textarea__inner:focus) { box-shadow: none; }
.input-actions { display: flex; justify-content: space-between; align-items: center; padding: 0 10px 4px 10px; margin-top: 8px; }
.footer-tip { text-align: center; font-size: 12px; color: #a1a1aa; margin-top: 12px; }

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