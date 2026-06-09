<template>
  <v-container class="py-6">
    <div class="d-flex align-center mb-4">
      <h2 class="text-h5">Records</h2>

      <v-spacer />

      <v-btn
        :disabled="!hasRetryable"
        prepend-icon="mdi-refresh"
        size="small"
        variant="tonal"
        @click="retryAll"
      >
        Retry all
      </v-btn>
    </div>

    <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>

    <v-card v-else>
      <v-table density="comfortable">
        <thead>
          <tr>
            <th>Record</th>
            <th>Device</th>
            <th>Date</th>
            <th class="text-right">Duration</th>
            <th class="text-right">Size</th>
            <th>Pipeline</th>
            <th />
          </tr>
        </thead>

        <tbody>
          <tr v-for="r in records" :key="r.recording_id">
            <td style="min-width: 180px">
              <router-link class="text-decoration-none" :to="`/recordings/${r.recording_id}`">
                {{ r.name }}
              </router-link>

              <div v-if="r.kind" class="text-caption text-medium-emphasis">{{ r.kind }}</div>
            </td>

            <td class="text-medium-emphasis">{{ r.device_name ?? r.device_id }}</td>

            <td class="text-medium-emphasis text-no-wrap">{{ formatDate(r.recorded_at ?? r.imported_at) }}</td>

            <td class="text-right text-medium-emphasis text-no-wrap">{{ formatDuration(r.duration_s) }}</td>

            <td class="text-right text-medium-emphasis text-no-wrap">{{ formatSize(r.size_bytes) }}</td>

            <td>
              <div class="d-flex align-center ga-1 py-1">
                <template v-for="(stage, i) in stagesOf(r)" :key="stage.key">
                  <v-icon v-if="i > 0" color="grey-lighten-1" size="14">mdi-chevron-right</v-icon>

                  <v-tooltip location="top" :text="stage.tip">
                    <template #activator="{ props }">
                      <v-chip
                        v-bind="props"
                        :color="stageColor(stage.state)"
                        label
                        size="small"
                        variant="tonal"
                      >
                        <v-icon size="14" start>{{ stageIcon(stage.state) }}</v-icon>
                        {{ stage.label }}
                      </v-chip>
                    </template>
                  </v-tooltip>
                </template>
              </div>
            </td>

            <td class="text-right">
              <v-btn
                v-if="failedStage(r)"
                color="primary"
                size="small"
                variant="text"
                @click="retryRecord(r)"
              >
                Retry
              </v-btn>
            </td>
          </tr>

          <tr v-if="records.length === 0">
            <td class="text-medium-emphasis" colspan="7">No records yet.</td>
          </tr>
        </tbody>
      </v-table>
    </v-card>
  </v-container>
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue'
  import { getRecords, type PipelineStage, type RecordPipeline, retryAllJobs, retryJob } from '@/services/api'
  import { useEventsStore } from '@/stores/events'

  // The stages a recording moves through (未處理 → 備份 → 語音轉文字 → 摘要).
  // A record with both stt and summary pending is still 未處理; backup is done on import.
  const STAGES = [
    { key: 'backup', label: '備份' },
    { key: 'stt', label: '語音轉文字' },
    { key: 'summary', label: '摘要' },
  ] as const

  const records = ref<RecordPipeline[]>([])
  const error = ref<string | null>(null)
  const events = useEventsStore()

  function stagesOf (r: RecordPipeline): { key: string, label: string, state: string, tip: string }[] {
    return STAGES.map(s => {
      const stage = r[s.key]
      return { key: s.key, label: s.label, state: stage.state, tip: stage.error ?? stage.state }
    })
  }

  function failedStage (r: RecordPipeline): PipelineStage | null {
    for (const s of STAGES) {
      const stage = r[s.key]
      if (stage.state === 'failed' && stage.job_id != null) {
        return stage
      }
    }
    return null
  }

  const hasRetryable = computed(() => records.value.some(r => failedStage(r) !== null))

  function stageIcon (state: string): string {
    return ({
      done: 'mdi-check-circle',
      active: 'mdi-progress-clock',
      failed: 'mdi-alert-circle',
      pending: 'mdi-circle-outline',
    } as Record<string, string>)[state] ?? 'mdi-circle-outline'
  }

  function stageColor (state: string): string {
    return ({ done: 'success', active: 'info', failed: 'error', pending: 'grey' } as Record<string, string>)[state] ?? 'grey'
  }

  function formatDate (iso?: string | null): string {
    if (!iso) return '—'
    const d = new Date(iso)
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleString()
  }

  function formatDuration (seconds?: number | null): string {
    if (seconds == null) return '—'
    const total = Math.round(seconds)
    const h = Math.floor(total / 3600)
    const m = Math.floor((total % 3600) / 60)
    const s = total % 60
    const pad = (n: number): string => String(n).padStart(2, '0')
    return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
  }

  function formatSize (bytes?: number | null): string {
    if (!bytes) return '—'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let value = bytes
    let i = 0
    while (value >= 1024 && i < units.length - 1) {
      value /= 1024
      i++
    }
    return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
  }

  async function refresh (): Promise<void> {
    try {
      records.value = (await getRecords({ limit: 200 })).items
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

  function retryRecord (r: RecordPipeline): void {
    const stage = failedStage(r)
    if (stage?.job_id != null) {
      void retry(stage.job_id)
    }
  }

  async function retryAll (): Promise<void> {
    try {
      await retryAllJobs()
      await refresh()
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  onMounted(() => {
    refresh()
    events.on(event => {
      if (event.type === 'job.updated' || event.type === 'recording.added') {
        refresh()
      }
    })
  })
</script>
