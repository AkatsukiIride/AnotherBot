<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2>账户管理</h2>
      <router-link to="/accounts/new" class="btn btn-primary">+ 添加账户</router-link>
    </div>
    <div v-if="accounts.length === 0" style="color:#999">暂无账户</div>
    <div v-for="acc in accounts" :key="acc.id" class="card" style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <span :class="'status-dot status-'+acc.status"></span>
          <strong>{{ acc.name }}</strong>
          <span style="color:#999;margin-left:8px">{{ acc.platform_id }}</span>
          <span v-if="acc.active_sessions?.length" style="color:#666;margin-left:8px;font-size:13px">
            活跃对话: <span v-for="s in acc.active_sessions" :key="s.key" style="margin-right:8px">{{ s.key }}({{ s.rounds }}轮)</span>
          </span>
        </div>
        <div style="display:flex;gap:4px">
          <button v-if="acc.enabled" class="btn btn-sm btn-danger" @click="toggle(acc)">禁用</button>
          <button v-else class="btn btn-sm btn-primary" @click="toggle(acc)">启用</button>
          <button class="btn btn-sm btn-outline" @click="$router.push(`/accounts/${acc.id}`)">编辑</button>
          <button class="btn btn-sm btn-danger" @click="remove(acc.id)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import api from '@/api'

const accounts = ref<any[]>([])
let es: EventSource | null = null

onMounted(async () => {
  try {
    const res = await api.get('/accounts') as any
    accounts.value = res.data || []
  } catch (e) {
    console.error('加载账户失败:', e)
  }
  es = new EventSource('/api/system/events/stream')
  es.addEventListener('status', (e) => {
    const data = JSON.parse(e.data)
    const acc = accounts.value.find(a => a.id === data.account_id)
    if (acc) acc.status = data.status
  })
})

onUnmounted(() => { es?.close() })

async function toggle(acc: any) {
  const endpoint = acc.enabled ? '/disable' : '/enable'
  await api.post(`/accounts/${acc.id}${endpoint}`)
  const res = await api.get('/accounts') as any
  accounts.value = res.data
}

async function remove(id: string) {
  if (!confirm('删除账户将同时清空其所有上下文，确认？')) return
  await api.delete(`/accounts/${id}`)
  accounts.value = accounts.value.filter(a => a.id !== id)
}
</script>
