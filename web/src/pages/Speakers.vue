<template>
  <v-container class="py-6">
    <h2 class="text-h5 mb-4">Speakers</h2>

    <v-alert v-if="error" class="mb-4" type="error" variant="tonal">{{ error }}</v-alert>

    <v-card class="mb-6">
      <v-table density="comfortable">
        <thead>
          <tr>
            <th>ID</th>
            <th>Name</th>
            <th>State</th>
            <th />
          </tr>
        </thead>

        <tbody>
          <tr v-for="sp in speakers" :key="sp.id">
            <td>{{ sp.id }}</td>

            <td style="min-width: 220px">
              <v-text-field
                v-model="names[sp.id]"
                density="compact"
                hide-details
                :placeholder="`Speaker ${sp.id}`"
                variant="plain"
                @keyup.enter="rename(sp.id)"
              />
            </td>

            <td>
              <v-chip v-if="sp.is_provisional" color="warning" label size="x-small">provisional</v-chip>

              <v-chip
                v-if="sp.needs_review"
                class="ml-1"
                color="info"
                label
                size="x-small"
              >review</v-chip>

              <!-- LLM-suggested name (FR-5.8): one click accepts it as the display name. -->
              <v-chip
                v-if="sp.suggested_name && !sp.display_name"
                class="ml-1"
                color="primary"
                label
                prepend-icon="mdi-lightbulb-outline"
                size="x-small"
                @click="acceptSuggestion(sp.id, sp.suggested_name)"
              >
                {{ sp.suggested_name }}?
              </v-chip>
            </td>

            <td class="text-right">
              <v-btn size="small" variant="text" @click="rename(sp.id)">Save</v-btn>

              <v-btn
                v-if="sp.suggested_name && !sp.display_name"
                color="primary"
                size="small"
                variant="text"
                @click="acceptSuggestion(sp.id, sp.suggested_name)"
              >
                Accept "{{ sp.suggested_name }}"
              </v-btn>

              <v-btn
                v-if="sp.is_provisional"
                color="primary"
                size="small"
                variant="text"
                @click="confirm(sp.id)"
              >
                Confirm
              </v-btn>
            </td>
          </tr>

          <tr v-if="speakers.length === 0">
            <td class="text-medium-emphasis" colspan="4">No speakers yet.</td>
          </tr>
        </tbody>
      </v-table>
    </v-card>

    <v-row>
      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Merge</v-card-title>

          <v-card-text>
            <p class="text-medium-emphasis mb-3">Fold the source identity into the target.</p>
            <v-select v-model="mergeSource" density="comfortable" :items="options" label="Source" />
            <v-select v-model="mergeTarget" density="comfortable" :items="options" label="Target" />
          </v-card-text>

          <v-card-actions>
            <v-btn
              color="primary"
              :disabled="mergeSource == null || mergeTarget == null || mergeSource === mergeTarget"
              variant="tonal"
              @click="doMerge"
            >
              Merge
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <v-col cols="12" md="6">
        <v-card>
          <v-card-title>Split</v-card-title>

          <v-card-text>
            <p class="text-medium-emphasis mb-3">Peel one recording into a new identity.</p>
            <v-select v-model="splitId" density="comfortable" :items="options" label="Speaker" />
            <v-text-field v-model="splitRecording" density="comfortable" label="Recording ID" />
          </v-card-text>

          <v-card-actions>
            <v-btn
              color="primary"
              :disabled="splitId == null || !splitRecording"
              variant="tonal"
              @click="doSplit"
            >
              Split
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue'
  import {
    listSpeakers,
    mergeSpeakers,
    type Speaker,
    splitSpeaker,
    updateSpeaker,
  } from '@/services/api'
  import { useEventsStore } from '@/stores/events'

  const speakers = ref<Speaker[]>([])
  const names = ref<Record<number, string>>({})
  const error = ref<string | null>(null)
  const events = useEventsStore()

  const mergeSource = ref<number | null>(null)
  const mergeTarget = ref<number | null>(null)
  const splitId = ref<number | null>(null)
  const splitRecording = ref('')

  const options = computed(() =>
    speakers.value.map(sp => ({ title: names.value[sp.id] || `Speaker ${sp.id}`, value: sp.id })),
  )

  async function refresh (): Promise<void> {
    try {
      speakers.value = await listSpeakers()
      for (const sp of speakers.value) names.value[sp.id] = sp.display_name ?? ''
      error.value = null
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  async function act (fn: () => Promise<unknown>): Promise<void> {
    try {
      await fn()
      await refresh()
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  const rename = (id: number) => act(() => updateSpeaker(id, { display_name: names.value[id] }))
  const confirm = (id: number) => act(() => updateSpeaker(id, { is_provisional: false }))

  // Accepting a suggestion names + confirms the identity in one step (FR-5.8).
  function acceptSuggestion (id: number, name: string): Promise<void> {
    return act(() => updateSpeaker(id, { display_name: name, is_provisional: false }))
  }

  function doMerge (): void {
    if (mergeSource.value == null || mergeTarget.value == null) return
    void act(() => mergeSpeakers(mergeSource.value!, mergeTarget.value!))
    mergeSource.value = null
    mergeTarget.value = null
  }

  function doSplit (): void {
    if (splitId.value == null) return
    void act(() => splitSpeaker(splitId.value!, splitRecording.value.trim()))
    splitRecording.value = ''
  }

  onMounted(() => {
    refresh()
    // merge/split run as jobs; refresh when they finish.
    events.on(event => {
      if (event.type === 'job.updated' || event.type === 'speaker.updated') refresh()
    })
  })
</script>
