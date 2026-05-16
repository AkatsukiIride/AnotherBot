<template>
  <div>
    <h2>日志</h2>
    <div style="margin-bottom:12px;display:flex;gap:8px">
      <select v-model="level" style="width:auto">
        <option value="">全部</option>
        <option value="ERROR">ERROR</option>
        <option value="WARNING">WARNING</option>
        <option value="INFO">INFO</option>
      </select>
      <button class="btn btn-sm btn-primary" @click="fetch">刷新</button>
    </div>
    <div class="card" ref="logBox" style="font-family:monospace;font-size:13px;max-height:500px;overflow-y:auto;white-space:pre-wrap">
      <div v-for="(line,i) in logs" :key="i" style="padding:2px 0" :style="{color:line.includes('ERROR')?'#e63946':line.includes('WARNING')?'#f39c12':'#333'}">{{ line }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import api from '@/api'

const logs = ref<string[]>([])
const level = ref('')
const logBox = ref<HTMLElement>()

let timer: ReturnType<typeof setInterval> | null = null
onMounted(() => { fetch(); timer = setInterval(fetch, 5000) })
onUnmounted(() => { if (timer) clearInterval(timer) })

async function fetch() {
  const params: any = { limit: 100 }
  if (level.value) params.level = level.value
  const res = await api.get('/system/logs', { params }) as any
  logs.value = (res.data || []).reverse()  // Newest first
  nextTick(() => { if (logBox.value) logBox.value.scrollTop = 0 })
}
</script>
