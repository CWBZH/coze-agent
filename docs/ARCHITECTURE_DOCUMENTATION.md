# Customer-Agent 架构文档

## 目录
1. [架构概览](#架构概览)
2. [分层架构](#分层架构)
3. [核心组件](#核心组件)
4. [数据模型](#数据模型)
5. [接口规范](#接口规范)
6. [部署架构](#部署架构)

---

## 架构概览

### 架构风格
Customer-Agent 采用**分层架构 + 微内核架构**，通过依赖注入容器管理服务生命周期。

### 设计原则
1. **单一职责**: 每个模块只负责一个功能
2. **依赖倒置**: 高层模块不依赖低层模块，都依赖抽象
3. **开闭原则**: 对扩展开放，对修改关闭
4. **接口隔离**: 使用小接口，避免大接口

### 架构全景图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Customer-Agent                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                      Presentation Layer                              │   │
│   │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │   │
│   │  │   MainUI    │  │ AutoReplyUI │  │ KnowledgeUI │  │  SettingUI  │ │   │
│   │  │  (主窗口)   │  │  (自动回复)  │  │  (知识库)    │  │   (设置)    │ │   │
│   │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                        │
│                                      ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                       Business Layer                                 │   │
│   │                                                                       │   │
│   │  ┌───────────────────┐  ┌───────────────────┐  ┌─────────────────┐ │   │
│   │  │   Agent Module    │  │  Message Module   │  │ Channel Module  │ │   │
│   │  │                   │  │                   │  │                 │ │   │
│   │  │ ┌───────────────┐ │  │ ┌───────────────┐ │  │ ┌─────────────┐ │ │   │
│   │  │ │CustomerAgent  │ │  │ │ MessageQueue  │ │  │ │ PDDChannel  │ │ │   │
│   │  │ └───────────────┘ │  │ └───────────────┘ │  │ └─────────────┘ │ │   │
│   │  │ ┌───────────────┐ │  │ ┌───────────────┐ │  │ ┌─────────────┐ │ │   │
│   │  │ │  LLMClient    │ │  │ │   Handlers    │ │  │ │ WebSocket   │ │ │   │
│   │  │ └───────────────┘ │  │ └───────────────┘ │  │ └─────────────┘ │ │   │
│   │  │ ┌───────────────┐ │  │ ┌───────────────┐ │  │ ┌─────────────┐ │ │   │
│   │  │ │SessionManager │ │  │ │   Consumers   │ │  │ │  API Utils  │ │ │   │
│   │  │ └───────────────┘ │  │ └───────────────┘ │  │ └─────────────┘ │ │   │
│   │  │ ┌───────────────┐ │  │                   │  │                 │ │   │
│   │  │ │ ToolExecutor  │ │  │                   │  │                 │ │   │
│   │  │ └───────────────┘ │  │                   │  │                 │ │   │
│   │  └───────────────────┘  └───────────────────┘  └─────────────────┘ │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                        │
│                                      ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                       Service Layer                                  │   │
│   │                                                                       │   │
│   │  ┌─────────────────────────────────────────────────────────────────┐│   │
│   │  │                    DI Container                                  ││   │
│   │  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐              ││   │
│   │  │  │DatabaseManager│ │KnowledgeService│ │CacheManager │              ││   │
│   │  │  │   (Singleton) │ │  (Singleton)   │ │ (Singleton) │              ││   │
│   │  │  └──────────────┘ └──────────────┘ └──────────────┘              ││   │
│   │  │  ┌──────────────┐ ┌──────────────┐                               ││   │
│   │  │  │StatusManager │ │ ProductSync  │                               ││   │
│   │  │  │   (Singleton) │ │  (Singleton) │                               ││   │
│   │  │  └──────────────┘ └──────────────┘                               ││   │
│   │  └─────────────────────────────────────────────────────────────────┘│   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                      │                                        │
│                                      ▼                                        │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                        Data Layer                                    │   │
│   │                                                                       │   │
│   │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │   │
│   │  │    SQLite    │  │ 知识库文件    │  │  配置文件    │  │  日志    │ │   │
│   │  │   Database   │  │ (PDF/Word)   │  │ config.json │  │ app.log  │ │   │
│   │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────┘ │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                               │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 分层架构

### 1. 表现层 (Presentation Layer)

**职责**: 用户界面展示与交互

**组件**:
- `MainWindow`: 主窗口，管理子页面切换
- `AutoReplyUI`: 自动回复控制面板
- `KnowledgeUI`: 知识库管理界面
- `SettingUI`: 系统设置界面
- `LogUI`: 日志查看界面
- `UserManagerWidget`: 账号管理

**技术**:
- PyQt6: GUI 框架
- pyqt6-fluent-widgets: 现代化 UI 组件库

**关键代码**:
```python
class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self.initNavigation()
        self.initWindow()
    
    def initNavigation(self):
        self.addSubPage(self.homeInterface, "主页", FIF.HOME)
        self.addSubPage(self.autoReplyInterface, "自动回复", FIF.ROBOT)
        self.addSubPage(self.knowledgeInterface, "知识库", FIF.BOOK_SHELF)
```

---

### 2. 业务层 (Business Layer)

**职责**: 核心业务逻辑处理

**模块划分**:

#### 2.1 Agent Module
负责 AI 智能回复生成。

```
Agent Module
├── CustomerAgent (主类)
│   ├── LLMClient (LLM 调用)
│   ├── SessionManager (会话管理)
│   ├── MessageBuilder (消息构建)
│   └── ToolExecutor (工具执行)
│
└── Tools (工具集)
    ├── get_product_knowledge (商品知识查询)
    ├── get_product_list (商品列表获取)
    ├── send_goods_link (发送商品卡片)
    ├── search_customer_service_knowledge (客服知识搜索)
    └── transfer_conversation (转人工)
```

#### 2.2 Message Module
负责消息队列与处理。

```
Message Module
├── MessageQueue (消息队列)
│   ├── enqueue() (入队)
│   └── dequeue() (出队)
│
├── MessageConsumer (消息消费者)
│   └── process() (处理消息)
│
└── Handlers (处理器链)
    ├── KeywordHandler (关键词检测)
    ├── AIHandler (AI 处理)
    └── SafetyHandler (安全检查)
```

#### 2.3 Channel Module
负责渠道集成。

```
Channel Module
└── PDDChannel (拼多多渠道)
    ├── Core
    │   ├── LifecycleMixin (生命周期管理)
    │   ├── ConnectionMixin (连接管理)
    │   ├── MessageHandlerMixin (消息处理)
    │   └── StatusMixin (状态管理)
    │
    ├── API
    │   ├── SendMessage (发送消息)
    │   ├── GetToken (获取 Token)
    │   ├── ProductManager (商品管理)
    │   └── GetUserInfo (用户信息)
    │
    └── Utils
        ├── BaseRequest (请求基类)
        └── PDDLogin (登录工具)
```

---

### 3. 服务层 (Service Layer)

**职责**: 提供公共服务，管理服务生命周期

**核心组件**:

#### 3.1 DI Container (依赖注入容器)

```python
class DIContainer:
    def register_singleton(self, service_type, instance=None, factory=None):
        """注册单例服务"""
        
    def register_transient(self, service_type, implementation_type=None, factory=None):
        """注册瞬态服务"""
        
    def register_scoped(self, service_type, implementation_type=None, factory=None):
        """注册作用域服务"""
        
    def get(self, service_type) -> Any:
        """获取服务实例"""
```

#### 3.2 核心服务

| 服务名 | 生命周期 | 职责 |
|--------|----------|------|
| DatabaseManager | Singleton | 数据库操作封装 |
| KnowledgeService | Singleton | 知识库检索服务 |
| CacheManager | Singleton | 本地缓存管理 |
| ConnectionStatusManager | Singleton | 连接状态管理 |
| ProductSyncService | Singleton | 商品数据同步 |

---

### 4. 数据层 (Data Layer)

**职责**: 数据持久化与访问

**组件**:

#### 4.1 SQLite 数据库

```python
class DatabaseManager:
    def __init__(self, db_path: str):
        self.engine = create_engine(f'sqlite:///{db_path}')
        self.Session = sessionmaker(bind=self.engine)
    
    # 账号管理
    def add_account(self, channel_name, shop_id, user_id, username, password, cookies)
    def get_account(self, channel_name, shop_id, user_id)
    def update_account_cookies(self, channel_name, shop_id, user_id, cookies)
    
    # 关键词管理
    def add_keyword(self, channel_name, keyword, action)
    def get_keywords(self, channel_name)
    
    # 知识管理
    def add_knowledge(self, shop_id, knowledge_type, content, keywords)
    def search_knowledge(self, shop_id, query, knowledge_type)
```

#### 4.2 数据模型

```python
class Channel(Base):
    __tablename__ = 'channels'
    id = Column(Integer, primary_key=True)
    channel_name = Column(String, unique=True)
    description = Column(String)

class Shop(Base):
    __tablename__ = 'shops'
    id = Column(Integer, primary_key=True)
    channel_id = Column(Integer, ForeignKey('channels.id'))
    shop_id = Column(String)
    shop_name = Column(String)

class Account(Base):
    __tablename__ = 'accounts'
    id = Column(Integer, primary_key=True)
    shop_id = Column(Integer, ForeignKey('shops.id'))
    user_id = Column(String)
    username = Column(String)
    password = Column(String)
    cookies = Column(Text)

class Knowledge(Base):
    __tablename__ = 'knowledge'
    id = Column(Integer, primary_key=True)
    shop_id = Column(String)
    knowledge_type = Column(String)  # product/customer_service
    content = Column(Text)
    keywords = Column(Text)

class Keyword(Base):
    __tablename__ = 'keywords'
    id = Column(Integer, primary_key=True)
    channel_name = Column(String)
    keyword = Column(String)
    action = Column(String)  # transfer_to_human
```

---

## 核心组件

### 1. CustomerAgent

**类图**:
```
┌─────────────────────────────────────────────────────────────┐
│                      CustomerAgent                           │
├─────────────────────────────────────────────────────────────┤
│ - _config: AgentConfig                                      │
│ - _llm_client: LLMClient                                    │
│ - _message_builder: MessageBuilder                          │
│ - _tool_executor: ToolExecutor                              │
│ - _session_manager: SessionManager                          │
│ - _tools: List[Dict]                                        │
├─────────────────────────────────────────────────────────────┤
│ + initialize_async() → bool                                 │
│ + async_reply(query: str, context: Context) → Reply         │
│ - _run_agent_loop(messages: List, dependencies: Dict) → str│
│ - _compress_with_llm(session_id: str, history: List)       │
└─────────────────────────────────────────────────────────────┘
```

**状态转换**:
```
┌─────────┐  initialize_async()  ┌──────────────┐
│ Created │ ──────────────────▶ │ Initialized  │
└─────────┘                      └──────────────┘
                                        │
                                        │ async_reply()
                                        ▼
                                 ┌──────────────┐
                                 │   Processing │
                                 └──────────────┘
```

---

### 2. PDDChannel

**类图**:
```
┌─────────────────────────────────────────────────────────────┐
│                       PDDChannel                             │
├─────────────────────────────────────────────────────────────┤
│ Inherits: LifecycleMixin, ConnectionMixin,                  │
│           MessageHandlerMixin, StatusMixin                   │
├─────────────────────────────────────────────────────────────┤
│ - base_url: str = "wss://m-ws.pinduoduo.com/"               │
│ - API_VERSION: str = "3"                                    │
│ - ws: WebSocket                                             │
│ - status_manager: ConnectionStatusManager                   │
│ - reconnect_config: ReconnectConfig                         │
│ - heartbeat_config: HeartbeatConfig                         │
├─────────────────────────────────────────────────────────────┤
│ + start_account(shop_id, user_id)                          │
│ + stop_account(shop_id, user_id)                           │
│ + init(shop_id, user_id, username)                         │
│ - _heartbeat_loop(websocket, shop_id, user_id, username)   │
│ - _message_loop(websocket, shop_id, user_id, username)    │
│ - _process_websocket_message(message)                      │
└─────────────────────────────────────────────────────────────┘
```

**状态机**:
```
        start_account()
DISCONNECTED ──────────────▶ CONNECTING
     ▲                              │
     │                              │ WebSocket connected
     │                              ▼
     │                       CONNECTED
     │                              │
     │                              │ WebSocket closed
     │                              ▼
     └─────────────────────── ERROR
                                 │
                                 │ auto_reconnect=True
                                 ▼
                          RECONNECTING
                                 │
                                 │ reconnect_success
                                 └────────────▶ CONNECTED
```

---

### 3. MessageQueue

**类图**:
```
┌─────────────────────────────────────────────────────────────┐
│                      MessageQueue                            │
├─────────────────────────────────────────────────────────────┤
│ - _queue: asyncio.Queue                                      │
│ - _handlers: List[BaseHandler]                              │
│ - _semaphore: asyncio.Semaphore                             │
├─────────────────────────────────────────────────────────────┤
│ + enqueue(message: Dict) → bool                             │
│ + dequeue() → Dict                                          │
│ + process(message: Dict) → bool                             │
│ + register_handler(handler: BaseHandler)                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      BaseHandler                             │
├─────────────────────────────────────────────────────────────┤
│ + can_handle(context: Context) → bool                       │
│ + handle(context: Context, metadata: Dict) → bool          │
└─────────────────────────────────────────────────────────────┘
         △
         │
    ┌────┴────┬─────────────────┐
    │         │                 │
┌───┴───┐ ┌───┴───┐        ┌───┴───┐
│Keyword│ │  AI   │        │Safety │
│Handler│ │Handler│        │Handler│
└───────┘ └───────┘        └───────┘
```

---

## 数据模型

### 1. Context (上下文)

```python
class Context:
    type: ContextType           # 消息类型
    content: str                # 消息内容
    channel_type: ChannelType   # 渠道类型
    kwargs: Any                 # 额外参数
    metadata: Dict              # 元数据

class ContextType(Enum):
    TEXT = "text"
    IMAGE = "image"
    GOODS_INQUIRY = "goods_inquiry"
    GOODS_SPEC = "goods_spec"
    ORDER_INFO = "order_info"
```

### 2. Reply (回复)

```python
class Reply:
    type: ReplyType             # 回复类型
    content: str                # 回复内容

class ReplyType(Enum):
    TEXT = "text"
    IMAGE = "image"
    GOODS_LINK = "goods_link"
    ERROR = "error"
```

### 3. 连接状态

```python
class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"

class ConnectionStatus:
    shop_id: str
    user_id: str
    username: str
    state: ConnectionState
    error_message: Optional[str]
    last_update: datetime
```

---

## 接口规范

### 1. Bot 接口

```python
class Bot(ABC):
    @abstractmethod
    async def async_reply(self, query: str, context: Context) -> Reply:
        """异步回复接口"""
        pass
    
    @abstractmethod
    def reply(self, query: str, context: Context) -> Reply:
        """同步回复接口"""
        pass
```

### 2. Handler 接口

```python
class BaseHandler(ABC):
    @abstractmethod
    def can_handle(self, context: Context) -> bool:
        """判断是否能处理该消息"""
        pass
    
    @abstractmethod
    async def handle(self, context: Context, metadata: Dict) -> bool:
        """处理消息"""
        pass
```

### 3. Tool 接口

```python
def agent_tool(
    name: str,
    description: str,
    parameters: Optional[Dict] = None
):
    """工具装饰器
    
    Args:
        name: 工具名称
        description: 工具描述
        parameters: 参数定义 (JSON Schema)
    """
    def decorator(func):
        # 注册工具
        register_tool(name, description, parameters, func)
        return func
    return decorator
```

---

## 部署架构

### 单机部署

```
┌─────────────────────────────────────────────────────────────┐
│                     Windows 机器                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Customer-Agent (app.py)                │   │
│  │                                                      │   │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐    │   │
│  │  │   PyQt6    │  │  Agent      │  │  Channel   │    │   │
│  │  │    UI      │  │  Module     │  │  Module    │    │   │
│  │  └────────────┘  └────────────┘  └────────────┘    │   │
│  │         │                │                 │          │   │
│  │         └────────────────┴─────────────────┘          │   │
│  │                           │                           │   │
│  │  ┌────────────────────────────────────────────────┐  │   │
│  │  │            SQLite Database                      │  │   │
│  │  │         ./temp/channel_shop.db                  │  │   │
│  │  └────────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────┘   │
│                             │                                │
│                             ▼                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Playwright Chromium                    │   │
│  │           ./browser_data/ (登录态)                  │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
           │                               │
           │ WebSocket                     │ HTTPS
           ▼                               ▼
┌─────────────────────┐       ┌─────────────────────────────┐
│  拼多多 WebSocket    │       │    LLM API Server          │
│  m-ws.pinduoduo.com │       │  (http://67.230.168.254:8080)│
└─────────────────────┘       └─────────────────────────────┘
```

### 资源需求

| 资源 | 最低要求 | 推荐配置 |
|------|---------|---------|
| CPU | 2核 | 4核+ |
| 内存 | 4GB | 8GB+ |
| 磁盘 | 1GB | 5GB+ |
| 网络 | 1Mbps | 10Mbps+ |

---

**文档版本**: 1.0.0
**更新时间**: 2026-05-01
**作者**: Claude Code Analysis
