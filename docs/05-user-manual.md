# AnotherBot — 用户手册

> 版本: 3.0 | 日期: 2026-05-16
> v3 更新: B站平台接入(私信+评论区@回复+直播弹幕)、平台级Prompt配置、轮询策略

---

## 目录

1. [准备工作](#1-准备工作)
2. [安装 AnotherBot](#2-安装-anotherbot)
3. [部署 NapCat 并登录 QQ](#3-部署-napcat-并登录-qq)
4. [连接 NapCat 和 AnotherBot](#4-连接-napcat-和-anotherbot)
5. [配置 Web 管理台](#5-配置-web-管理台)
6. [配置 AI 模型](#6-配置-ai-模型)
7. [创建第一个人设](#7-创建第一个人设)
8. [验证一切正常](#8-验证一切正常)
9. [多账户配置](#9-多账户配置)
10. [常见问题](#10-常见问题)

---

## 1. 准备工作

开始之前准备好这些东西：

| 准备项 | 说明 |
|--------|------|
| 一台电脑 | Windows/Mac/Linux 均可，个人 PC 常驻运行 |
| Python 3.12+ | [python.org](https://www.python.org/downloads/) 下载安装 |
| Node.js 20+ | 前端开发需要，[nodejs.org](https://nodejs.org/) 下载 |
| 一个 QQ 号 | **关键：不建议用主号！** 用养了几个月、有正常聊天记录的小号 |
| 一部手机 | NapCat 登录 QQ 需要扫码 |
| LLM API Key | 千问/DeepSeek/Claude 等任意 OpenAI 兼容的 API |

### QQ 号风控提醒

- **不要用新注册的 QQ 号**——风控概率极高，可能几分钟就封
- **不要用主号**——万一封号，好友、群聊全丢
- 建议用养了 3 个月以上、加了几个群、有正常聊天记录的小号
- 扫码登录后不要立刻大量发消息，让 Bot "静置"一段时间

---

## 2. 安装 AnotherBot

### 2.1 获取代码

```bash
git clone https://github.com/your-repo/anotherbot.git
cd anotherbot
```

### 2.2 安装 Python 依赖

```bash
# 创建虚拟环境 (推荐)
python -m venv venv

# Windows:
venv\Scripts\activate

# Mac/Linux:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 2.3 安装前端依赖

```bash
cd web
npm install
cd ..
```

### 2.4 生成加密密钥

```bash
python main.py --generate-key
```

这会在终端输出一个密钥，把它设为环境变量：

```
# Windows (PowerShell):
$env:ANOTHERBOT_SECRET_KEY = "你的密钥"

# Windows (CMD):
set ANOTHERBOT_SECRET_KEY=你的密钥

# Mac/Linux:
export ANOTHERBOT_SECRET_KEY="你的密钥"
```

这个密钥用来加密存储 API Key，不设置的话开发阶段会用明文（不推荐）。

---

## 3. 部署 NapCat 并登录 QQ

### 3.1 什么是 NapCat

NapCat 是一个"无头 QQ 客户端"——它在后台运行，没有界面，但能收发 QQ 消息。它把 QQ 消息转成标准的 OneBot v11 格式，通过 WebSocket 提供给 AnotherBot。

**关系图**：

```
你的电脑
┌─────────────────────────────────────────────┐
│                                             │
│  NapCat                  AnotherBot         │
│  ┌────────────┐         ┌────────────────┐  │
│  │ 登录 QQ 号   │ WS反连  │ QQAdapter      │  │
│  │ 收发消息     │────────→│ :3001          │  │
│  │ 转OneBot格式 │         │ 处理消息调LLM   │  │
│  └────────────┘         └────────────────┘  │
│                                             │
│  需要扫码登录            不需要登录QQ         │
└─────────────────────────────────────────────┘
```

### 3.2 安装 NapCat

**方式一：Windows 一键包（推荐）**

从 [NapCat releases](https://github.com/NapNeko/NapCat/releases) 下载 `NapCat-win32-x64.zip`，解压到任意目录，双击 `napcat.bat` 启动。

**方式二：Docker**

```bash
docker run -d \
  -e NAPCAT_GID=$(id -g) \
  -e NAPCAT_UID=$(id -u) \
  -p 6099:6099 \
  --name napcat \
  --restart=always \
  mlikiowa/napcat-docker:latest
```

### 3.3 登录 QQ

1. 启动 NapCat 后，查看控制台日志，找到 WebUI 地址（默认 `http://127.0.0.1:6099`）和登录 Token
2. 浏览器打开 WebUI，输入 Token
3. 进入「网络配置」页面
4. 点击「登录账号」，会弹出二维码
5. 用手机 QQ 扫码 → 确认登录

**注意**：扫码的是你要当 Bot 的那个 QQ 号。手机上登录后不要退出，NapCat 需要保持在线。

---

## 4. 连接 NapCat 和 AnotherBot

### 4.1 在 NapCat WebUI 配置 WebSocket

进入 NapCat WebUI → 网络配置 → 添加 WebSocket 客户端：

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 名称 | AnotherBot-大号 | 随意起 |
| 类型 | WebSocket 客户端 | NapCat 主动连 AnotherBot |
| URL | `ws://127.0.0.1:3001/onebot/v11/ws` | 注意: 每账户端口不同 |
| 消息格式 | Array | OneBot v11 标准 |
| 心跳间隔 | 5000 | 5秒 |
| 重连间隔 | 5000 | 断线5秒后重试 |

保存后，NapCat 会立刻尝试连接。

### 4.2 在 AnotherBot WebUI 启用账户

1. 先启动 AnotherBot（见下一步）
2. 进入 Web 管理台 → 账户管理
3. 找到你的 QQ 账户 → 点击「启用」
4. 状态指示灯变绿 → 连接成功

### 4.3 连接原理

```
AnotherBot 先启动:
  → QQAdapter 在 :3001 开启 WebSocket Server
  → 等待客户端连接

NapCat 后启动:
  → 扫码登录 QQ
  → 作为 WS Client 连接 ws://127.0.0.1:3001
  → 连接成功 → QQ 消息开始转发
```

**关键**：AnotherBot 必须先启动（开 WS Server），NapCat 才能连上。如果 NapCat 先启动了也没关系，它会自动重连。

---

## 5. 配置 Web 管理台

### 5.1 启动 AnotherBot

```bash
# 后端 (终端1)
cd anotherbot
python main.py
# 输出: Uvicorn running on http://127.0.0.1:8080

# 前端 (终端2, 开发模式)
cd anotherbot/web
npm run dev
# 输出: Vite dev server running on http://localhost:5173
```

### 5.2 打开管理台

浏览器访问 `http://localhost:5173`

首次启动时数据库会自动创建，预置了 QQ 平台类型。你会看到空的 Dashboard。

### 5.3 管理台概览

```
侧边导航:
  🏠 首页      — Bot 状态监控、实时消息流
  👤 人设管理   — 创建/编辑角色卡
  💬 对话测试   — 沙盒测试对话效果
  🔗 账户管理   — 管理各平台 Bot 账户
  😂 表情包库   — 上传/管理表情包
  ⚙️ 系统设置   — 模型 API 配置
  📋 日志      — 查看运行日志
```

---

## 6. 配置 AI 模型

### 6.1 添加模型配置

进入系统设置 → 模型配置 → 添加对话模型：

| 配置项 | 示例值 | 说明 |
|--------|--------|------|
| 名称 | 日常对话 | 自定义，方便识别 |
| 类别 | 对话 (chat) | 对话用这个，识图用 vision |
| 提供商 | OpenAI 兼容 | 千问/DeepSeek 等都是这个 |
| 模型名 | `qwen-turbo` | API 文档里查准确的模型 ID |
| API Key | `sk-xxxx...` | 从模型提供商获取 |
| Base URL | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 对应提供商的地址 |
| 温度 | 0.8 | 0-2，越高越随机 |
| 最大 Token | 512 | 单次回复最大长度 |

### 6.2 国内常用模型 API

| 提供商 | Base URL | 模型名示例 |
|--------|----------|-----------|
| 阿里千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| SiliconCloud | `https://api.siliconflow.cn/v1` | `Qwen/Qwen3-32B` |
| 月之暗面 | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| Claude API | `https://api.anthropic.com/v1` | `claude-sonnet-4-6` |

### 6.3 测试连接

添加模型后点击「测试连接」，成功会显示延迟毫秒数。失败检查 API Key 和 Base URL。

### 6.4 设为默认

点击「设为默认」——所有未单独指定模型的账户都会使用这个。

---

## 7. 创建第一个人设

### 7.1 新建人设

进入人设管理 → 创建人设：

```
名称: 小助手
描述: 一个活泼的AI助手，喜欢聊天，乐于助人
性格: 外向、热情、偶尔毒舌，喜欢用网络流行语
场景: 和用户在群里聊天
```

### 7.2 添加对话示例 (重要)

对话示例是让模型理解人设风格的**最关键字段**：

```
用户: 你好呀
小助手: 嗨~ 来啦！今天有什么新鲜事？

用户: 推荐个游戏呗
小助手: 那得看你喜欢什么类型啊！FPS？RPG？还是那种一玩玩一天的策略游戏？

用户: 好无聊啊
小助手: 无聊？那是你没找到好玩的事！要不我给你讲个冷笑话？
```

示例对话约 3-5 对就够了，太多会占用 System Prompt 空间。

### 7.3 设为活跃

保存后在列表页点击「设为活跃」——当前没有单独绑定人设的账户都会使用这个。

### 7.4 导入酒馆角色卡 (可选)

如果你在 SillyTavern/酒馆 社区有收藏的角色卡 PNG：

1. 进入人设管理 → 导入
2. 上传角色卡 PNG 文件
3. 系统自动解析嵌入的 JSON → 填充表单
4. 你可以修改后再保存

---

## 8. 验证一切正常

### 8.1 对话测试

进入对话测试页 → 选择你的人设和模型 → 发送消息：

```
你: 你好呀
Bot: 嗨~ 来啦！我是小助手，需要我帮忙吗？
```

这里可以快速验证人设和模型效果，不会发到 QQ。

### 8.2 QQ 实际测试

用**另一个 QQ 号**（不是 Bot 那个号），在群里 @Bot 或私聊：

```
@Bot /help

Bot 回复:
📋 可用指令:
/reset  - 清空当前对话上下文
/new    - 结束当前对话
/status - 查看上下文状态
/help   - 显示此帮助
```

有回复 → 链路全通。

### 8.3 检查 Dashboard

首页 Dashboard 应该能看到：
- 平台状态：「● 大号 已连接」
- 今日概览：消息计数
- 实时消息流：刚发的测试消息

---

## 9. 多账户配置

如果你想跑多个 QQ 号（比如大号在摸鱼群，小号在技术群）：

### 9.1 添加第二个账户

1. 账户管理 → 添加账户
2. 填写：
   - 名称：小号-导师
   - 平台：QQ
   - Bot QQ号：789012（另一个号）
   - WS 端口：3002（自动建议）
3. 保存

### 9.2 配置第二个 NapCat

在 NapCat 目录复制一份配置，修改 WS 连接地址为 `ws://127.0.0.1:3002/onebot/v11/ws`，启动第二个 NapCat 实例，用另一个 QQ 号扫码登录。

### 9.3 绑定不同人设 (可选)

编辑账户 → 人设与模型 → 绑定人设选「毒舌吐槽怪」——这个账户的 Bot 就会有不同性格。

### 9.4 独立开关

每个账户可以独立启用/禁用。比如小号暂时不用，点「禁用」就行，不影响大号。

---

## 10. 常见问题

### Q1: NapCat 连不上 AnotherBot

```
检查:
  1. AnotherBot 是否已启动？(先启后端，再连 NapCat)
  2. 端口是否一致？NapCat 的 URL 端口 = 账户配置的 WS 端口
  3. 端口是否被占用？换一个端口试试 (3003, 3004...)
  4. 防火墙/杀毒软件是否拦截？添加允许规则
```

### Q2: Bot 收到消息但不回复

```
检查:
  1. 群聊是否 @了 Bot？(V1 需要 @ 才回复)
  2. 是否配置了 AI 模型并设为默认？
  3. 查看日志页，看是否有 API 调用错误
  4. 人设是否已创建并设为活跃？
```

### Q3: QQ 号被封了怎么办

```
预防:
  - 用养过的小号，不用新号
  - 扫码后不要立刻大量发消息
  - 控制消息频率，不要短时间内发太多

补救:
  - QQ 安全中心申诉
  - 换一个号，重新走配置流程
  - 账号配置已经在 AnotherBot 里，只需要改 NapCat 侧的 QQ 号
```

### Q4: 如何切换模型？

系统设置 → 模型配置 → 编辑现有或新增 → 设为默认。切换即时生效，不需要重启。

如果只想某个账户切换：编辑账户 → 人设与模型 → 对话模型选指定的。

### Q5: 上下文太长/太短？

编辑账户 → 上下文设置：
- 最大轮数：调小让 Bot "忘得更快"
- 有效期：调小让旧消息更快失效

可以在对话测试页先调试参数，确定了再应用到线上账户。

### Q6: 如何备份数据？

```bash
# 整个 data 目录就是全部数据
# 备份:
cp -r anotherbot/data anotherbot/data_backup_20260513

# 恢复:
cp -r anotherbot/data_backup_20260513/* anotherbot/data/
```

SQLite 单文件 `anotherbot.db` + 表情包文件夹 `stickers/`，全部备份。

### Q7: 怎么更新 AnotherBot？

```bash
git pull
pip install -r requirements.txt --upgrade
cd web && npm install && npm run build && cd ..
# 重启 AnotherBot
```

### Q8: 如何看到 Bot 当前在聊什么？

Dashboard 首页 → 实时消息流，能看到所有已启用账户的收发消息。也可以在日志页按 level 过滤。
