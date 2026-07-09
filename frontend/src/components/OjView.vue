<template>
  <div class="oj-view-container p-4 h-full flex flex-col gap-4">
    <el-card header="自动刷题引擎配置">
      <el-form :model="form" inline>
        <el-form-item label="实验 ID">
          <el-input v-model="form.contest_id" placeholder="例如: 1234" />
        </el-form-item>
        <el-form-item label="实验密码">
          <el-input v-model="form.contest_password" type="password" placeholder="可选" />
        </el-form-item>
        <el-button type="primary" :loading="running" @click="startSolve">开始自动攻破</el-button>
      </el-form>
    </el-card>

    <el-card class="flex-grow overflow-hidden flex flex-col" header="执行日志">
      <div ref="logContainer" class="log-container h-80 overflow-y-auto p-2 bg-gray-900 text-green-400 font-mono text-sm rounded">
        <div v-for="(log, i) in logs" :key="i" class="mb-1">{{ log }}</div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue';
import { ElMessage } from 'element-plus';

const form = ref({ contest_id: '', contest_password: '' });
const logs = ref(['[准备] 等待启动...']);
const logContainer = ref(null);
const running = ref(false);

const startSolve = () => {
  if (!form.value.contest_id) return ElMessage.error('请填写实验 ID');
  
  logs.value = ['[系统] 正在连接后端...'];
  running.value = true;
  
  // 使用 EventSource 处理后端流式数据
  const source = new EventSource(`/api/oj/stream_solve?contest_id=${form.value.contest_id}&contest_password=${form.value.contest_password}`);
  
  source.onmessage = (event) => {
    logs.value.push(event.data);
    nextTick(() => {
      if (logContainer.value) logContainer.value.scrollTop = logContainer.value.scrollHeight;
    });
  };

  source.onerror = () => {
    logs.value.push('[系统] ⚠️ 连接断开或任务结束');
    running.value = false;
    source.close();
  };
};
</script>

<style scoped>
.log-container { white-space: pre-wrap; }
</style>