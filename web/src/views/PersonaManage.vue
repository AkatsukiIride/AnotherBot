<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2>人设管理</h2>
      <div>
        <router-link to="/personas/import" class="btn btn-outline btn-sm" style="margin-right:8px">导入酒馆卡片</router-link>
        <router-link to="/personas/new" class="btn btn-primary">+ 创建人设</router-link>
      </div>
    </div>
    <div v-if="personas.length === 0" style="color:#999">暂无角色卡，点击上方按钮创建或导入</div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px">
      <div v-for="p in personas" :key="p.id" class="card" style="cursor:pointer" @click="$router.push(`/personas/${p.id}`)">
        <div style="display:flex;justify-content:space-between;align-items:start">
          <div>
            <strong>{{ p.name }}</strong>
            <span v-if="p.is_active" style="color:#4361ee;font-size:12px;margin-left:4px">(当前)</span>
          </div>
        </div>
        <div style="font-size:13px;color:#666;margin-top:4px">{{ p.personality || p.description }}</div>
        <div style="margin-top:8px">
          <button v-if="p.is_active" class="btn btn-sm btn-outline" @click.stop="activate(p.id)">取消活跃</button>
          <button v-else class="btn btn-sm btn-primary" @click.stop="activate(p.id)">设为活跃</button>
          <button class="btn btn-sm btn-danger" @click.stop="remove(p.id)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/api'
import type { Persona } from '@/types'

const personas = ref<Persona[]>([])

onMounted(async () => {
  const res = await api.get('/personas') as any
  personas.value = res.data
})

async function activate(id: string) {
  await api.post(`/personas/${id}/activate`)
  const res = await api.get('/personas') as any
  personas.value = res.data
}

async function remove(id: string) {
  if (!confirm('确认删除？')) return
  await api.delete(`/personas/${id}`)
  personas.value = personas.value.filter(p => p.id !== id)
}
</script>
