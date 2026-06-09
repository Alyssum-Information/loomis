<template>
  <v-container class="py-6">
    <h2 class="text-h5 mb-4">Jobs &amp; health</h2>

    <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>

    <v-table v-else density="comfortable">
      <thead>
        <tr>
          <th>ID</th>
          <th>Type</th>
          <th>Status</th>
          <th>Attempts</th>
          <th>Last error</th>
          <th>Updated</th>
          <th />
        </tr>
      </thead>

      <tbody>
        <tr v-for="job in jobs" :key="job.id">
          <td>{{ job.id }}</td>
          <td>{{ job.type }}</td>
          <td><v-chip :color="statusColor(job.status)" label size="x-small">{{ job.status }}</v-chip></td>
          <td>{{ job.attempts }}</td>
          <td class="text-error text-truncate" style="max-width: 280px">{{ job.last_error }}</td>
          <td class="text-medium-emphasis">{{ job.updated_at }}</td>

          <td class="text-right">
            <v-btn
              v-if="job.status === 'failed' || job.status === 'parked'"
              color="primary"
              size="small"
              variant="text"
              @click="retry(job.id)"
            >
              Retry
            </v-btn>
          </td>
        </tr>

        <tr v-if="jobs.length === 0">
          <td class="text-medium-emphasis" colspan="7">No jobs.</td>
        </tr>
      </tbody>
    </v-table>
  </v-container>
</template>

<script lang="ts" setup>
  import { onMounted, ref } from 'vue'
  import { type Job, listJobs, retryJob } from '@/services/api'
  import { useEventsStore } from '@/stores/events'

  const jobs = ref<Job[]>([])
  const error = ref<string | null>(null)
  const events = useEventsStore()

  function statusColor (status: string): string {
    return { done: 'success', failed: 'error', parked: 'error', running: 'info' }[status] ?? 'grey'
  }

  async function refresh (): Promise<void> {
    try {
      jobs.value = await listJobs({ limit: 200 })
      error.value = null
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  async function retry (id: number): Promise<void> {
    try {
      await retryJob(id)
      await refresh()
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  onMounted(() => {
    refresh()
    events.on(event => {
      if (event.type === 'job.updated') refresh()
    })
  })
</script>
