<template>
  <v-container class="py-8">
    <v-row justify="center">
      <v-col cols="12" md="6" sm="8">
        <v-card>
          <v-card-title class="d-flex align-center justify-space-between">
            <span>Loomis backend</span>
            <v-chip :color="chipColor" label size="small">{{ chipText }}</v-chip>
          </v-card-title>

          <v-card-text>
            <template v-if="store.data">
              <div>Status: <strong>{{ store.data.status }}</strong></div>
              <div>Version: <strong>{{ store.data.version }}</strong></div>
              <div>DB version: <strong>{{ store.data.db_version }}</strong></div>
            </template>

            <v-alert v-else-if="store.error" type="error" variant="tonal">
              Cannot reach backend: {{ store.error }}
            </v-alert>

            <div v-else class="text-medium-emphasis">Checking…</div>
          </v-card-text>

          <v-card-actions>
            <v-btn :loading="store.loading" variant="tonal" @click="store.refresh()">
              Refresh
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script lang="ts" setup>
  import { computed, onMounted } from 'vue'
  import { useHealthStore } from '@/stores/health'

  const store = useHealthStore()

  const chipColor = computed(() => (store.error ? 'error' : (store.data ? 'success' : 'grey')))
  const chipText = computed(() => (store.error ? 'offline' : (store.data ? 'online' : '…')))

  onMounted(() => store.refresh())
</script>
