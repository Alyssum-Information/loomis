<template>
  <v-app>
    <v-navigation-drawer permanent>
      <v-list-item class="py-3" prepend-icon="mdi-waveform" subtitle="lifelog" title="Loomis" />
      <v-divider />

      <v-list density="compact" nav>
        <v-list-item
          v-for="item in nav"
          :key="item.to"
          :prepend-icon="item.icon"
          :title="item.title"
          :to="item.to"
        />
      </v-list>
    </v-navigation-drawer>

    <v-app-bar flat>
      <v-app-bar-title>{{ route.name ?? 'Loomis' }}</v-app-bar-title>
      <v-spacer />

      <div class="search-wrap mr-4">
        <v-text-field
          v-model="q"
          clearable
          density="compact"
          hide-details
          placeholder="Search…"
          prepend-inner-icon="mdi-magnify"
          single-line
          variant="solo-filled"
          @blur="onBlur"
          @focus="focused = true"
          @keyup.enter="run"
          @update:model-value="onInput"
        />

        <v-card v-if="open" class="search-results" elevation="6">
          <v-list density="compact" lines="two">
            <v-list-item
              v-for="hit in results"
              :key="`${hit.ref_kind}:${hit.ref_id}`"
              @mousedown.prevent="go(hit)"
            >
              <template #prepend>
                <v-chip class="mr-2" label size="x-small">{{ hit.ref_kind }}</v-chip>
              </template>

              <v-list-item-title>{{ hit.title || hit.ref_id }}</v-list-item-title>
              <v-list-item-subtitle class="text-wrap">{{ hit.snippet }}</v-list-item-subtitle>
            </v-list-item>

            <v-list-item v-if="results.length === 0" class="text-medium-emphasis">No matches.</v-list-item>
          </v-list>
        </v-card>
      </div>

      <v-chip
        class="mr-4"
        :color="events.connected ? 'success' : 'grey'"
        label
        size="small"
        variant="tonal"
      >
        <v-icon size="small" start>mdi-circle</v-icon>
        {{ events.connected ? 'live' : 'offline' }}
      </v-chip>
    </v-app-bar>

    <v-main>
      <router-view />
    </v-main>

    <v-snackbar v-model="newDevice" location="bottom right" :timeout="-1">
      A new recorder was connected.
      <template #actions>
        <v-btn color="primary" to="/devices" variant="text" @click="newDevice = false">
          Manage
        </v-btn>
      </template>
    </v-snackbar>
  </v-app>
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue'
  import { useRoute, useRouter } from 'vue-router'
  import { search, type SearchHit } from '@/services/api'
  import { useEventsStore } from '@/stores/events'

  const route = useRoute()
  const router = useRouter()
  const events = useEventsStore()
  const newDevice = ref(false)

  const q = ref('')
  const results = ref<SearchHit[]>([])
  const focused = ref(false)
  const searched = ref(false)
  const open = computed(() => focused.value && searched.value && q.value.trim().length > 0)

  const nav = [
    { title: 'Dashboard', icon: 'mdi-view-dashboard', to: '/' },
    { title: 'Timeline', icon: 'mdi-timeline-clock', to: '/timeline' },
    { title: 'Speakers', icon: 'mdi-account-voice', to: '/speakers' },
    { title: 'Devices', icon: 'mdi-usb-flash-drive', to: '/devices' },
    { title: 'Jobs', icon: 'mdi-cog-sync', to: '/jobs' },
  ]

  async function run (): Promise<void> {
    const term = q.value.trim()
    if (!term) {
      results.value = []
      searched.value = false
      return
    }
    try {
      results.value = await search(term, 8)
    } catch {
      results.value = []
    } finally {
      searched.value = true
    }
  }

  function onInput (): void {
    if (q.value.trim().length >= 2) void run()
    else searched.value = false
  }

  function onBlur (): void {
    // Delay so a result @mousedown can fire before the dropdown closes.
    setTimeout(() => (focused.value = false), 150)
  }

  function go (hit: SearchHit): void {
    const path = hit.ref_kind === 'recording'
      ? `/recordings/${hit.ref_id}`
      : (hit.ref_kind === 'diary'
        ? `/diary/${hit.ref_id}`
        : `/meetings/${hit.ref_id}`)
    q.value = ''
    searched.value = false
    focused.value = false
    void router.push(path)
  }

  onMounted(() => {
    events.connect()
    events.on(event => {
      if (event.type === 'device.connected' && event.data.registered === false) {
        newDevice.value = true
      }
    })
  })
</script>

<style scoped>
.search-wrap {
  position: relative;
  width: 320px;
}
.search-results {
  position: absolute;
  top: 100%;
  right: 0;
  left: 0;
  z-index: 1000;
  margin-top: 4px;
  max-height: 60vh;
  overflow-y: auto;
}
</style>
