/**
 * Typed client for the Loomis backend API.
 *
 * Uses same-origin "/api/v1" paths: proxied to the backend in dev (see
 * vite.config.mts), served by the backend itself in production.
 * Contract: ../../docs/11-api-specification.md
 */

const BASE = '/api/v1'

export interface Health {
  status: string
  version: string
  db_version: number | null
}

async function getJson<T> (path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} ${res.statusText}`)
  }
  return await res.json() as T
}

export function getHealth (): Promise<Health> {
  return getJson<Health>('/health')
}
