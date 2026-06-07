// Backend health state — proves the SPA ↔ backend wiring works.
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getHealth, type Health } from '@/services/api'

export const useHealthStore = defineStore('health', () => {
  const data = ref<Health | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function refresh (): Promise<void> {
    loading.value = true
    error.value = null
    try {
      data.value = await getHealth()
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
      data.value = null
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, refresh }
})
