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
  import { onMounted, ref } from 'vue'
  import { useRoute } from 'vue-router'
  import { useEventsStore } from '@/stores/events'

  const route = useRoute()
  const events = useEventsStore()
  const newDevice = ref(false)

  const nav = [
    { title: 'Dashboard', icon: 'mdi-view-dashboard', to: '/' },
    { title: 'Timeline', icon: 'mdi-timeline-clock', to: '/timeline' },
    { title: 'Search', icon: 'mdi-magnify', to: '/search' },
    { title: 'Speakers', icon: 'mdi-account-voice', to: '/speakers' },
    { title: 'Devices', icon: 'mdi-usb-flash-drive', to: '/devices' },
    { title: 'Jobs', icon: 'mdi-cog-sync', to: '/jobs' },
  ]

  onMounted(() => {
    events.connect()
    // FR-1.3: prompt the user when an (unregistered) recorder appears.
    events.on(event => {
      if (event.type === 'device.connected' && event.data.registered === false) {
        newDevice.value = true
      }
    })
  })
</script>
