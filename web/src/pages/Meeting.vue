<template>
  <v-container class="py-6">
    <v-btn
      class="mb-4"
      prepend-icon="mdi-arrow-left"
      size="small"
      to="/timeline"
      variant="text"
    >
      Timeline
    </v-btn>

    <v-alert v-if="error" type="error" variant="tonal">{{ error }}</v-alert>

    <template v-else-if="meeting">
      <h2 class="text-h5 mb-1">{{ meeting.title ?? 'Meeting' }}</h2>
      <div class="text-medium-emphasis mb-4">{{ meeting.occurred_on }}</div>

      <div v-if="attendees.length > 0" class="mb-4">
        <v-chip
          v-for="(a, i) in attendees"
          :key="i"
          class="mr-2 mb-2"
          prepend-icon="mdi-account"
          size="small"
        >
          {{ a }}
        </v-chip>
      </div>

      <v-card class="mb-4">
        <v-card-title>Summary</v-card-title>
        <v-card-text style="white-space: pre-wrap">{{ summary || '(no summary)' }}</v-card-text>
      </v-card>

      <v-row>
        <v-col v-if="decisions.length > 0" cols="12" md="6">
          <v-card>
            <v-card-title>Decisions</v-card-title>

            <v-list density="compact">
              <v-list-item v-for="(d, i) in decisions" :key="i" prepend-icon="mdi-gavel" :title="d" />
            </v-list>
          </v-card>
        </v-col>

        <v-col v-if="actionItems.length > 0" cols="12" md="6">
          <v-card>
            <v-card-title>Action items</v-card-title>

            <v-list density="compact">
              <v-list-item
                v-for="(a, i) in actionItems"
                :key="i"
                prepend-icon="mdi-checkbox-marked-circle-outline"
                :subtitle="a.owner || 'unassigned'"
                :title="a.task"
              />
            </v-list>
          </v-card>
        </v-col>
      </v-row>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue'
  import { useRoute } from 'vue-router'
  import { getMeeting, type Meeting } from '@/services/api'

  interface ActionItem { owner?: string, task?: string, due?: string | null }

  const route = useRoute()
  const meeting = ref<Meeting | null>(null)
  const error = ref<string | null>(null)

  const summary = computed(() => String(meeting.value?.metadata.summary_markdown ?? ''))
  const attendees = computed(() => (meeting.value?.metadata.attendees as string[] | undefined) ?? [])
  const decisions = computed(() => (meeting.value?.metadata.decisions as string[] | undefined) ?? [])
  const actionItems = computed(
    () => (meeting.value?.metadata.action_items as ActionItem[] | undefined) ?? [],
  )

  onMounted(async () => {
    try {
      meeting.value = await getMeeting(route.params.id as string)
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  })
</script>
