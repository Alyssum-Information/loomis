/**
 * router/index.ts — manual routes for the read-only screens (M3 PR E).
 */
import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '@/pages/index.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/timeline', name: 'timeline', component: () => import('@/pages/Timeline.vue') },
    {
      path: '/recordings/:id',
      name: 'recording',
      component: () => import('@/pages/Recording.vue'),
    },
    { path: '/diary/:date', name: 'diary', component: () => import('@/pages/Diary.vue') },
    { path: '/meetings/:id', name: 'meeting', component: () => import('@/pages/Meeting.vue') },
    { path: '/speakers', name: 'speakers', component: () => import('@/pages/Speakers.vue') },
    { path: '/records', name: 'records', component: () => import('@/pages/Records.vue') },
  ],
})

export default router
