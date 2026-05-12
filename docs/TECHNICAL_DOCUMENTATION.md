# Customer-Agent 技术文档

## 目录
1. [系统概述](#系统概述)
2. [技术架构](#技术架构)
3. [核心模块详解](#核心模块详解)
4. [数据流分析](#数据流分析)
5. [关键技术实现](#关键技术实现)
6. [配置与部署](#配置与部署)

---

## 系统概述

### 项目定位
Customer-Agent 是一个**电商智能客服桌面应用**，集成 AI 大模型实现自动回复，支持拼多多等电商平台。

### 核心能力
- ✅ 实时消息监听（WebSocket）
- ✅ AI 智能回复（LLM + Function Calling）
- ✅ 商品主动推荐（Agent 工具调用）
- ✅ 双知识库检索（商品 + 客服）
- ✅ 关键词转人工
- ✅ 多账号管理
- ✅ 自动重连机制

### 技术栈

| 层级 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **UI框架** | PyQt6 | 6.9.0 | 桌面GUI |
| **UI组件** | pyqt6-fluent-widgets | 1.9.0 | 现代化UI组件 |
| **浏览器自动化** | Playwright | 1.52.0 | 登录态保持 |
| **实时通信** | websockets | 14.2 | 消息监听 |
| **HTTP请求** | requests | 2.32.5 | API调用 |
| **AI框架** | OpenAI SDK | 1.109.1 | LLM调用 |
| **数据库** | SQLAlchemy | 2.0.43 | ORM框架 |
| **数据库** | SQLite | - | 本地存储 |
| **中文分词** | jieba | 0.42.1 | 知识检索 |
| **Token统计** | tiktoken | 0.12.0 | 上下文管理 |
| **日志** | loguru | 0.7.0 | 结构化日志 |
| **配置** | Pydantic | 2.11.4 | 配置验证 |
| **异步** | asyncio | - | 并发处理 |

---

## 技术架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Customer-Agent                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        UI Layer (PyQt6)                          │    │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐            │    │
│  │  │主窗口     │ │自动回复UI│ │知识库UI  │ │设置UI    │            │    │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘            │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                    │                                      │
│                                    ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                     Business Logic Layer                         │    │
│  │                                                                   │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │    │
│  │  │   Agent      │  │   Message    │  │   Channel    │            │    │
│  │  │   (AI回复)   │  │   (消息队列)  │  │   (渠道集成)  │            │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘            │    │
│  │         │                  │                  │                   │    │
│  │         ▼                  ▼                  ▼                   │    │
│  │  ┌──────────────────────────────────────────────────────────┐    │    │
│  │  │              Core Services (DI Container)                │    │    │
│  │  │  • DatabaseManager  • KnowledgeService  • CacheManager   │    │    │
│  │  └──────────────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                    │                                      │
│                                    ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                        Data Layer                                │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │    │
│  │  │   SQLite     │  │  知识库文件   │  │  配置文件     │            │    │
│  │  │   数据库     │  │  (PDF/Word)  │  │  config.json  │            │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘            │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                           │
└─────────────────────────────────────────────────────────────────────────┘
```

### 模块依赖关系

```
app.py (入口)
    │
    ├── config.py (配置管理)
    │
    ├── core/ (核心服务)
    │   ├── di_container.py (依赖注入容器)
    │   ├── service_providers.py (服务提供者)
    │   └── connection_status.py (连接状态管理)
    │
    ├── ui/ (用户界面)
    │   ├── main_ui.py (主窗口)
    │   ├── auto_reply_ui.py (自动回复)
    │   ├── Knowledge_ui.py (知识库)
    │   └── setting_ui.py (设置)
    │
    ├── Agent/ (AI Agent)
    │   └── CustomerAgent/
    │       ├── custom/ (核心实现)
    │       │   ├── customer_agent.py (Agent主类)
    │       │   ├── llm_client.py (LLM客户端)
    │       │   ├── session_manager.py (会话管理)
    │       │   └── tool_executor.py (工具执行)
    │       └── tools/ (工具集)
    │           ├── get_product_knowledge.py
    │           ├── get_product_list.py
    │           └── send_goods_link.py
    │
    ├── Channel/ (渠道集成)
    │   └── pinduoduo/
    │       ├── core/ (核心模块)
    │       │   ├── pdd_lifecycle.py (生命周期)
    │       │   ├── pdd_connection.py (连接管理)
    │       │   └── pdd_message_handler.py (消息处理)
    │       └── utils/ (工具)
    │           ├── base_request.py (请求基类)
    │           └── API/ (API封装)
    │
    ├── Message/ (消息处理)
    │   ├── core/queue.py (消息队列)
    │   └── handlers/ (处理器链)
    │       └── ai_handler.py (AI处理)
    │
    └── database/ (数据层)
        ├── db_manager.py (数据库管理)
        ├── knowledge_service.py (知识服务)
        └── product_sync.py (商品同步)
```

---

## 核心模块详解

### 1. 依赖注入容器 (DI Container)

**文件**: `core/di_container.py`

**设计模式**: 依赖注入 + 单例模式

**核心代码**:
```python
class ServiceLifetime(Enum):
    SINGLETON = "singleton"     # 单例：全局唯一实例
    TRANSIENT = "transient"     # 瞬态：每次创建新实例
    SCOPED = "scoped"           # 作用域：作用域内单例

class DIContainer:
    def register_singleton(self, service_type: Type, instance: Any = None,
                         factory: Callable = None, implementation_type: Type = None):
        """注册单例服务"""
        
    def get(self, service_type: Type) -> Any:
        """获取服务实例"""
        # 双重检查锁定，确保线程安全
        if descriptor.lifetime == ServiceLifetime.SINGLETON:
            if key in self._singletons:
                return self._singletons[key]
            with self._lock:
                if key in self._singletons:
                    return self._singletons[key]
                instance = self._create_instance(...)
                self._singletons[key] = instance
                return instance
```

**使用示例**:
```python
# 注册服务
container.register_singleton(DatabaseManager, factory=lambda: DatabaseManager(db_path))
container.register_singleton(KnowledgeService, factory=lambda: KnowledgeService())

# 获取服务
db_manager = container.get(DatabaseManager)
knowledge_service = container.get(KnowledgeService)
```

**解决的问题**:
1. 避免全局变量的滥用
2. 统一管理服务生命周期
3. 方便测试时 Mock 替换
4. 解耦模块间依赖

---

### 2. Agent 核心实现

**文件**: `Agent/CustomerAgent/custom/customer_agent.py`

**设计模式**: ReAct Agent + Function Calling

**核心流程**:

```
┌─────────────────────────────────────────────────────────┐
│                    Agent 循环流程                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. 加载历史消息                                         │
│     └── SessionManager.get_history(session_id)          │
│                                                         │
│  2. 检查上下文压缩                                       │
│     └── if should_compress() → LLM压缩历史              │
│                                                         │
│  3. 构建 messages 列表                                   │
│     └── MessageBuilder.build_messages(query, history)   │
│                                                         │
│  4. 调用 LLM                                            │
│     └── LLMClient.chat(messages, tool_choice="auto")    │
│                                                         │
│  5. 解析 tool_calls                                     │
│     └── if has_tool_calls → 执行工具                    │
│     └── else → 返回最终回复                             │
│                                                         │
│  6. 并行执行工具                                         │
│     └── ToolExecutor.execute_parallel(tool_calls)       │
│                                                         │
│  7. 回传工具结果                                         │
│     └── messages.append(tool_results)                   │
│                                                         │
│  8. 循环直到无工具调用                                   │
│     └── goto step 4                                     │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**核心代码**:
```python
async def _run_agent_loop(self, messages: List[Dict], dependencies: Dict) -> str:
    """Agent 循环核心"""
    loop_count = 0
    
    while loop_count < self._config.max_loops:
        # 1. 调用 LLM
        response = await self._llm_client.chat(messages, tool_choice="auto")
        
        # 2. 无工具调用，返回内容
        if not response.has_tool_calls:
            return response.content or ""
        
        # 3. 保存 assistant 消息
        messages.append({
            "role": "assistant",
            "content": response.content,
            "tool_calls": [...]
        })
        
        # 4. 并行执行工具
        tool_results = await self._tool_executor.execute_parallel(
            response.tool_calls, dependencies
        )
        
        # 5. 回传结果
        for result in tool_results:
            messages.append(result.to_dict())
        
        loop_count += 1
    
    return messages[-1].get("content", "")
```

---

### 3. WebSocket 生命周期管理

**文件**: `Channel/pinduoduo/core/pdd_lifecycle.py`

**设计模式**: Mixin + 异步事件循环

**核心流程**:

```
┌─────────────────────────────────────────────────────────┐
│                  WebSocket 生命周期                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  start_account()                                        │
│      │                                                  │
│      ├── 获取账号信息                                    │
│      ├── 更新状态为 CONNECTING                          │
│      └── 创建连接任务                                    │
│          │                                              │
│          ▼                                              │
│  init()                                                 │
│      │                                                  │
│      ├── 获取 Token                                     │
│      │   └── GetToken(shop_id, user_id).get_token()     │
│      │                                                  │
│      ├── 建立 WebSocket 连接                            │
│      │   └── websockets.connect("wss://m-ws.pinduoduo.com/") │
│      │                                                  │
│      ├── 更新状态为 CONNECTED                           │
│      │                                                  │
│      ├── 启动心跳任务                                    │
│      │   └── _heartbeat_loop()                          │
│      │                                                  │
│      └── 启动消息循环                                    │
│          └── _message_loop()                            │
│              │                                          │
│              ├── async for message in websocket:        │
│              │   └── 并发处理消息                         │
│              │                                          │
│              └── 连接关闭时退出                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**关键代码**:
```python
async def init(self, shop_id: str, user_id: str, username: str, ...):
    # 1. 获取 Token
    token = GetToken(shop_id, user_id)
    access_token = token.get_token()
    
    # 2. 建立连接
    async with websockets.connect(
        f"{self.base_url}?access_token={access_token}&...",
        ping_interval=60,
        ping_timeout=30,
        max_size=10**7
    ) as websocket:
        self.ws = websocket
        
        # 3. 启动心跳
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(websocket, shop_id, user_id, username)
        )
        
        # 4. 启动消息循环
        message_task = asyncio.create_task(
            self._message_loop(websocket, shop_id, user_id, username, queue_name)
        )
        
        # 5. 等待任务完成
        await asyncio.wait([message_task, heartbeat_task], ...)
```

---

### 4. 消息队列与处理器链

**文件**: `Message/core/queue.py` + `Message/handlers/ai_handler.py`

**设计模式**: 生产者-消费者 + 责任链模式

**消息处理流程**:

```
WebSocket消息 → 消息队列 → 处理器链 → 发送回复
                    │
                    ├── KeywordHandler (关键词检测)
                    │   └── 检测到"投诉" → 标记转人工
                    │
                    ├── AIHandler (AI生成回复)
                    │   ├── 预处理消息
                    │   ├── 调用 CustomerAgent
                    │   └── 发送回复
                    │
                    └── SafetyHandler (风控检查)
                        ├── 检查回复频率
                        └── 检查敏感内容
```

**关键代码**:
```python
class AIReplyHandler(BaseHandler):
    async def handle(self, context: Context, metadata: Dict[str, Any]) -> bool:
        # 1. 预处理消息
        processed_content = self.preprocessor.process(context.content, context.type)
        
        # 2. 调用 AI
        reply = await self._get_ai_reply(processed_content, context)
        
        # 3. 发送回复
        success = await self._send_reply(context, reply, metadata)
        
        return success
    
    async def _get_ai_reply(self, query: str, context: Context) -> Optional[str]:
        if hasattr(self.bot, 'async_reply'):
            res = await self.bot.async_reply(query, context)
            return getattr(res, 'content', str(res))
        return None
```

---

### 5. API 请求基类

**文件**: `Channel/pinduoduo/utils/base_request.py`

**设计模式**: 模板方法 + 重试模式

**核心特性**:

```
┌─────────────────────────────────────────────────────────┐
│                    API 请求流程                          │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. 初始化请求                                           │
│     └── 加载 Cookies 和账号信息                          │
│                                                         │
│  2. 发送请求（带重试）                                    │
│     ├── 检查响应                                         │
│     ├── if 会话过期 (error_code=43001):                 │
│     │   ├── 自动重新登录                                 │
│     │   ├── 更新 Cookies                                │
│     │   └── 重试请求                                     │
│     └── else: 返回结果                                   │
│                                                         │
│  3. 重试机制（指数退避）                                  │
│     ├── delay = initial_delay * (backoff ^ attempt)     │
│     ├── delay += random_jitter                          │
│     └── max_retries = 3                                 │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**关键代码**:
```python
def _should_retry(self, response, exception) -> bool:
    """判断是否应该重试"""
    if response:
        # 会话过期，需要重新登录
        if response.json().get('error_code') == 43001:
            return True
    if exception:
        # 网络错误，应该重试
        if isinstance(exception, (requests.ConnectionError, requests.Timeout)):
            return True
    return False

def _relogin_and_update_cookies(self) -> bool:
    """重新登录并更新 Cookies"""
    # 1. 尝试刷新 Cookies
    refresh_result = await refresh_pdd_cookies(username, password)
    if refresh_result:
        self._apply_new_cookies(refresh_result['cookies'])
        return True
    
    # 2. 回退到完整登录
    login_result = await login_pdd(username, password)
    if login_result:
        self._apply_new_cookies(login_result['cookies'])
        return True
    
    return False
```

---

## 数据流分析

### 完整的消息处理流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         消息处理完整流程                                  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  1. 拼多多服务器 → WebSocket 推送消息                                    │
│     │                                                                   │
│     ▼                                                                   │
│  2. PDDChannel._message_loop() 接收消息                                 │
│     │                                                                   │
│     ├── 解析消息内容                                                    │
│     ├── 提取 from_uid, content, msg_type                                │
│     │                                                                   │
│     ▼                                                                   │
│  3. 消息入队                                                            │
│     │                                                                   │
│     └── MessageQueue.enqueue(message)                                   │
│         │                                                               │
│         ▼                                                               │
│  4. 消息消费者处理                                                      │
│     │                                                                   │
│     ├── MessagePreprocessor 预处理                                      │
│     │   ├── 去除特殊字符                                                │
│     │   └── 提取关键词                                                  │
│     │                                                                   │
│     ▼                                                                   │
│  5. KeywordHandler 关键词检测                                           │
│     │                                                                   │
│     ├── if 匹配"投诉/退款/举报":                                        │
│     │   └── 标记转人工，停止自动处理                                     │
│     │                                                                   │
│     ├── else: 继续处理                                                  │
│     │                                                                   │
│     ▼                                                                   │
│  6. AIReplyHandler AI 处理                                              │
│     │                                                                   │
│     ├── 构建 Context 对象                                               │
│     │   ├── session_id = "pdd_{user_id}"                                │
│     │   ├── shop_id, user_id, from_uid                                  │
│     │   └── 历史消息                                                    │
│     │                                                                   │
│     ├── 调用 CustomerAgent.async_reply()                                │
│     │   │                                                               │
│     │   ├── 加载历史消息                                                │
│     │   │   └── SessionManager.get_history(session_id)                  │
│     │   │                                                               │
│     │   ├── 检查上下文压缩                                              │
│     │   │   └── if token_count > threshold: compress()                  │
│     │   │                                                               │
│     │   ├── 构建 messages 列表                                          │
│     │   │   ├── system prompt (指令)                                    │
│     │   │   ├── 历史消息 (压缩后)                                        │
│     │   │   └── 当前用户消息                                            │
│     │   │                                                               │
│     │   ├── 调用 LLM                                                    │
│     │   │   └── LLMClient.chat(messages, tools, tool_choice="auto")     │
│     │   │                                                               │
│     │   ├── 解析 tool_calls                                             │
│     │   │   ├── if has_tool_calls:                                      │
│     │   │   │   ├── get_product_knowledge (查询商品知识)                │
│     │   │   │   ├── send_goods_link (发送商品卡片)                      │
│     │   │   │   └── transfer_conversation (转人工)                      │
│     │   │   │                                                           │
│     │   │   └── 执行工具 → 回传结果 → 继续调用 LLM                       │
│     │   │                                                               │
│     │   └── 返回最终回复                                                │
│     │                                                                   │
│     ├── 保存回复到历史                                                  │
│     │   └── SessionManager.add_message(session_id, "assistant", reply)  │
│     │                                                                   │
│     └── 返回 Reply 对象                                                 │
│         │                                                               │
│         ▼                                                               │
│  7. 发送回复                                                            │
│     │                                                                   │
│     ├── SendMessage.send_text(from_uid, reply)                          │
│     │   │                                                               │
│     │   ├── 构建请求体                                                  │
│     │   │   {                                                           │
│     │   │     "to_uid": from_uid,                                       │
│     │   │     "content": reply,                                         │
│     │   │     "msg_type": "text"                                        │
│     │   │   }                                                           │
│     │   │                                                               │
│     │   ├── 调用拼多多 API                                              │
│     │   │   └── POST https://mms.pinduoduo.com/plateau/chat/send_message │
│     │   │                                                               │
│     │   └── 检查响应                                                    │
│     │                                                                   │
│     └── 返回发送结果                                                    │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 关键技术实现

### 1. 浏览器自动化登录

**文件**: `Channel/pinduoduo/pdd_login.py`

**技术**: Playwright + Persistent Context

**关键原理**:
```python
async def login_pdd(name, password):
    # 使用持久化上下文，保存登录态
    browser = await playwright.chromium.launch_persistent_context(
        user_data_dir="./browser_data",  # 持久化目录
        headless=False  # 显示浏览器，方便扫码
    )
    
    page = browser.new_page()
    await page.goto("https://mms.pinduoduo.com/login")
    
    # 自动填写账号密码
    await page.fill("input[name='username']", name)
    await page.fill("input[type='password']", password)
    await page.click("button[type='submit']")
    
    # 等待登录成功
    await page.wait_for_url("**/home**")
    
    # 提取 Cookies
    cookies = await page.context.cookies()
    return {"cookies": cookies}
```

**优势**:
1. **登录态持久化**: 不需要每次登录
2. **绕过验证码**: 真实浏览器环境
3. **支持扫码**: 人工扫码登录

---

### 2. 会话管理

**文件**: `Agent/CustomerAgent/custom/session_manager.py`

**技术**: Token 计数 + LLM 摘要压缩

**核心原理**:
```python
class SessionManager:
    def __init__(self, token_window: int = 131072, compress_ratio: float = 0.8):
        self.token_window = token_window  # 模型上下文窗口大小
        self.threshold = int(token_window * compress_ratio)  # 压缩阈值
        self._token_estimator = TokenEstimator()  # Token 估算器
    
    def should_compress(self, session_id: str) -> bool:
        """判断是否需要压缩"""
        messages = self.get_history(session_id)
        token_count = self.estimate_tokens(messages)
        return token_count > self.threshold
    
    def compress_history(self, session_id: str, summary_func: Callable):
        """压缩历史消息"""
        old_messages = self.get_history(session_id)
        
        # 1. 调用 LLM 生成摘要
        summary = summary_func(old_messages)
        
        # 2. 保留最近 N 条消息
        retained = old_messages[-self.retain_count:]
        
        # 3. 组合：摘要 + 最近消息
        compressed = [
            {"role": "system", "content": f"[对话摘要] {summary}"},
            *retained
        ]
        
        # 4. 更新历史
        self._store[session_id] = compressed
```

**优势**:
1. **自动压缩**: 超过阈值自动压缩
2. **保留关键信息**: 摘要 + 最近消息
3. **节省 Token**: 大幅减少上下文长度

---

### 3. 工具调用机制

**文件**: `Agent/CustomerAgent/tools/`

**技术**: Function Calling + 装饰器模式

**工具定义示例**:
```python
# get_product_knowledge.py
@agent_tool(
    name="get_product_knowledge",
    description="获取指定商品的详细知识，包括成分、使用方法、规格等"
)
def get_product_knowledge(goods_id: str, shop_id: str) -> str:
    """查询商品知识库"""
    from database import knowledge_service
    
    result = knowledge_service.search_product_knowledge(
        goods_id=goods_id,
        shop_id=shop_id
    )
    
    return json.dumps(result, ensure_ascii=False)
```

**工具执行器**:
```python
class ToolExecutor:
    async def execute_parallel(self, tool_calls: List, dependencies: Dict) -> List[ToolResult]:
        """并行执行多个工具"""
        tasks = []
        for tc in tool_calls:
            # 在线程池中执行，避免阻塞
            task = asyncio.get_event_loop().run_in_executor(
                None,
                execute_tool,
                tc.function.name,
                tc.function.arguments,
                dependencies
            )
            tasks.append((tc.id, task))
        
        # 等待所有任务完成
        results = []
        for tool_call_id, task in tasks:
            content = await task
            results.append(ToolResult(tool_call_id, content))
        
        return results
```

---

### 4. 心跳保活机制

**文件**: `Channel/pinduoduo/core/pdd_lifecycle.py`

**核心代码**:
```python
async def _heartbeat_loop(self, websocket, shop_id, user_id, username):
    """心跳检查循环"""
    consecutive_failures = 0
    
    while not self._stop_event.is_set():
        try:
            # 发送 Ping
            start_time = time.time()
            await websocket.ping()
            response_time = time.time() - start_time
            
            # 成功，重置计数
            consecutive_failures = 0
            self.logger.debug(f"心跳成功: {response_time:.3f}s")
            
            # 等待下一次
            await asyncio.sleep(self.heartbeat_config.heartbeat_interval)
            
        except asyncio.TimeoutError:
            consecutive_failures += 1
            self.logger.warning(f"心跳超时: 连续失败 {consecutive_failures} 次")
            
            # 超过最大失败次数
            if consecutive_failures >= self.heartbeat_config.max_heartbeat_failures:
                self.status_manager.update_status(
                    shop_id, user_id, username,
                    ConnectionState.ERROR,
                    "心跳检查失败"
                )
                break
```

---

## 配置与部署

### 配置文件结构

**文件**: `config.json`

```json
{
    "business_hours": {
        "start": "08:00",
        "end": "23:00"
    },
    "llm": {
        "model_name": "ep-GLM-5",
        "api_key": "your-api-key",
        "api_base": "http://67.230.168.254:8080"
    },
    "prompt": {
        "instructions": [
            "1. 请用中文回复客户问题",
            "2. 优先使用工具查询商品知识",
            "3. 敏感问题转人工客服"
        ]
    },
    "db_path": "./temp/channel_shop.db"
}
```

### 部署命令

```bash
# 1. 克隆项目
git clone https://github.com/JC0v0/Customer-Agent.git
cd Customer-Agent

# 2. 安装依赖
pip install uv
uv sync

# 3. 安装浏览器
python scripts/install_playwright.py

# 4. 配置 API
cp config.json.template config.json
# 编辑 config.json，填入 API Key

# 5. 启动应用
python app.py
```

---

**文档版本**: 1.0.0
**更新时间**: 2026-05-01
**作者**: Claude Code Analysis
