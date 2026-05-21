<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2>Dashboard</h2>
      <span v-if="status?.uptime" style="color:#999;font-size:13px">已运行 {{ status.uptime }}</span>
    </div>

    <!-- 平台状态 -->
    <div class="card">
      <h3>平台状态</h3>
      <div v-if="accounts.length === 0" style="color:#999">暂无账户，请先<a href="#/accounts">添加账户</a></div>
      <div v-for="acc in accounts" :key="acc.id" style="padding:10px 0;border-bottom:1px solid #f0f0f0">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <div>
            <span :class="'status-dot status-'+acc.status"></span>
            <strong>{{ acc.name }}</strong>
            <span style="color:#999;margin-left:8px;font-size:13px">{{ acc.platform_id }}</span>
            <span v-if="acc.active_sessions?.length" style="color:#666;margin-left:12px;font-size:13px">
              <span v-for="s in acc.active_sessions" :key="s.key" style="margin-right:12px">{{ s.key }}({{ s.rounds }}轮)</span>
            </span>
            <span v-if="!acc.active_sessions?.length && acc.enabled" style="color:#ccc;margin-left:12px;font-size:13px">暂无活跃对话</span>
          </div>
          <button class="btn btn-sm" :class="acc.enabled ? 'btn-danger' : 'btn-primary'" @click="toggleAccount(acc)">
            {{ acc.enabled ? '禁用' : '启用' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 今日概览 -->
    <div class="card">
      <h3>今日概览 <small style="font-weight:normal;color:#999;font-size:12px">每30秒自动刷新</small></h3>
      <div style="display:flex;gap:48px">
        <div><strong style="font-size:22px">{{ stats.messages_received }}</strong><br><small style="color:#999">消息</small></div>
        <div><strong style="font-size:22px">{{ stats.tokens_used }}</strong><br><small style="color:#999">Token</small></div>
        <div><strong style="font-size:22px">{{ stats.active_sessions }}</strong><br><small style="color:#999">活跃对话</small></div>
      </div>
    </div>

    <!-- 指令使用统计 -->
    <div class="card">
      <h3>指令使用统计</h3>
      <div style="font-size:13px">
        <div v-if="cmdStats.length === 0" style="color:#ccc;padding:10px">暂无数据</div>
        <div v-for="(c,i) in cmdStats" :key="i" style="display:inline-block;padding:4px 12px;margin:4px;background:#f5f6fa;border-radius:6px">
          <span style="color:#e67e22">{{ c.command }}</span>
          <strong style="color:#333;margin-left:4px">{{ c.count }}</strong>
        </div>
      </div>
    </div>
    <!-- 实时消息 -->
    <div class="card">
      <h3>实时消息 <small style="font-weight:normal;color:#999;font-size:12px">(SSE)</small></h3>
      <div ref="feed" style="max-height:350px;overflow-y:auto;font-size:13px;font-family:monospace">
        <div v-if="messages.length === 0" style="color:#ccc;padding:20px 0;text-align:center">等待消息...</div>
        <div v-for="(m,i) in messages" :key="i" style="padding:3px 0;border-bottom:1px solid #f8f8f8">
          <span style="color:#999">{{ m.timestamp }}</span>
          <span style="color:#4361ee">[{{ m.account_name }}]</span>
          <span v-if="m.direction==='received' && !m.is_at_bot" style="color:#ccc;font-size:11px"> ※</span>
          <span :style="{color: m.direction==='sent' ? '#2ecc71' : '#333'}">{{ m.sender || 'Bot' }}: {{ m.content }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onUnmounted, nextTick } from 'vue'
import api from '@/api'

const accounts = ref<any[]>([])
const stats = reactive({ messages_received: 0, tokens_used: 0, active_sessions: 0 })
const messages = ref<any[]>([])
const cmdStats = ref<any[]>([])
const feed = ref<HTMLElement>()
let eventSource: EventSource | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await refreshData()
  fetchCmdStats()

  eventSource = new EventSource('/api/system/events/stream')
  eventSource.addEventListener('message', (e) => {
    const data = JSON.parse(e.data)
    messages.value.push(data)
    if (messages.value.length > 100) messages.value.shift()
    nextTick(() => { if (feed.value) feed.value.scrollTop = feed.value.scrollHeight })
  })
  eventSource.addEventListener('status', (e) => {
    const data = JSON.parse(e.data)
    const acc = accounts.value.find(a => a.id === data.account_id)
    if (acc) acc.status = data.status
  })

  // Auto-refresh stats and cmd logs every 30s
  pollTimer = setInterval(() => { refreshStats(); fetchCmdStats() }, 30000)
})

onUnmounted(() => {
  eventSource?.close()
  if (pollTimer) clearInterval(pollTimer)
})

async function refreshData() {
  await Promise.all([refreshAccounts(), refreshStats()])
}

async function refreshAccounts() {
  try {
    const res = await api.get('/accounts') as any
    accounts.value = res.data || []
  } catch (e) { /* ignore */ }
}

async function refreshStats() {
  try {
    const res = await api.get('/system/status') as any
    if (res.data?.today) {
      stats.messages_received = res.data.today.messages_received
      stats.tokens_used = res.data.today.tokens_used
      stats.active_sessions = res.data.today.active_sessions
    }
  } catch (e) { /* ignore */ }
}

async function fetchCmdStats() {
  try {
    const res = await api.get('/system/commands') as any
    cmdStats.value = res.data || []
  } catch (e) { /* ignore */ }
}

async function toggleAccount(acc: any) {
  const endpoint = acc.enabled ? '/disable' : '/enable'
  await api.post(`/accounts/${acc.id}${endpoint}`)
  await refreshAccounts()
}
</script>
