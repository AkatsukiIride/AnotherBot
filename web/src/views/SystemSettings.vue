<template>
  <div>
    <h2>系统设置</h2>
    <div v-for="cat in ['chat','vision']" :key="cat" class="card">
      <h3>{{ cat === 'chat' ? '对话模型 (chat)' : '识图模型 (vision)' }} <small v-if="cat==='vision'" style="color:#999">V2</small></h3>
      <div v-if="providersByCategory(cat).length === 0" style="color:#999">{{ cat === 'vision' ? '未配置' : '未配置' }}</div>
      <div v-for="p in providersByCategory(cat)" :key="p.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center">
        <div>
          <strong>{{ p.name }}</strong> ({{ p.model }}) <span v-if="p.is_default" style="color:#4361ee">默认</span>
        </div>
        <div style="display:flex;gap:6px">
          <button class="btn btn-sm btn-outline" @click="edit(p)">编辑</button>
          <button class="btn btn-sm btn-primary" @click="test(p.id)">测试</button>
          <button v-if="!p.is_default" class="btn btn-sm btn-outline" @click="setDefault(p)">设为默认</button>
          <button class="btn btn-sm btn-danger" @click="remove(p.id)">删除</button>
        </div>
      </div>
      <button class="btn btn-primary" style="margin-top:12px" @click="add(cat)">+ 添加{{ cat === 'chat' ? '对话' : '识图' }}模型</button>
    </div>
    <div v-if="showModal" class="card" style="position:fixed;top:50%;left:50%;transform:translate(-50%,-50%);z-index:100;width:400px;box-shadow:0 4px 20px rgba(0,0,0,0.15)">
      <h3>{{ editingId ? '编辑' : '添加' }}模型</h3>
      <label>名称</label><input v-model="modal.name" />
      <label>类别</label><select v-model="modal.category"><option value="chat">对话</option><option value="vision">识图</option></select>
      <label>模型名</label><input v-model="modal.model" placeholder="qwen-turbo" />
      <label>API Key <span v-if="editingId" style="color:#999;font-size:12px">(留空不修改)</span></label><input v-model="modal.api_key" type="password" :placeholder="editingId ? '已保存, 留空则不修改' : 'sk-xxx...'" />
      <label>Base URL</label><input v-model="modal.base_url" />
      <label>温度</label><input v-model.number="modal.temperature" type="number" step="0.1" />
      <label>Max Tokens</label><input v-model.number="modal.max_tokens" type="number" />
      <label><input type="checkbox" v-model="modal.is_default" style="width:auto;margin:0 4px 0 0" />设为默认</label>
      <div style="margin-top:12px;display:flex;gap:8px">
        <button class="btn btn-primary" @click="saveModal">保存</button>
        <button class="btn btn-outline" @click="showModal = false">取消</button>
      </div>
    </div>
    <div v-if="showModal" style="position:fixed;inset:0;background:rgba(0,0,0,0.2);z-index:99" @click="showModal = false"></div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive } from 'vue'
import api from '@/api'
import type { Provider } from '@/types'

const providers = ref<Provider[]>([])
const showModal = ref(false)
const editingId = ref<string | null>(null)
const modal = reactive({ name: '', category: 'chat', model: '', api_key: '', base_url: '', temperature: 0.8, max_tokens: 512, is_default: false })

function providersByCategory(cat: string) {
  return providers.value.filter(p => p.category === cat)
}

onMounted(async () => {
  const res = await api.get('/providers') as any
  providers.value = res.data || []
})

function add(cat: string) {
  editingId.value = null
  Object.assign(modal, { name: '', category: cat, model: '', api_key: '', base_url: '', temperature: 0.8, max_tokens: 512, is_default: false })
  showModal.value = true
}

function edit(p: Provider) {
  editingId.value = p.id
  Object.assign(modal, { name: p.name, category: p.category, model: p.model, api_key: '', base_url: p.base_url, temperature: p.temperature, max_tokens: p.max_tokens, is_default: p.is_default })
  showModal.value = true
}

async function saveModal() {
  if (editingId.value) {
    await api.put(`/providers/${editingId.value}`, { ...modal })
  } else {
    await api.post('/providers', { ...modal })
  }
  const res = await api.get('/providers') as any
  providers.value = res.data || []
  showModal.value = false
}

async function test(id: string) {
  const res = await api.post(`/providers/${id}/test`) as any
  if (res.data?.success) alert(`连接成功! 延迟: ${res.data.latency_ms}ms`)
  else alert('连接失败: ' + (res.data?.error || res.error))
}

async function setDefault(p: Provider) {
  await api.put(`/providers/${p.id}`, { is_default: true })
  const res = await api.get('/providers') as any
  providers.value = res.data || []
}

async function remove(id: string) {
  if (!confirm('确认删除？')) return
  await api.delete(`/providers/${id}`)
  providers.value = providers.value.filter(p => p.id !== id)
}
</script>
