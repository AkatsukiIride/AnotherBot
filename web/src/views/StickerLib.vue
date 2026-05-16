<template>
  <div>
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
      <h2>表情包库</h2>
      <button class="btn btn-primary" @click="showUpload = true">+ 上传表情</button>
    </div>
    <div v-if="showUpload" class="card" style="margin-bottom:16px">
      <input type="file" accept="image/jpeg,image/png,image/gif,image/webp" @change="upload" />
      <button class="btn btn-sm btn-outline" @click="showUpload = false" style="margin-top:8px">取消</button>
    </div>
    <div v-if="stickers.length === 0" style="color:#999">暂无表情包</div>
    <div class="card" v-for="s in stickers" :key="s.id" style="margin-bottom:8px;display:flex;gap:12px;align-items:center;cursor:pointer" @click="preview = preview === s.code ? null : s.code">
      <img :src="'/api/stickers/image/' + s.code" style="width:60px;height:60px;object-fit:cover;border-radius:4px;flex-shrink:0" @error="($event.target as HTMLImageElement).style.display='none'" />
      <div style="flex:1">
        <strong>{{ s.code }}</strong> · {{ s.filename }} · {{ (s.file_size / 1024).toFixed(0) }}KB
        <div style="font-size:13px;color:#666;margin-top:2px">{{ s.description || '(点击添加描述)' }}</div>
      </div>
      <div style="display:flex;gap:4px">
        <button class="btn btn-sm btn-outline" @click.stop="editDesc(s)">编辑描述</button>
        <button class="btn btn-sm btn-outline" @click.stop="reDescribe(s)">重识别</button>
        <button class="btn btn-sm btn-danger" @click.stop="remove(s.id)">删除</button>
      </div>
    </div>
    <!-- Preview modal -->
    <div v-if="preview" style="position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:99;display:flex;align-items:center;justify-content:center" @click="preview = null">
      <img :src="'/api/stickers/image/' + preview" style="max-width:80vw;max-height:80vh;object-fit:contain" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/api'
import type { Sticker } from '@/types'

const stickers = ref<Sticker[]>([])
const showUpload = ref(false)
const preview = ref<string | null>(null)

onMounted(async () => {
  const res = await api.get('/stickers') as any
  stickers.value = res.data
})

async function upload(e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  fd.append('auto_describe', 'false')
  await api.post('/stickers', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
  const res = await api.get('/stickers') as any
  stickers.value = res.data
  showUpload.value = false
}

async function reDescribe(s: Sticker) {
  const res = await api.post(`/stickers/${s.id}/re-describe`) as any
  if (res.ok) s.description = res.data.description
  else alert(res.error || '识别失败')
}

async function editDesc(s: Sticker) {
  const desc = prompt('编辑描述:', s.description)
  if (desc !== null) {
    await api.put(`/stickers/${s.id}`, { description: desc })
    s.description = desc
  }
}

async function remove(id: string) {
  if (!confirm('确认删除？')) return
  const res = await api.delete(`/stickers/${id}`) as any
  if (!res.ok) { alert(res.error); return }
  stickers.value = stickers.value.filter(s => s.id !== id)
}
</script>
