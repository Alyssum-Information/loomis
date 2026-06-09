<template>
  <v-container class="py-6">
    <div class="d-flex align-center mb-4">
      <h2 class="text-h5">Devices</h2>

      <v-spacer />

      <v-btn color="primary" prepend-icon="mdi-plus" variant="tonal" @click="openAdd">
        Add device
      </v-btn>
    </div>

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

    <v-row>
      <v-col
        v-for="d in devices"
        :key="d.id"
        cols="12"
        lg="4"
        md="6"
      >
        <v-card v-if="edits[d.id]" class="h-100 d-flex flex-column">
          <v-card-title class="d-flex align-center ga-2">
            <v-icon size="small">mdi-usb-flash-drive</v-icon>

            <v-text-field
              v-model="edits[d.id].name"
              density="compact"
              hide-details
              variant="plain"
            />

            <v-chip :color="d.registered ? 'success' : 'grey'" label size="x-small">
              {{ d.registered ? 'registered' : 'inactive' }}
            </v-chip>
          </v-card-title>

          <v-card-text class="flex-grow-1">
            <div class="text-medium-emphasis text-caption mb-3">
              Last seen: {{ d.last_seen_at ?? '—' }}
            </div>

            <v-switch
              v-model="edits[d.id].auto_delete"
              color="primary"
              density="compact"
              hide-details
              label="Auto-delete source after backup"
            />

            <v-select
              v-model="edits[d.id].transcode_policy"
              class="mt-2"
              density="compact"
              hide-details
              :items="policies"
              label="Transcode"
              variant="outlined"
            />
          </v-card-text>

          <v-card-actions>
            <v-btn size="small" variant="text" @click="save(d.id)">Save</v-btn>

            <v-spacer />

            <v-btn
              v-if="d.registered"
              color="error"
              size="small"
              variant="text"
              @click="unregister(d.id)"
            >
              Unregister
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-col>

      <v-col v-if="devices.length === 0" cols="12">
        <v-card variant="tonal">
          <v-card-text class="text-medium-emphasis text-center py-8">
            No devices yet. Plug in a recorder, or use <strong>Add device</strong>.
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-dialog v-model="addOpen" max-width="520">
      <v-card>
        <v-card-title>Register a device</v-card-title>

        <v-card-text>
          <p class="text-medium-emphasis mb-4">
            Point Loomis at the recorder's mounted drive or folder. A
            <code>.loomis/device.json</code> marker is written there and the device
            starts auto-importing.
          </p>

          <v-text-field
            v-model="addVolume"
            class="mb-2"
            density="comfortable"
            hint="e.g. E:\\ on Windows, or /Volumes/RECORDER"
            label="Drive or folder path"
            persistent-hint
          />

          <v-text-field v-model="addName" density="comfortable" label="Name (optional)" />
        </v-card-text>

        <v-card-actions>
          <v-spacer />

          <v-btn variant="text" @click="addOpen = false">Cancel</v-btn>

          <v-btn color="primary" :disabled="!addVolume.trim()" variant="flat" @click="addDevice">
            Register
          </v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
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
    unregisterDevice,
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

  const addOpen = ref(false)
  const addVolume = ref('')
  const addName = ref('')

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

  function openAdd (): void {
    addVolume.value = ''
    addName.value = ''
    addOpen.value = true
  }

  function addDevice (): void {
    const volume = addVolume.value.trim()
    if (!volume) return
    addOpen.value = false
    void act(() => registerDevice({ volume, name: addName.value.trim() || undefined }))
  }

  function unregister (id: string): void {
    void act(() => unregisterDevice(id))
  }

  onMounted(() => {
    refresh()
    events.on(event => {
      if (event.type === 'device.connected') refresh()
    })
  })
</script>
