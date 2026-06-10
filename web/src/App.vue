<template>
  <v-app>
    <v-app-bar>
      <template #prepend>
        <v-app-bar-nav-icon @click="drawer = !drawer" />
      </template>

      <v-app-bar-title>
        <v-icon icon="mdi-waveform" />
        Loomis
      </v-app-bar-title>

      <div class="search-wrap">
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

      <v-spacer />

      <!-- The mandatory egress indicator (FR-7.8): visible whenever any configured
           feature can send data off this machine. -->
      <v-chip
        v-if="egressKinds.length > 0"
        class="mr-2"
        color="warning"
        label
        prepend-icon="mdi-cloud-upload-outline"
        size="small"
        to="/settings"
      >
        egress: {{ egressKinds.join(', ') }}
      </v-chip>
    </v-app-bar>

    <v-navigation-drawer v-model="drawer">
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

    <v-main>
      <router-view />
    </v-main>

    <v-footer app class="system-bar text-caption px-4 py-0" height="26">
      <v-icon :color="events.connected ? 'success' : 'grey'" size="10">mdi-circle</v-icon>
      <span class="ml-1">{{ events.connected ? 'live' : 'offline' }}</span>

      <template v-if="jobStats.length > 0">
        <span class="mx-2 text-disabled">·</span>

        <span v-for="p in jobStats" :key="p.label" class="mr-2" :class="p.cls">
          {{ p.count }} {{ p.label }}
        </span>
      </template>

      <v-spacer />

      <template v-if="health.data">
        <span>Loomis v{{ health.data.version }}</span>
        <span class="mx-2 text-disabled">·</span>
        <span>DB schema {{ health.data.db_version }}</span>
      </template>

      <span v-else-if="health.error" class="text-error">backend offline</span>
      <span v-else class="text-disabled">connecting…</span>
    </v-footer>

    <v-snackbar v-model="newDevice" location="bottom right" :timeout="-1">
      A new recorder was connected.
      <template #actions>
        <v-btn color="primary" to="/" variant="text" @click="newDevice = false">
          Manage
        </v-btn>
      </template>
    </v-snackbar>
  </v-app>
</template>

<script lang="ts" setup>
  import { computed, onMounted, ref } from 'vue'
  import { useRouter } from 'vue-router'
  import {
    type EgressStatus,
    getSettings,
    type Job,
    listJobs,
    search,
    type SearchHit,
  } from '@/services/api'
  import { useEventsStore } from '@/stores/events'
  import { useHealthStore } from '@/stores/health'

  const router = useRouter()
  const events = useEventsStore()
  const health = useHealthStore()
  const newDevice = ref(false)
  const drawer = ref(true)

  // Pipeline job counts shown in the system bar, newest figures pushed live.
  const jobs = ref<Job[]>([])

  const jobStats = computed<{ label: string, count: number, cls: string }[]>(() => {
    const counts: Record<string, number> = {}
    for (const job of jobs.value) counts[job.status] = (counts[job.status] ?? 0) + 1
    const order: [string, string][] = [
      ['running', 'text-info'],
      ['queued', ''],
      ['parked', 'text-error'],
      ['failed', 'text-error'],
    ]
    return order
      .filter(([key]) => counts[key])
      .map(([key, cls]) => ({ label: key, count: counts[key], cls }))
  })

  async function refreshJobs (): Promise<void> {
    try {
      jobs.value = await listJobs({ limit: 200 })
    } catch { /* system-bar counts are best-effort */ }
  }

  const q = ref('')
  const results = ref<SearchHit[]>([])
  const focused = ref(false)
  const searched = ref(false)
  const open = computed(() => focused.value && searched.value && q.value.trim().length > 0)

  const nav = [
    { title: 'Dashboard', icon: 'mdi-view-dashboard', to: '/' },
    { title: 'Timeline', icon: 'mdi-timeline-clock', to: '/timeline' },
    { title: 'Speakers', icon: 'mdi-account-voice', to: '/speakers' },
    { title: 'Records', icon: 'mdi-cog-sync', to: '/records' },
    { title: 'Settings', icon: 'mdi-cog', to: '/settings' },
  ]

  // Egress indicator (FR-7.8): which features can currently send data off-machine.
  const egress = ref<EgressStatus | null>(null)

  const egressKinds = computed(() => {
    if (!egress.value) return []
    return Object.entries(egress.value)
      .filter(([, on]) => on)
      .map(([kind]) => kind.replace('_', ' '))
  })

  async function refreshEgress (): Promise<void> {
    try {
      egress.value = (await getSettings()).egress
    } catch { /* indicator is best-effort */ }
  }

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
    health.refresh()
    refreshJobs()
    refreshEgress()
    events.connect()
    events.on(event => {
      if (event.type === 'job.updated' || event.type === 'recording.added') {
        refreshJobs()
      }
      if (event.type === 'egress.pending' || event.type === 'egress.started') {
        refreshEgress()
      }
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
.system-bar {
  border-top: thin solid rgba(var(--v-border-color), var(--v-border-opacity));
  min-height: 26px;
}
</style>
