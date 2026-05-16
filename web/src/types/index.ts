export interface Persona {
  id: string
  name: string
  description: string
  personality: string
  scenario: string
  first_message: string
  example_dialogue: string
  custom_prompt: string
  post_instructions: string
  avatar_path: string
  is_active: boolean
  author: string
}

export interface Provider {
  id: string
  name: string
  category: 'chat' | 'vision' | 'search'
  provider_type: string
  model: string
  base_url: string
  temperature: number
  max_tokens: number
  is_default: boolean
}

export interface Account {
  id: string
  platform_id: string
  name: string
  enabled: boolean
  config_json: Record<string, any>
  persona_id: string | null
  chat_provider_id: string | null
  vision_provider_id: string | null
  favorite_sticker_codes: string[]
  status?: 'connected' | 'connecting' | 'stopped' | 'error'
  active_sessions?: { key: string; rounds: number }[]
}

export interface Sticker {
  id: string
  code: string
  filename: string
  description: string
  file_size: number
  mime_type: string
  uploaded_at: string
}

export interface SystemStatus {
  uptime: string
  today: {
    messages_received: number
    messages_sent: number
    tokens_used: number
    active_sessions: number
  }
  accounts: { id: string; name: string; platform: string; status: string }[]
}
