<template>
  <v-container class="py-6">
    <h2 class="text-h5 mb-4">Timeline</h2>

    <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>

    <v-list v-else lines="two">
      <v-list-item
        v-for="day in days"
        :key="day.date"
        :title="day.date"
        :to="day.has_diary ? `/diary/${day.date}` : undefined"
      >
        <template #prepend>
          <v-icon>{{ day.has_diary ? 'mdi-book-open-variant' : 'mdi-calendar-blank' }}</v-icon>
        </template>

        <template #append>
          <v-chip
            v-if="day.has_diary"
            class="mr-2"
            color="primary"
            label
            size="small"
          >diary</v-chip>

          <v-chip v-if="day.meeting_count" color="secondary" label size="small">
            {{ day.meeting_count }} meeting{{ day.meeting_count > 1 ? 's' : '' }}
          </v-chip>
        </template>
      </v-list-item>

      <v-list-item v-if="days.length === 0" class="text-medium-emphasis">
        Nothing on the timeline yet — import a recording to get started.
      </v-list-item>
    </v-list>
  </v-container>
</template>

<script lang="ts" setup>
  import { onMounted, ref } from 'vue'
  import { getTimeline, type TimelineDay } from '@/services/api'
  import { useEventsStore } from '@/stores/events'

  const days = ref<TimelineDay[]>([])
  const error = ref<string | null>(null)
  const events = useEventsStore()

  async function refresh (): Promise<void> {
    try {
      days.value = await getTimeline()
      error.value = null
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  onMounted(() => {
    refresh()
    events.on(event => {
      if (event.type === 'diary.updated') refresh()
    })
  })
</script>
