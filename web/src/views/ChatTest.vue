<template>
  <div>
    <h2>对话测试</h2>
    <div class="card" style="padding:12px 20px;display:flex;gap:16px;align-items:center;margin-bottom:12px">
      <select v-model="personaId" style="width:auto;margin:0">
        <option value="">系统默认人设</option>
        <option v-for="p in personas" :key="p.id" :value="p.id">{{ p.name }}{{ p.is_active ? ' (活跃)' : '' }}</option>
      </select>
      <select v-model="providerId" style="width:auto;margin:0">
        <option value="">系统默认模型</option>
        <option v-for="p in chatProviders" :key="p.id" :value="p.id">{{ p.name }} ({{ p.model }})</option>
      </select>
      <button class="btn btn-sm btn-outline" @click="resetChat">重置上下文</button>
    </div>
    <div class="card" style="height:400px;overflow-y:auto;margin-bottom:12px" ref="chatBox">
      <div v-for="(m,i) in messages" :key="i" :style="{textAlign:m.role==='user'?'right':'left',margin:'8px 0'}">
        <span :style="{display:'inline-block',padding:'8px 14px',borderRadius:'12px',maxWidth:'80%',background:m.role==='user'?'#4361ee':'#f0f0f0',color:m.role==='user'?'#fff':'#333'}">{{ m.content }}</span>
      </div>
    </div>
    <div style="display:flex;gap:8px">
      <input v-model="input" @keyup.enter="send" placeholder="输入消息... /reset /new /status /help" style="flex:1;margin:0" />
      <button class="btn btn-primary" @click="send" :disabled="streaming">发送</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import api from '@/api'

const personas = ref<any[]>([])
const chatProviders = ref<any[]>([])
const personaId = ref('')
const providerId = ref('')
const messages = ref<{role:string;content:string}[]>([])
const input = ref('')
const streaming = ref(false)
const chatBox = ref<HTMLElement>()

let ws: WebSocket | null = null

onMounted(async () => {
  const [pRes, provRes] = await Promise.all([
    api.get('/personas') as any,
    api.get('/providers') as any,
  ])
  personas.value = pRes.data
  chatProviders.value = (provRes.data || []).filter((p:any) => p.category === 'chat')
})

function connectWs() {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  ws = new WebSocket(`${protocol}//${location.host}/ws/chat-test`)
  ws.onmessage = (e) => {
    const data = JSON.parse(e.data)
    if (data.type === 'chunk') {
      if (messages.value[messages.value.length-1]?.role !== 'assistant') {
        messages.value.push({ role: 'assistant', content: data.content })
      } else {
        messages.value[messages.value.length-1].content += data.content
      }
      scrollDown()
    } else if (data.type === 'done') {
      streaming.value = false
    } else if (data.type === 'command_result') {
      messages.value.push({ role: 'assistant', content: data.message })
    } else if (data.type === 'error') {
      streaming.value = false
      messages.value.push({ role: 'assistant', content: 'Error: ' + data.message })
    }
  }
}

async function send() {
  const msg = input.value.trim()
  if (!msg || streaming.value) return
  input.value = ''

  // Handle commands locally
  if (msg.startsWith('/')) {
    if (!ws || ws.readyState !== WebSocket.OPEN) connectWs()
    await new Promise(r => setTimeout(r, 100)) // wait for connection
    messages.value.push({ role: 'user', content: msg })
    ws!.send(JSON.stringify({ action: 'command', command: msg }))
    scrollDown()
    return
  }

  if (!ws || ws.readyState !== WebSocket.OPEN) connectWs()
  await new Promise(r => setTimeout(r, 100))

  messages.value.push({ role: 'user', content: msg })
  streaming.value = true
  ws!.send(JSON.stringify({
    action: 'send', message: msg,
    persona_id: personaId.value || null,
    provider_id: providerId.value || null,
  }))
  scrollDown()
}

function resetChat() {
  messages.value = []
  if (ws) ws.close()
  connectWs()
}

function scrollDown() {
  nextTick(() => {
    if (chatBox.value) chatBox.value.scrollTop = chatBox.value.scrollHeight
  })
}
</script>
