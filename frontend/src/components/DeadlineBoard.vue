<template>
  <div class="board-wrapper">
    <!-- 左侧栏：账号管理 -->
    <div class="left-sidebar">
      <div class="sidebar-title">
        <el-icon><Calendar /></el-icon>
        <span>智能 DDL 监控</span>
      </div>
      <div class="account-section-title">已认证账号</div>
      
      <div class="account-list">
        <div v-for="acc in accounts" :key="acc.student_id"
             class="account-card"
             :class="{ 'active-card': selectedAccount?.student_id === acc.student_id }"
             @click="selectAccount(acc)">
          <div class="avatar">{{ acc.real_name ? acc.real_name.charAt(0) : 'U' }}</div>
          <div class="info">
            <div class="name">{{ acc.real_name || '未知姓名' }}</div>
            <div class="id">{{ acc.student_id }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 右侧栏：核心数据展示 -->
    <div class="right-content">
      <!-- 顶部导航条 -->
      <div class="top-header">
        <div class="status-text">
          <span v-if="selectedAccount">当前查看: <b>{{ selectedAccount.real_name }}</b> 的任务线</span>
          <span v-else>请在左侧选择一个账号以开启防破防监控</span>
        </div>
        
        <div class="controls" v-if="selectedAccount">
           <el-radio-group v-model="currentView" size="large">
              <el-radio-button value="assignments" label="assignments">作业 / 小测</el-radio-button>
              <el-radio-button value="exams" label="exams">考试安排</el-radio-button>
           </el-radio-group>
           <el-button type="success" size="large" :loading="loading" @click="syncData" style="margin-left: 15px;">
             强制同步
           </el-button>
        </div>
      </div>

      <!-- 主区域：时间线瀑布流 -->
      <div class="main-scroll" v-loading="loading">
        <el-empty v-if="!selectedAccount" description="暂无数据，请先在左侧选择账号"></el-empty>

        <!-- 视图 1：作业时间线 -->
        <div v-else-if="currentView === 'assignments'" class="timeline-box">
           <el-timeline v-if="deadlines.length > 0">
             <el-timeline-item
               v-for="item in deadlines"
               :key="item.id"
               :timestamp="formatDateTime(item.deadline)"
               placement="top"
               :type="getTimelineType(item.deadline)"
               size="large"
             >
               <el-card shadow="hover" class="task-card">
                 <div class="card-header">
                   <el-tag size="small">{{ item.course_name }}</el-tag>
                   <span :class="['urgent-text', getStatusClass(item.deadline)]">
                     {{ getStatusText(item.deadline) }}
                   </span>
                 </div>
                 <h3 class="task-name">{{ item.task_name || item.title }}</h3>
               </el-card>
             </el-timeline-item>
           </el-timeline>
           <el-empty v-else description="太棒了！近期没有任何 DDL，享受生活吧！"></el-empty>
        </div>

        <!-- 视图 2：考试安排 -->
        <div v-else-if="currentView === 'exams'" class="timeline-box">
           <el-empty description="暂时没有读取到期末考试安排"></el-empty>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import axios from 'axios';
import { Calendar } from '@element-plus/icons-vue';
import { ElMessage } from 'element-plus';

const currentView = ref('assignments');
const selectedAccount = ref(null);
const loading = ref(false);

const accounts = ref([]);
const deadlines = ref([]);

// 1. 初始化时从已有的 campus 路由读取账号
const fetchAccounts = async () => {
  try {
    const res = await axios.get('/api/campus/accounts');
    accounts.value = res.data;
  } catch (error) {
    ElMessage.error('获取账号列表失败，请检查后端状态');
  }
};

// 2. 选择左侧账号，默认读取秒开的本地缓存
const selectAccount = async (acc) => {
  selectedAccount.value = acc;
  loading.value = true;
  try {
    const res = await axios.get(`/api/deadlines/${acc.student_id}?sync=false`);
    deadlines.value = res.data.data || [];
  } catch (error) {
    ElMessage.error('获取本地 Deadline 失败');
  } finally {
    loading.value = false;
  }
};

// 3. 点击强制同步，呼叫爬虫热更新
const syncData = async () => {
  if (!selectedAccount.value) return;
  loading.value = true;
  try {
    const res = await axios.get(`/api/deadlines/${selectedAccount.value.student_id}?sync=true`);
    deadlines.value = res.data.data || [];
    ElMessage.success('同步畅课数据成功！');
  } catch (error) {
    ElMessage.error('同步失败: ' + (error.response?.data?.detail || error.message));
  } finally {
    loading.value = false;
  }
};

// 工具函数：日期格式化
const formatDateTime = (dateStr) => {
  if(!dateStr) return '无时间限制';
  const d = new Date(dateStr);
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

// 工具函数：防破防核心逻辑，计算状态文字
const getStatusText = (dateStr) => {
  if(!dateStr) return '无限期';
  const ddl = new Date(dateStr).getTime();
  const now = new Date().getTime();
  const diffHours = (ddl - now) / (1000 * 60 * 60);

  if (diffHours < 0) return '已逾期 💀';
  if (diffHours < 24) return '极度紧急 (不足24h) 🚨';
  if (diffHours < 72) return '即将截止 (不足3天) ⚠️';
  return '时间充裕 ☕';
};

// 工具函数：控制 Element Plus 时间线节点的颜色
const getTimelineType = (dateStr) => {
  const text = getStatusText(dateStr);
  if (text.includes('逾期')) return 'info';
  if (text.includes('极度紧急')) return 'danger';
  if (text.includes('即将截止')) return 'warning';
  return 'success';
};

// 工具函数：控制卡片右上角文字的颜色和心跳动画
const getStatusClass = (dateStr) => {
  const text = getStatusText(dateStr);
  if (text.includes('逾期')) return 'status-gray';
  if (text.includes('极度紧急')) return 'status-red blink';
  if (text.includes('即将截止')) return 'status-orange';
  return 'status-green';
};

onMounted(() => {
  fetchAccounts();
});
</script>

<style scoped>
.board-wrapper {
  display: flex;
  height: 100%;
  width: 100%;
  background-color: #f5f7fa;
}

/* 左侧侧边栏 */
.left-sidebar {
  width: 280px;
  background-color: #ffffff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
}
.sidebar-title {
  padding: 20px;
  font-size: 18px;
  font-weight: bold;
  color: #303133;
  border-bottom: 1px solid #ebeef5;
  display: flex;
  align-items: center;
  gap: 10px;
}
.account-section-title {
  padding: 15px 20px 5px;
  font-size: 13px;
  color: #909399;
}
.account-list {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}
.account-card {
  display: flex;
  align-items: center;
  padding: 12px;
  margin-bottom: 10px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
  border: 1px solid transparent;
}
.account-card:hover {
  background-color: #f2f6fc;
}
.active-card {
  background-color: #ecf5ff;
  border-color: #b3d8ff;
}
.avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background-color: #409EFF;
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-size: 18px;
  margin-right: 12px;
}
.info .name {
  font-size: 14px;
  font-weight: bold;
  color: #303133;
}
.info .id {
  font-size: 12px;
  color: #909399;
  margin-top: 2px;
}

/* 右侧内容区 */
.right-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.top-header {
  height: 70px;
  background-color: #ffffff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 30px;
}
.status-text {
  font-size: 16px;
  color: #606266;
}
.main-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 40px;
}
.timeline-box {
  max-width: 800px;
  margin: 0 auto;
}

/* 卡片内部细节 */
.task-card {
  border-radius: 8px;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}
.task-name {
  margin: 0;
  font-size: 16px;
  color: #303133;
}

/* 防破防提醒颜色与动画 */
.urgent-text { font-size: 13px; font-weight: bold; }
.status-gray { color: #909399; }
.status-red { color: #F56C6C; }
.status-orange { color: #E6A23C; }
.status-green { color: #67C23A; }

/* 小于 24 小时的心跳预警动画 */
.blink { animation: blinker 1.5s linear infinite; }
@keyframes blinker { 50% { opacity: 0.2; } }
</style>