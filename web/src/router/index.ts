import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/', component: () => import('@/views/Dashboard.vue') },
  { path: '/personas', component: () => import('@/views/PersonaManage.vue') },
  { path: '/personas/import', component: () => import('@/views/PersonaImport.vue') },
  { path: '/personas/:id', component: () => import('@/views/PersonaEdit.vue') },
  { path: '/chat-test', component: () => import('@/views/ChatTest.vue') },
  { path: '/accounts', component: () => import('@/views/AccountManage.vue') },
  { path: '/accounts/new', component: () => import('@/views/AccountEdit.vue') },
  { path: '/accounts/:id', component: () => import('@/views/AccountEdit.vue') },
  { path: '/stickers', component: () => import('@/views/StickerLib.vue') },
  { path: '/settings', component: () => import('@/views/SystemSettings.vue') },
  { path: '/logs', component: () => import('@/views/LogViewer.vue') },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
