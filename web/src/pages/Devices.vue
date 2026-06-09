<template>
  <v-container class="py-6">
    <h2 class="text-h5 mb-4">Devices</h2>

    <v-alert v-if="error" class="mb-4" type="error" variant="tonal">{{ error }}</v-alert>

    <v-alert
      v-for="p in pending"
      :key="p.volume"
      class="mb-3"
      icon="mdi-usb-flash-drive"
      type="info"
      variant="tonal"
    >
      <div class="d-flex align-center ga-3">
        <span>Unregistered recorder at <strong>{{ p.volume }}</strong></span>

        <v-text-field
          v-model="registerNames[p.volume]"
          density="compact"
          hide-details
          label="Name"
          style="max-width: 220px"
        />

        <v-btn color="primary" size="small" variant="flat" @click="doRegister(p.volume)">
          Register
        </v-btn>
      </div>
    </v-alert>

    <v-card>
      <v-table density="comfortable">
        <thead>
          <tr>
            <th>Name</th>
            <th>Auto-delete</th>
            <th>Transcode</th>
            <th>Last seen</th>
            <th />
          </tr>
        </thead>

        <tbody>
          <tr v-for="d in devices" :key="d.id">
            <td style="min-width: 200px">
              <v-text-field v-model="edits[d.id].name" density="compact" hide-details variant="plain" />
            </td>

            <td>
              <v-switch v-model="edits[d.id].auto_delete" color="primary" density="compact" hide-details />
            </td>

            <td style="min-width: 180px">
              <v-select
                v-model="edits[d.id].transcode_policy"
                density="compact"
                hide-details
                :items="policies"
                variant="plain"
              />
            </td>

            <td class="text-medium-emphasis">{{ d.last_seen_at ?? '—' }}</td>

            <td class="text-right">
              <v-btn size="small" variant="text" @click="save(d.id)">Save</v-btn>
            </td>
          </tr>

          <tr v-if="devices.length === 0">
            <td class="text-medium-emphasis" colspan="5">No devices registered.</td>
          </tr>
        </tbody>
      </v-table>
    </v-card>
  </v-container>
</template>

<script lang="ts" setup>
  import { onMounted, ref } from 'vue'
  import {
    type Device,
    getPendingDevices,
    listDevices,
    type PendingDevice,
    registerDevice,
    updateDevice,
  } from '@/services/api'
  import { useEventsStore } from '@/stores/events'

  interface Edit { name: string, auto_delete: boolean, transcode_policy: string }

  const devices = ref<Device[]>([])
  const pending = ref<PendingDevice[]>([])
  const edits = ref<Record<string, Edit>>({})
  const registerNames = ref<Record<string, string>>({})
  const error = ref<string | null>(null)
  const events = useEventsStore()

  const policies = ['keep_original', 'transcode_keep', 'transcode_only']

  async function refresh (): Promise<void> {
    try {
      devices.value = await listDevices()
      for (const d of devices.value) {
        edits.value[d.id] = {
          name: d.name,
          auto_delete: d.auto_delete,
          transcode_policy: d.transcode_policy,
        }
      }
      pending.value = await getPendingDevices()
      error.value = null
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  async function act (fn: () => Promise<unknown>): Promise<void> {
    try {
      await fn()
      await refresh()
    } catch (error_) {
      error.value = error_ instanceof Error ? error_.message : String(error_)
    }
  }

  function save (id: string): void {
    void act(() => updateDevice(id, edits.value[id]))
  }

  function doRegister (volume: string): void {
    void act(() => registerDevice({ volume, name: registerNames.value[volume] || undefined }))
  }

  onMounted(() => {
    refresh()
    events.on(event => {
      if (event.type === 'device.connected') refresh()
    })
  })
</script>
