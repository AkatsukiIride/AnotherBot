<template>
  <div>
    <router-link to="/personas" style="color:#4361ee;font-size:14px">← 返回</router-link>
    <h2 style="margin-top:8px">导入酒馆角色卡</h2>
    <div class="card">
      <p style="margin-bottom:12px;color:#666">上传 SillyTavern/酒馆 的角色卡 PNG 文件，系统将自动解析并创建对应的人设。</p>
      <input type="file" accept="image/png" @change="upload" />
      <div v-if="loading" style="margin-top:8px">解析中...</div>
      <div v-if="error" style="color:#e63946;margin-top:8px">{{ error }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api'

const router = useRouter()
const loading = ref(false)
const error = ref('')

async function upload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  loading.value = true
  error.value = ''
  const fd = new FormData()
  fd.append('file', file)
  try {
    const res = await api.post('/personas/import', fd, { headers: { 'Content-Type': 'multipart/form-data' } }) as any
    if (res.ok) router.push(`/personas/${res.data.id}`)
    else error.value = res.error
  } catch (e: any) {
    error.value = e.message
  }
  loading.value = false
}
</script>
