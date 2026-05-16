<template>
  <div>
    <router-link to="/personas" style="color:#4361ee;font-size:14px">← 返回</router-link>
    <h2 style="margin-top:8px">{{ isNew ? '创建人设' : '编辑人设: ' + form.name }}</h2>

    <div class="card">
      <div style="display:flex;gap:20px">
        <div style="flex:1">
          <label>名称</label>
          <input v-model="form.name" />
          <label>作者</label>
          <input v-model="form.author" />
          <label>描述</label>
          <textarea v-model="form.description" rows="2"></textarea>
          <label>性格</label>
          <textarea v-model="form.personality" rows="2"></textarea>
          <label>场景</label>
          <input v-model="form.scenario" />
        </div>
        <div style="flex:1">
          <label>开场白</label>
          <textarea v-model="form.first_message" rows="2"></textarea>
          <label>自定义 Prompt</label>
          <textarea v-model="form.custom_prompt" rows="2"></textarea>
          <label>对话后指令</label>
          <textarea v-model="form.post_instructions" rows="2"></textarea>
          <label>对话示例 (每行一对，格式: 用户: xxx | Bot: yyy)</label>
          <textarea v-model="form.example_dialogue" rows="3"></textarea>
        </div>
      </div>
      <div style="margin-top:16px;display:flex;gap:8px">
        <button class="btn btn-primary" @click="save">保存</button>
        <router-link to="/personas" class="btn btn-outline">取消</router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const isNew = route.params.id === 'new' || !route.params.id

const form = ref({ name: '', author: '', description: '', personality: '', scenario: '', first_message: '', custom_prompt: '', post_instructions: '', example_dialogue: '' })

onMounted(async () => {
  if (!isNew) {
    const res = await api.get(`/personas/${route.params.id}`) as any
    if (res.ok) Object.assign(form.value, res.data)
  }
})

async function save() {
  if (isNew) {
    await api.post('/personas', form.value)
  } else {
    await api.put(`/personas/${route.params.id}`, form.value)
  }
  router.push('/personas')
}
</script>
