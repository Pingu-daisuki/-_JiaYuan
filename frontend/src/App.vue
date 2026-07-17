<template>
  <div class="app-container">
    <el-container class="main-layout">
      <el-aside width="240px" class="sidebar">
        <div class="logo-area">
          <span class="logo-icon">🎓</span>
          <span class="logo-text">厦大_JiaYuan</span>
        </div>

        <el-menu
          :default-active="activeMenu"
          class="el-menu-vertical"
          @select="handleMenuSelect"
          background-color="#ffffff"
          text-color="#303133"
          active-text-color="#409EFF"
        >
          <el-menu-item index="dashboard">
            <el-icon><DataBoard /></el-icon>
            <span>学习仪表盘</span>
          </el-menu-item>
          <el-menu-item index="chat">
            <el-icon><ChatSquare /></el-icon>
            <span>XMU_RAG</span>
          </el-menu-item>

          <el-menu-item index="library">
            <el-icon><Reading /></el-icon>
            <span>XMU_Library</span>
          </el-menu-item>

          <el-menu-item index="campus">
            <el-icon><School /></el-icon>
            <span>XMU_RollCall</span>
          </el-menu-item>

          <!-- ✨ 新增的 Deadline 看板入口 -->
          <el-menu-item index="deadlines">
            <el-icon><Calendar /></el-icon>
            <span>XMU_DeadLines</span>
          </el-menu-item>

          <el-menu-item index="oj">
            <el-icon><Monitor /></el-icon>
            <span>XMU_OJ</span>
          </el-menu-item>

          <el-menu-item index="settings">
            <el-icon><Setting /></el-icon>
            <span>Settings</span>
          </el-menu-item>

          <el-menu-item index="system">
            <el-icon><Operation /></el-icon>
            <span>运行与数据</span>
          </el-menu-item>
        </el-menu>
      </el-aside>

      <el-main class="content-area">
        <KeepAlive>
          <DashboardView v-if="activeMenu === 'dashboard'" class="module-wrapper" @navigate="handleMenuSelect" @open-conversation="openConversation" />
          <ChatView v-else-if="activeMenu === 'chat'" :requested-conversation-id="requestedConversationId" class="module-wrapper" />
          <LibraryPanel v-else-if="activeMenu === 'library'" class="module-wrapper" />
          <CampusView v-else-if="activeMenu === 'campus'" class="module-wrapper" />
          <!-- ✨ 新增的组件渲染逻辑 -->
          <DeadlineBoard v-else-if="activeMenu === 'deadlines'" class="module-wrapper" />
          <OjView v-else-if="activeMenu === 'oj'" class="module-wrapper" />
          <SettingsView v-else-if="activeMenu === 'settings'" class="module-wrapper" />
          <SystemView v-else-if="activeMenu === 'system'" class="module-wrapper" />
        </KeepAlive>
      </el-main>
    </el-container>
  </div>
</template>

<script setup>
import { defineAsyncComponent, ref } from 'vue'
// ✨ 引入新页面的图标和组件
import { ChatSquare, Reading, School, Monitor, Setting, Calendar, Operation, DataBoard } from '@element-plus/icons-vue'
const DashboardView = defineAsyncComponent(() => import('./components/DashboardView.vue'))
const ChatView = defineAsyncComponent(() => import('./components/ChatView.vue'))
const LibraryPanel = defineAsyncComponent(() => import('./components/LibraryPanel.vue'))
const CampusView = defineAsyncComponent(() => import('./components/CampusView.vue'))
const OjView = defineAsyncComponent(() => import('./components/OjView.vue'))
const SettingsView = defineAsyncComponent(() => import('./components/SettingsView.vue'))
const DeadlineBoard = defineAsyncComponent(() => import('./components/DeadlineBoard.vue'))
const SystemView = defineAsyncComponent(() => import('./components/SystemView.vue'))

const activeMenu = ref('dashboard')
const requestedConversationId = ref('')

const handleMenuSelect = (index) => {
  activeMenu.value = index
}
const openConversation = (id) => {
  requestedConversationId.value = id
  activeMenu.value = 'chat'
}
</script>

<style>
/* 🧠 全局样式重置 */
html, body, #app { 
  margin: 0; 
  padding: 0; 
  height: 100%; 
  width: 100%; 
  background-color: #ffffff !important; 
}
</style>

<style scoped>
.app-container { height: 100vh; width: 100vw; background-color: #ffffff; }
.main-layout { height: 100%; }
.sidebar { background-color: #ffffff; border-right: 1px solid #e6e6e6; display: flex; flex-direction: column; }
.logo-area { height: 70px; display: flex; align-items: center; padding-left: 20px; border-bottom: 1px solid #f0f0f0; }
.logo-icon { font-size: 24px; margin-right: 10px; }
.logo-text { font-size: 16px; font-weight: 600; color: #2c3e50; margin: 0; }
.el-menu-vertical { border-right: none; padding-top: 10px; }
.content-area { background-color: #ffffff; padding: 0; height: 100%; box-sizing: border-box; overflow: hidden; }
.module-wrapper { height: 100%; animation: fadeIn 0.2s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
</style>
