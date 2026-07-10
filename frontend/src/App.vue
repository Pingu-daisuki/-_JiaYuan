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
    @select="(index) => activeMenu = index"
    background-color="#ffffff"
    text-color="#303133"
    active-text-color="#409EFF"
  >
    <el-menu-item index="chat">
      <el-icon><ChatSquare /></el-icon>
      <span>文献对话 (RAG)</span>
    </el-menu-item>

    <el-menu-item index="library">
      <el-icon><Reading /></el-icon>
      <span>我的图书馆</span>
    </el-menu-item>

    <el-menu-item index="campus">
      <el-icon><School /></el-icon>
      <span>XMU_RollCall</span>
    </el-menu-item>

    <el-menu-item index="oj">
      <el-icon><Monitor /></el-icon>
      <span>OJ 自动化破题</span>
    </el-menu-item>

    <el-menu-item index="settings">
      <el-icon><Setting /></el-icon>
      <span>引擎与模型设置</span>
    </el-menu-item>
  </el-menu>
</el-aside>

      <el-main class="content-area">
        <KeepAlive>
        <ChatView v-if="activeMenu === 'chat'" class="module-wrapper" />
        <OjView v-else-if="activeMenu === 'oj' " class="module-wrapper" />
        <LibraryPanel v-else-if="activeMenu === 'library'" class="module-wrapper" />
        <CampusView v-else-if="activeMenu === 'campus'" class="module-wrapper" />
        <SettingsView v-else-if="activeMenu === 'settings'" class="module-wrapper" />
        </KeepAlive>
      </el-main>
    </el-container>
  </div>
</template>

<script setup>

import OjView from './components/OjView.vue'; // 确保这里也是大写 O
import { Monitor } from '@element-plus/icons-vue'; // 如果你还没导入这个图标
import CampusView from './components/CampusView.vue'
import { ChatSquare, Reading, School } from '@element-plus/icons-vue' // ✨ 加入 School 图标
import { ref } from 'vue'
import { ChatDotRound, Setting, Collection } from '@element-plus/icons-vue' // ✨ 记得导入 Collection 图标
import ChatView from './components/ChatView.vue' 
import SettingsView from './components/SettingsView.vue'
import LibraryPanel from './components/LibraryPanel.vue'

const activeMenu = ref('chat')

const handleMenuSelect = (index) => {
  activeMenu.value = index
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
.logo-title { font-size: 16px; font-weight: 600; color: #2c3e50; margin: 0; }
.menu-vertical { border-right: none; padding-top: 10px; }
.content-area { background-color: #ffffff; padding: 0; height: 100%; box-sizing: border-box; overflow: hidden; }
.module-wrapper { height: 100%; animation: fadeIn 0.2s ease-out; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
</style>