// Live backend events over the WebSocket (/api/v1/ws). Pages subscribe via `on()`
// to refresh themselves without polling. Contract: ../../docs/11-api-specification.md §4
import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface WsEvent {
  type: string
  data: Record<string, unknown>
}

type Listener = (event: WsEvent) => void

export const useEventsStore = defineStore('events', () => {
  const connected = ref(false)
  const last = ref<WsEvent | null>(null)
  const listeners = new Set<Listener>()

  let socket: WebSocket | null = null
  let retry: ReturnType<typeof setTimeout> | null = null

  function on (fn: Listener): () => void {
    listeners.add(fn)
    return () => listeners.delete(fn)
  }

  function connect (): void {
    if (socket) {
      return
    }
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    socket = new WebSocket(`${proto}://${location.host}/api/v1/ws`)

    socket.addEventListener('open', () => {
      connected.value = true
    })
    socket.addEventListener('message', event => {
      const parsed = JSON.parse(event.data as string) as WsEvent
      last.value = parsed
      for (const fn of listeners) {
        fn(parsed)
      }
    })
    socket.addEventListener('close', () => {
      connected.value = false
      socket = null
      scheduleReconnect()
    })
    socket.addEventListener('error', () => socket?.close())
  }

  function scheduleReconnect (): void {
    if (retry) {
      return
    }
    retry = setTimeout(() => {
      retry = null
      connect()
    }, 2000)
  }

  return { connected, last, on, connect }
})
