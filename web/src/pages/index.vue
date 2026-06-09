<template>
  <v-container class="py-6">
    <v-row>
      <v-col cols="12" md="4">
        <v-card>
          <v-card-title class="d-flex align-center justify-space-between">
            <span>Backend</span>

            <v-chip :color="health.error ? 'error' : (health.data ? 'success' : 'grey')" label size="small">
              {{ health.error ? 'offline' : (health.data ? 'online' : '…') }}
            </v-chip>
          </v-card-title>

          <v-card-text v-if="health.data">
            <div>Version: <strong>{{ health.data.version }}</strong></div>
            <div>DB schema: <strong>{{ health.data.db_version }}</strong></div>
          </v-card-text>

          <v-card-text v-else-if="health.error" class="text-error">{{ health.error }}</v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="8">
        <v-card>
          <v-card-title>Pipeline jobs</v-card-title>

          <v-card-text>
            <v-chip
              v-for="(count, status) in jobCounts"
              :key="status"
              class="mr-2 mb-2"
              :color="statusColor(status)"
              label
              variant="tonal"
            >
              {{ status }}: {{ count }}
            </v-chip>

            <span v-if="Object.keys(jobCounts).length === 0" class="text-medium-emphasis">no jobs yet</span>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12">
        <v-card>
          <v-card-title>Recent recordings</v-card-title>

          <v-list lines="two">
            <v-list-item
              v-for="rec in recordings"
              :key="rec.id"
              :subtitle="`${rec.status} · ${rec.recorded_at ?? rec.imported_at ?? ''}`"
              :title="rec.id"
              :to="`/recordings/${rec.id}`"
            >
              <template #prepend>
                <v-icon>mdi-microphone</v-icon>
              </template>

              <template #append>
                <v-chip v-if="rec.kind" label size="x-small">{{ rec.kind }}</v-chip>
              </template>
            </v-list-item>

            <v-list-item v-if="recordings.length === 0" class="text-medium-emphasis">
              No recordings imported yet.
            </v-list-item>
          </v-list>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue'
  import { getRecordings, type Job, listJobs, type Recording } from '@/services/api'
  import { useEventsStore } from '@/stores/events'
  import { useHealthStore } from '@/stores/health'

  const health = useHealthStore()
  const events = useEventsStore()
  const recordings = ref<Recording[]>([])
  const jobs = ref<Job[]>([])

  const jobCounts = computed<Record<string, number>>(() => {
    const counts: Record<string, number> = {}
    for (const job of jobs.value) counts[job.status] = (counts[job.status] ?? 0) + 1
    return counts
  })

  function statusColor (status: string): string {
    return { done: 'success', failed: 'error', parked: 'error', running: 'info' }[status] ?? 'grey'
  }

  async function refresh (): Promise<void> {
    health.refresh()
    recordings.value = (await getRecordings({ limit: 8 })).items
    jobs.value = await listJobs({ limit: 200 })
  }

  onMounted(() => {
    refresh()
    events.on(event => {
      if (event.type === 'job.updated' || event.type === 'recording.added') refresh()
    })
  })
</script>
