import { ref } from 'vue'

// 这里的变量在全局是唯一的
export const globalProfile = ref({
  username: '',
  password: ''
})