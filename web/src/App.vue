<template>
  <div class="app">
    <aside class="sidebar">
      <div class="logo">AnotherBot</div>
      <nav>
        <router-link to="/">🏠 首页</router-link>
        <router-link to="/personas">👤 人设管理</router-link>
        <router-link to="/chat-test">💬 对话测试</router-link>
        <router-link to="/accounts">🔗 账户管理</router-link>
        <router-link to="/stickers">😀 表情包库</router-link>
        <router-link to="/settings">⚙️ 系统设置</router-link>
        <router-link to="/logs">📋 日志</router-link>
      </nav>
    </aside>
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #f5f5f5; color: #333; }
.app { display: flex; min-height: 100vh; }
.sidebar { width: 200px; background: #1a1a2e; color: #eee; padding: 20px 0; flex-shrink: 0; }
.sidebar .logo { font-size: 20px; font-weight: bold; padding: 0 20px 20px; border-bottom: 1px solid #333; margin-bottom: 10px; }
.sidebar nav { display: flex; flex-direction: column; }
.sidebar a { color: #aaa; text-decoration: none; padding: 10px 20px; font-size: 14px; }
.sidebar a:hover, .sidebar a.router-link-active { color: #fff; background: #16213e; }
.content { flex: 1; padding: 24px; overflow-y: auto; }
.card { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.btn { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
.btn-primary { background: #4361ee; color: #fff; }
.btn-danger { background: #e63946; color: #fff; }
.btn-sm { padding: 4px 10px; font-size: 12px; }
.btn-outline { background: transparent; border: 1px solid #ccc; }
input, textarea, select { padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; width: 100%; margin-bottom: 8px; }
label { display: block; font-size: 13px; color: #666; margin-bottom: 4px; }
h2 { font-size: 20px; margin-bottom: 16px; }
h3 { font-size: 16px; margin-bottom: 12px; }
.status-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
.status-connected { background: #2ecc71; }
.status-connecting { background: #f39c12; }
.status-running { background: #3498db; }
.status-stopped { background: #bdc3c7; }
.status-error { background: #e74c3c; }
.form-row { display: flex; gap: 12px; }
.form-row > * { flex: 1; }
</style>
