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

      <audio
        ref="audio"
        class="w-100 mb-4"
        controls
        :src="audioSrc"
        @pause="playing = false"
        @play="playing = true"
        @timeupdate="onTimeUpdate"
      />

      <v-card>
        <v-card-title>Transcript</v-card-title>

        <v-list>
          <v-list-item
            v-for="(seg, i) in segments"
            :id="`segment-${i}`"
            :key="seg.id ?? seg.idx"
            :active="i === activeIdx"
            color="primary"
            @click="playFrom(seg)"
          >
            <template #prepend>
              <v-chip class="mr-3" label size="x-small">{{ speakerLabel(seg) }}</v-chip>
            </template>

            <v-list-item-title class="text-wrap">{{ seg.text }}</v-list-item-title>

            <template #append>
              <span class="text-caption text-medium-emphasis mr-2">{{ fmt(seg.start_s) }}</span>

              <v-btn
                density="comfortable"
                :icon="i === activeIdx && playing ? 'mdi-pause' : 'mdi-play'"
                size="small"
                variant="text"
                @click.stop="toggleSegment(seg, i)"
              />
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
  import { onMounted, ref, watch } from 'vue'
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

  const playing = ref(false)
  const activeIdx = ref(-1)

  function speakerLabel (seg: Segment): string {
    if (seg.speaker_id != null) return speakerNames.value[seg.speaker_id] ?? `Speaker ${seg.speaker_id}`
    return seg.diarization_label ?? '—'
  }

  function fmt (seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  // Highlight the segment the playhead is inside; -1 between segments (silence).
  function onTimeUpdate (): void {
    const t = audio.value?.currentTime ?? 0
    const list = segments.value
    let idx = -1
    for (let i = list.length - 1; i >= 0; i--) {
      if (t >= list[i].start_s) {
        if (t < list[i].end_s) idx = i
        break
      }
    }
    activeIdx.value = idx
  }

  // Keep the highlighted line visible while playback advances.
  watch(activeIdx, idx => {
    if (idx < 0) return
    document
      .querySelector(`#segment-${idx}`)
      ?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })

  function playFrom (seg: Segment): void {
    if (!audio.value) return
    audio.value.currentTime = seg.start_s
    void audio.value.play()
  }

  // The per-line button: play from this line, or pause if it is already playing.
  function toggleSegment (seg: Segment, i: number): void {
    if (!audio.value) return
    if (i === activeIdx.value && playing.value) {
      audio.value.pause()
      return
    }
    playFrom(seg)
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
