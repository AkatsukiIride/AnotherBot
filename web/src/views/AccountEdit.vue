<template>
  <div>
    <router-link to="/accounts" style="color:#4361ee;font-size:14px">← 返回</router-link>
    <h2 style="margin-top:8px">{{ isNew ? '添加账户' : '编辑账户: ' + form.name }}</h2>
    <div class="card">
      <div style="display:flex;gap:12px">
        <div style="flex:1">
          <label>账户名称</label>
          <input v-model="form.name" placeholder="如: 大号-吐槽怪" />
          <label>平台类型</label>
          <select v-model="form.platform_id" :disabled="!isNew">
            <option value="qq">QQ</option>
            <option value="bilibili">B站</option>
            <option value="desktop_pet" disabled>桌宠 (V2)</option>
          </select>
        </div>
        <div style="flex:1">
          <!-- QQ 配置 -->
          <template v-if="form.platform_id === 'qq'">
            <label>Bot QQ号</label>
            <input v-model="config.bot_qq" placeholder="123456" />
            <label>WS 端口</label>
            <input v-model.number="config.ws_port" type="number" placeholder="3001" />
            <div style="font-size:12px;color:#666;margin-top:4px">
              NapCat 配置: ws://127.0.0.1:{{ config.ws_port }}/onebot/v11/ws
            </div>
          </template>
          <!-- B站 配置 -->
          <template v-if="form.platform_id === 'bilibili'">
            <label>SESSDATA <small style="color:#999">(F12→Application→Cookies→bilibili.com)</small></label>
            <input v-model="config.sessdata" placeholder="从浏览器Cookie复制" />
            <label>bili_jct</label>
            <input v-model="config.bili_jct" placeholder="CSRF Token" />
            <label>buvid3</label>
            <input v-model="config.buvid3" placeholder="设备ID" />
            <label>Bot 名称</label>
            <input v-model="config.bot_name" placeholder="如: 伊蕾娜" />
            <label>直播间ID (逗号分隔)</label>
            <input v-model="config.live_room_ids_str" placeholder="22544798" />
            <label>监控视频ID (BV号，逗号分隔)</label>
            <input v-model="config.monitor_video_ids_str" placeholder="BV1xx411c7mD" />
            <label>授权回复UID (逗号分隔，这些用户@Bot才会回复)</label>
            <input v-model="config.authorized_uids_str" placeholder="2512428321, 431490003" />
            <div style="display:flex;gap:12px;margin-top:8px">
              <label style="margin:0"><input type="checkbox" v-model="config.live_enabled" style="width:auto;margin-right:4px" />直播弹幕</label>
              <label style="margin:0"><input type="checkbox" v-model="config.comment_enabled" style="width:auto;margin-right:4px" />评论区</label>
              <label style="margin:0"><input type="checkbox" v-model="config.session_enabled" style="width:auto;margin-right:4px" />私信</label>
            </div>
          </template>
          <!-- 桌宠 配置 -->
          <template v-if="form.platform_id === 'desktop_pet'">
            <label>窗口标题</label>
            <input v-model="config.window_title" placeholder="小助手" />
          </template>
        </div>
      </div>
      <div style="margin-top:12px">
        <label>绑定人设</label>
        <select v-model="form.persona_id">
          <option :value="null">使用系统默认</option>
          <option v-for="p in personas" :key="p.id" :value="p.id">{{ p.name }}{{ p.is_active ? ' (活跃)' : '' }}</option>
        </select>
        <label>对话模型</label>
        <select v-model="form.chat_provider_id">
          <option :value="null">使用系统默认</option>
          <option v-for="p in chatProviders" :key="p.id" :value="p.id">{{ p.name }} ({{ p.model }})</option>
        </select>
      </div>
      <div style="margin-top:12px">
        <label style="font-weight:bold">上下文设置</label>
        <div style="display:flex;gap:12px">
          <div style="flex:1">
            <label>最大轮数 (5-50)</label>
            <input v-model.number="config.context_max_turns" type="number" min="5" max="50" placeholder="20" />
          </div>
          <div style="flex:1">
            <label>有效期 (5-120分钟)</label>
            <input v-model.number="config.context_ttl_minutes" type="number" min="5" max="120" placeholder="30" />
          </div>
        </div>
      </div>
      <div style="margin-top:16px;display:flex;gap:8px">
        <button class="btn btn-primary" @click="save">保存</button>
        <router-link to="/accounts" class="btn btn-outline">取消</router-link>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const isNew = route.path === '/accounts/new'

const personas = ref<any[]>([])
const chatProviders = ref<any[]>([])

const form = reactive({
  name: '', platform_id: 'qq', persona_id: null as string|null,
  chat_provider_id: null as string|null
})
const config = reactive<any>({ bot_qq: '', ws_port: 3001, protocol: 'onebot_v11', context_max_turns: 20, context_ttl_minutes: 30 })

// Reset config when platform changes
function resetConfigForPlatform(pid: string) {
  const base = { context_max_turns: 20, context_ttl_minutes: 30 }
  if (pid === 'qq') Object.assign(config, { bot_qq: '', ws_port: 3001, protocol: 'onebot_v11', ...base })
  else if (pid === 'bilibili') Object.assign(config, { sessdata: '', bili_jct: '', buvid3: '', bot_name: '', live_room_ids_str: '', live_enabled: false, comment_enabled: false, session_enabled: false, ...base })
  else Object.assign(config, { ...base })
}

onMounted(async () => {
  if (isNew) resetConfigForPlatform('qq')
  const [pRes, provRes] = await Promise.all([
    api.get('/personas') as any,
    api.get('/providers') as any,
  ])
  personas.value = pRes.data
  chatProviders.value = (provRes.data || []).filter((p:any) => p.category === 'chat')

  if (!isNew) {
    const res = await api.get(`/accounts/${route.params.id}`) as any
    if (res.ok) {
      Object.assign(form, { name: res.data.name, platform_id: res.data.platform_id, persona_id: res.data.persona_id, chat_provider_id: res.data.chat_provider_id })
      Object.assign(config, res.data.config_json)
      // Convert live_room_ids array to comma-separated string for display
      if (res.data.config_json.live_room_ids) {
        config.live_room_ids_str = res.data.config_json.live_room_ids.join(', ')
      }
      if (res.data.config_json.monitor_video_ids) {
        config.monitor_video_ids_str = res.data.config_json.monitor_video_ids.join(', ')
      }
      if (res.data.config_json.authorized_uids) {
        config.authorized_uids_str = res.data.config_json.authorized_uids.join(', ')
      }
    }
  }
})

async function save() {
  const cfg = { ...config }
  // Convert live_room_ids_str to array
  if (form.platform_id === 'bilibili') {
    if (cfg.live_room_ids_str) cfg.live_room_ids = cfg.live_room_ids_str.split(',').map((s: string) => s.trim()).filter(Boolean)
    if (cfg.monitor_video_ids_str) cfg.monitor_video_ids = cfg.monitor_video_ids_str.split(',').map((s: string) => s.trim()).filter(Boolean)
    if (cfg.authorized_uids_str) cfg.authorized_uids = cfg.authorized_uids_str.split(',').map((s: string) => s.trim()).filter(Boolean)
  }
  delete cfg.live_room_ids_str
  delete cfg.monitor_video_ids_str
  delete cfg.authorized_uids_str
  const body = { ...form, config_json: cfg }
  if (isNew) {
    await api.post('/accounts', body)
  } else {
    await api.put(`/accounts/${route.params.id}`, body)
  }
  router.push('/accounts')
}
</script>
