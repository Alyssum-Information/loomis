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

    <template v-else-if="entry">
      <h2 class="text-h5 mb-1">{{ entry.title ?? entry.date }}</h2>
      <div class="text-medium-emphasis mb-4">{{ entry.date }}</div>

      <v-card class="mb-4">
        <v-card-text style="white-space: pre-wrap">{{ narrative || '(no entry)' }}</v-card-text>
      </v-card>

      <v-row>
        <v-col v-if="todos.length > 0" cols="12" md="6">
          <v-card>
            <v-card-title>To-dos</v-card-title>

            <v-list density="compact">
              <v-list-item v-for="(t, i) in todos" :key="i" prepend-icon="mdi-checkbox-blank-outline" :title="t" />
            </v-list>
          </v-card>
        </v-col>

        <v-col v-if="decisions.length > 0" cols="12" md="6">
          <v-card>
            <v-card-title>Decisions</v-card-title>

            <v-list density="compact">
              <v-list-item v-for="(d, i) in decisions" :key="i" prepend-icon="mdi-gavel" :title="d" />
            </v-list>
          </v-card>
        </v-col>
      </v-row>

      <div v-if="topics.length > 0" class="mt-4">
        <v-chip
          v-for="(t, i) in topics"
          :key="i"
          class="mr-2 mb-2"
          label
          size="small"
        >{{ t }}</v-chip>
      </div>
    </template>
  </v-container>
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue'
  import { useRoute } from 'vue-router'
  import { type DiaryEntry, getDiary } from '@/services/api'

  const route = useRoute()
  const entry = ref<DiaryEntry | null>(null)
  const error = ref<string | null>(null)

  const narrative = computed(() => String(entry.value?.metadata.narrative_markdown ?? ''))
  const todos = computed(() => (entry.value?.metadata.todos as string[] | undefined) ?? [])
  const decisions = computed(() => (entry.value?.metadata.decisions as string[] | undefined) ?? [])
  const topics = computed(() => (entry.value?.metadata.topics as string[] | undefined) ?? [])

  onMounted(async () => {
    try {
      entry.value = await getDiary(route.params.date as string)
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  })
</script>
