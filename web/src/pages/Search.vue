<template>
  <v-container class="py-6">
    <h2 class="text-h5 mb-4">Search</h2>

    <v-text-field
      v-model="q"
      clearable
      density="comfortable"
      hide-details
      placeholder="Search transcripts, diaries, meetings…"
      prepend-inner-icon="mdi-magnify"
      variant="outlined"
      @keyup.enter="run"
    />

    <v-alert v-if="error" class="mt-4" type="error" variant="tonal">{{ error }}</v-alert>

    <v-list v-else class="mt-2" lines="two">
      <v-list-item
        v-for="hit in hits"
        :key="`${hit.ref_kind}:${hit.ref_id}`"
        :to="link(hit)"
      >
        <template #prepend>
          <v-chip class="mr-3" label size="x-small">{{ hit.ref_kind }}</v-chip>
        </template>

        <v-list-item-title>{{ hit.title || hit.ref_id }}</v-list-item-title>
        <v-list-item-subtitle class="text-wrap">{{ hit.snippet }}</v-list-item-subtitle>
      </v-list-item>

      <v-list-item v-if="searched && hits.length === 0" class="text-medium-emphasis">
        No matches.
      </v-list-item>
    </v-list>
  </v-container>
</template>

<script lang="ts" setup>
  import { ref } from 'vue'
  import { search, type SearchHit } from '@/services/api'

  const q = ref('')
  const hits = ref<SearchHit[]>([])
  const error = ref<string | null>(null)
  const searched = ref(false)

  function link (hit: SearchHit): string {
    if (hit.ref_kind === 'recording') return `/recordings/${hit.ref_id}`
    if (hit.ref_kind === 'diary') return `/diary/${hit.ref_id}`
    return `/meetings/${hit.ref_id}`
  }

  async function run (): Promise<void> {
    if (!q.value.trim()) return
    try {
      hits.value = await search(q.value.trim())
      error.value = null
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    } finally {
      searched.value = true
    }
  }
</script>
