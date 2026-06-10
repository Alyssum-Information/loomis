<template>
  <v-container class="py-6" style="max-width: 880px">
    <h2 class="text-h5 mb-1">Settings</h2>

    <div v-if="configPath" class="text-caption text-medium-emphasis mb-4">
      Stored in {{ configPath }} — environment variables still override the file.
    </div>

    <v-alert v-if="error" class="mb-4" type="error" variant="tonal">{{ error }}</v-alert>

    <v-alert
      v-if="notice"
      class="mb-4"
      closable
      type="info"
      variant="tonal"
      @click:close="notice = null"
    >
      {{ notice }}
    </v-alert>

    <!-- Egress overview: the mandatory privacy-boundary indicator (FR-7.8). -->
    <v-alert
      v-if="egressActive"
      class="mb-4"
      icon="mdi-cloud-upload-outline"
      type="warning"
      variant="tonal"
    >
      Data can leave this machine:
      <strong>{{ egressKinds.join(', ') }}</strong>. Everything else stays local.
    </v-alert>

    <template v-if="form">
      <!-- Transcription -->
      <v-card class="mb-4">
        <v-card-title>Transcription</v-card-title>

        <v-card-text>
          <v-text-field
            v-model="form.stt.language"
            density="comfortable"
            hint="Your daily language, e.g. &quot;zh&quot; — auto-detection misreads clips that open with silence"
            label="Language (auto = detect per file)"
            persistent-hint
          />

          <v-text-field
            v-model="form.stt.model"
            class="mt-2"
            density="comfortable"
            hint="large-v3 on GPU; medium/small for CPU-only machines"
            label="Whisper model"
            persistent-hint
          />

          <v-text-field
            v-model="form.diarize.hf_token"
            class="mt-2"
            density="comfortable"
            hint="HuggingFace token for the gated pyannote diarization model"
            label="HuggingFace token"
            persistent-hint
            type="password"
          />
        </v-card-text>

        <v-card-actions>
          <v-btn color="primary" variant="tonal" @click="save({ stt: form.stt, diarize: form.diarize })">
            Save
          </v-btn>
        </v-card-actions>
      </v-card>

      <!-- Summaries -->
      <v-card class="mb-4">
        <v-card-title>Summaries</v-card-title>

        <v-card-text>
          <v-text-field
            v-model="form.llm.model"
            density="comfortable"
            hint="Ollama model used for diaries and meeting records"
            label="LLM model"
            persistent-hint
          />

          <v-text-field
            v-model="form.summaries.summary_language"
            class="mt-2"
            density="comfortable"
            hint="auto = follow the transcript's dominant language"
            label="Summary language"
            persistent-hint
          />

          <v-text-field
            v-model.number="form.summaries.diary_day_settle_minutes"
            class="mt-2"
            density="comfortable"
            hint="Quiet period after a day's last import before its diary is written"
            label="Diary settle window (minutes)"
            persistent-hint
            type="number"
          />
        </v-card-text>

        <v-card-actions>
          <v-btn
            color="primary"
            variant="tonal"
            @click="save({ llm: { model: form.llm.model }, summaries: form.summaries })"
          >
            Save
          </v-btn>
        </v-card-actions>
      </v-card>

      <!-- Import -->
      <v-card class="mb-4">
        <v-card-title>Import</v-card-title>

        <v-card-text>
          <v-select
            v-model="form.backup.transcode_policy"
            density="comfortable"
            hint="transcode_only keeps just the validated Opus (~10× smaller); keep_original archives bit-exact files"
            :items="['transcode_only', 'transcode_keep', 'keep_original']"
            label="Default transcode policy (new sources)"
            persistent-hint
          />

          <v-text-field
            v-model="form.transcode.bitrate"
            class="mt-2"
            density="comfortable"
            hint="32k is the STT-safe floor; transcription quality drops below ~24k"
            label="Opus bitrate"
            persistent-hint
          />

          <v-text-field
            v-model.number="form.backup.folder_poll_interval_s"
            class="mt-2"
            density="comfortable"
            label="Watched-folder scan interval (seconds)"
            type="number"
          />
        </v-card-text>

        <v-card-actions>
          <v-btn
            color="primary"
            variant="tonal"
            @click="save({
              backup: {
                transcode_policy: form.backup.transcode_policy,
                folder_poll_interval_s: form.backup.folder_poll_interval_s,
              },
              transcode: { bitrate: form.transcode.bitrate },
            })"
          >
            Save
          </v-btn>
        </v-card-actions>
      </v-card>

      <!-- Cloud sync: crossing the privacy boundary needs an explicit confirm (FR-7.8). -->
      <v-card class="mb-4">
        <v-card-title>Cloud backup</v-card-title>

        <v-card-text>
          <v-switch
            color="warning"
            density="comfortable"
            hide-details
            label="Enable cloud sync (data leaves this machine)"
            :model-value="Boolean(form.cloud.enabled)"
            @update:model-value="onCloudToggle"
          />

          <v-text-field
            v-model="form.cloud.schedule_cron"
            class="mt-3"
            density="comfortable"
            hint="5-field cron, e.g. &quot;0 3 * * *&quot; = daily at 03:00; empty = manual only"
            label="Sync schedule (cron)"
            persistent-hint
          />

          <div class="text-caption text-medium-emphasis mt-3">
            Remotes are configured with <code>rclone config</code> and listed under
            <code>[[cloud.remotes]]</code> in the config file; manual sync lives on the
            Sources screen.
          </div>
        </v-card-text>

        <v-card-actions>
          <v-btn
            color="primary"
            variant="tonal"
            @click="save({ cloud: { schedule_cron: form.cloud.schedule_cron } })"
          >
            Save
          </v-btn>
        </v-card-actions>
      </v-card>
    </template>

    <!-- Explicit consent before the first egress-enabling change (FR-7.8). -->
    <v-dialog v-model="confirmOpen" max-width="480">
      <v-card>
        <v-card-title>Send data off this machine?</v-card-title>

        <v-card-text>
          Enabling cloud sync will push your library to the configured rclone
          remotes. Loomis is local-first: nothing leaves this machine until you
          confirm. Pushes are copy-only and never delete local files.
        </v-card-text>

        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="confirmOpen = false">Cancel</v-btn>
          <v-btn color="warning" variant="flat" @click="confirmCloud">Enable</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue'
  import { type EgressStatus, getSettings, patchSettings } from '@/services/api'
  import { useEventsStore } from '@/stores/events'

  // The editable slice of the config; values mirror the backend's snake_case keys.
  type SettingsForm = {
    stt: { language: string, model: string }
    diarize: { hf_token: string }
    llm: { model: string }
    summaries: { summary_language: string, diary_day_settle_minutes: number }
    backup: { transcode_policy: string, folder_poll_interval_s: number }
    transcode: { bitrate: string }
    cloud: { enabled: boolean, schedule_cron: string }
  }
  type Patch = Record<string, Record<string, unknown>>

  const form = ref<SettingsForm | null>(null)
  const egress = ref<EgressStatus | null>(null)
  const configPath = ref('')
  const error = ref<string | null>(null)
  const notice = ref<string | null>(null)
  const confirmOpen = ref(false)
  const events = useEventsStore()

  const egressKinds = computed(() => {
    if (!egress.value) return []
    return Object.entries(egress.value)
      .filter(([, on]) => on)
      .map(([kind]) => kind.replace('_', ' '))
  })
  const egressActive = computed(() => egressKinds.value.length > 0)

  async function refresh (): Promise<void> {
    try {
      const env = await getSettings()
      form.value = env.settings as unknown as SettingsForm
      egress.value = env.egress
      configPath.value = env.config_path
      error.value = null
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  async function save (patch: Patch): Promise<void> {
    try {
      const result = await patchSettings(patch)
      egress.value = result.egress
      notice.value = result.restart_required
        ? 'Saved — restart Loomis for some of these changes to take effect.'
        : 'Saved.'
      error.value = null
      await refresh()
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  // The cloud toggle never flips silently: off → on requires the consent dialog.
  function onCloudToggle (on: boolean | null): void {
    if (on) {
      confirmOpen.value = true
      return
    }
    void save({ cloud: { enabled: false } })
  }

  function confirmCloud (): void {
    confirmOpen.value = false
    void save({ cloud: { enabled: true } })
  }

  onMounted(() => {
    refresh()
    events.on(event => {
      if (event.type === 'egress.pending') refresh()
    })
  })
</script>
