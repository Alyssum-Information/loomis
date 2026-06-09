<template>
  <v-container class="py-6">
    <v-btn
      class="mb-4"
      prepend-icon="mdi-arrow-left"
      size="small"
      to="/"
      variant="text"
    >
      Back
    </v-btn>

    <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>

    <template v-else-if="recording">
      <h2 class="text-h6 mb-1">Recording {{ recording.id }}</h2>

      <div class="text-medium-emphasis mb-4">
        {{ recording.status }} · {{ recording.recorded_at ?? recording.imported_at }}
        <v-chip v-if="recording.kind" class="ml-2" label size="x-small">{{ recording.kind }}</v-chip>
      </div>

      <audio ref="audio" class="w-100 mb-4" controls :src="audioSrc" />

      <v-card>
        <v-card-title>Transcript</v-card-title>

        <v-list>
          <v-list-item
            v-for="seg in segments"
            :key="seg.id ?? seg.idx"
            @click="seek(seg.start_s)"
          >
            <template #prepend>
              <v-chip class="mr-3" label size="x-small">{{ speakerLabel(seg) }}</v-chip>
            </template>

            <v-list-item-title class="text-wrap">{{ seg.text }}</v-list-item-title>

            <template #append>
              <span class="text-caption text-medium-emphasis">{{ fmt(seg.start_s) }}</span>
            </template>
          </v-list-item>

          <v-list-item v-if="segments.length === 0" class="text-medium-emphasis">
            No transcript yet.
          </v-list-item>
        </v-list>
      </v-card>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
  import { onMounted, ref } from 'vue'
  import { useRoute } from 'vue-router'
  import {
    audioUrl,
    getRecording,
    getTranscript,
    listSpeakers,
    type Recording,
    type Segment,
  } from '@/services/api'

  const route = useRoute()
  const id = route.params.id as string

  const recording = ref<Recording | null>(null)
  const segments = ref<Segment[]>([])
  const speakerNames = ref<Record<number, string>>({})
  const error = ref<string | null>(null)
  const audio = ref<HTMLAudioElement | null>(null)
  const audioSrc = audioUrl(id)

  function speakerLabel (seg: Segment): string {
    if (seg.speaker_id != null) return speakerNames.value[seg.speaker_id] ?? `Speaker ${seg.speaker_id}`
    return seg.diarization_label ?? '—'
  }

  function fmt (seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  function seek (seconds: number): void {
    if (audio.value) {
      audio.value.currentTime = seconds
      void audio.value.play()
    }
  }

  onMounted(async () => {
    try {
      recording.value = await getRecording(id)
      for (const sp of await listSpeakers()) {
        if (sp.display_name) speakerNames.value[sp.id] = sp.display_name
      }
      try {
        segments.value = (await getTranscript(id)).segments
      } catch { /* no transcript yet */ }
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  })
</script>
