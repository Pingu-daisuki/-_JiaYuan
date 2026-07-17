import { ref } from 'vue'
import { apiJson } from '../api/client'

export const campusAccounts = ref([])
export const campusAccountsLoading = ref(false)

let activeRequest = null

export const refreshCampusAccounts = async () => {
  if (activeRequest) return activeRequest

  campusAccountsLoading.value = true
  activeRequest = (async () => {
    const payload = await apiJson('/api/campus/accounts', { cache: 'no-store' })
    if (!Array.isArray(payload)) throw new Error('身份资料格式异常')
    campusAccounts.value = payload
    return payload
  })()

  try {
    return await activeRequest
  } finally {
    activeRequest = null
    campusAccountsLoading.value = false
  }
}
