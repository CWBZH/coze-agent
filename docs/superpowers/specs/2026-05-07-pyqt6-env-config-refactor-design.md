# PyQt6 + QFluentWidgets 界面重构设计文档

**日期：** 2026-05-07
**状态：** 已批准
**作者：** Claude Code

---

## 概述

废弃 config.json，实现 SettingUI 直接读写 .env 文件，并升级 LogUI 以展示格式化的"AI 思考链路"日志，取消非必要的弹窗干扰。

---

## 设计决策

### 配置参数范围
**决策：** 所有参数都在 SettingUI 中可见和可编辑
- 包括现有 config.json 参数（LLM、本地模型、业务时间、路由、数据库）
- 包括 V2.0 环境变量参数（Redis、Qdrant、TTLs、阈值）

### 配置文件迁移策略
**决策：** 完全迁移到 .env，废弃 config.json
- 所有配置统一由 .env 管理
- 提示词指令存入 Redis（支持多店铺隔离）

### AI 思考链路展示方式
**决策：** 新增独立卡片展示
- 在 LogUI 中创建专门的 AIThoughtChainCard
- 与普通日志分开展示
- 红线意图保留原有弹窗警报

---

## 架构设计

### 整体架构

```
.env 文件 ←→ SettingUI (可视化编辑)
           ↓
    app.py 启动加载 (load_dotenv 在最顶端)
           ↓
    core/config.py 读取
           ↓
    业务逻辑使用

AI处理线程 → ai_thought_chain_signal → LogUI AIThoughtChainCard
```

### 核心改动文件

1. `ui/setting_ui.py` - 重构为使用 python-dotenv 读写 .env
2. `ui/signal_bus.py` - 新增 `ai_thought_chain_signal` 信号
3. `ui/log_ui.py` - 新增 `AIThoughtChainCard` 独立卡片
4. `app.py` - 启动时加载 .env（添加 `load_dotenv()`）
5. 新建 `.env` - 存放所有配置参数
6. 新建 `scripts/init_env.py` - .env 初始化脚本

---

## .env 文件结构

**文件位置：** 项目根目录 `.env`

```env
# =============================================================================
# LLM 云端模型配置
# =============================================================================
LLM_API_KEY=your_api_key_here
LLM_API_BASE=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL_NAME=doubao-seed-1-6-flash-250828

# =============================================================================
# 本地模型配置 (Ollama)
# =============================================================================
LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_BASE_URL=http://localhost:11434
LOCAL_MODEL_NAME=customer-service
LOCAL_MODEL_MAX_TOKENS=50
LOCAL_MODEL_TEMPERATURE=0.3
LOCAL_MODEL_TIMEOUT=30

# =============================================================================
# 路由配置
# =============================================================================
ROUTING_LOCAL_MAX_LENGTH=15
ROUTING_FALLBACK_ON_ERROR=true

# =============================================================================
# Redis 配置
# =============================================================================
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=123456
REDIS_DB=0

# =============================================================================
# Qdrant 配置
# =============================================================================
QDRANT_HOST=localhost
QDRANT_PORT=6333

# =============================================================================
# TTL 时间配置 (秒)
# =============================================================================
HUMAN_LOCK_TTL=240
INFERENCE_LOCK_TTL=10
INTENT_CACHE_TTL=600
ALERT_COOLDOWN_TTL=60
AI_AWAKENING_TTL=30

# =============================================================================
# 意图判定配置
# =============================================================================
SHORT_SENTENCE_THRESHOLD=5

# =============================================================================
# 业务时间配置
# =============================================================================
BUSINESS_HOURS_START=08:00
BUSINESS_HOURS_END=23:00

# =============================================================================
# 数据库配置
# =============================================================================
DB_PATH=./temp/channel_shop.db
```

**提示词指令存储：** Redis 键名 `shop:{shop_id}:prompt_instructions`

---

## SettingUI 重构设计

### UI 卡片布局

```
SettingUI
├── 店铺选择器 (ComboBox)
├── LLMConfigCard          ← .env: LLM_API_KEY, LLM_API_BASE, LLM_MODEL_NAME
├── LocalModelConfigCard   ← .env: LOCAL_MODEL_* 参数
├── RedisConfigCard        ← .env: REDIS_HOST, REDIS_PORT, REDIS_PASSWORD, REDIS_DB
├── QdrantConfigCard       ← .env: QDRANT_HOST, QDRANT_PORT
├── TTLConfigCard          ← .env: HUMAN_LOCK_TTL, INFERENCE_LOCK_TTL, etc.
├── ThresholdConfigCard    ← .env: SHORT_SENTENCE_THRESHOLD, ROUTING_LOCAL_MAX_LENGTH
├── BusinessHoursCard      ← .env: BUSINESS_HOURS_START, BUSINESS_HOURS_END
├── PromptConfigCard       ← Redis: shop:{shop_id}:prompt_instructions
└── Save Button            ← 保存所有配置到 .env 和 Redis
```

### 防错逻辑

#### 1. 绝对路径安全处理

```python
from pathlib import Path
from dotenv import load_dotenv, set_key, find_dotenv

# 项目根目录（在模块顶部定义）
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

def saveToEnv(self):
    """保存到 .env（使用绝对路径）"""
    # 确保 .env 文件存在
    if not ENV_FILE.exists():
        ENV_FILE.touch()

    # 使用绝对路径写入
    set_key(str(ENV_FILE), "REDIS_HOST", self.redis_host_edit.text())
    set_key(str(ENV_FILE), "REDIS_PORT", str(self.redis_port_spin.value()))
    # ... 其他字段
```

#### 2. Redis 变更的连接重建逻辑

```python
def onSaveClicked(self):
    """保存所有配置"""
    try:
        # 1. 检查 Redis 配置是否变更
        redis_config_changed = self._checkRedisConfigChanged()

        # 2. 保存所有卡片到 .env
        self.llm_card.saveToEnv()
        self.redis_card.saveToEnv()
        # ... 其他卡片

        # 3. 如果 Redis 配置变更，重建连接池
        if redis_config_changed:
            from database.redis_manager import reinit_redis_client
            reinit_redis_client(
                host=self.redis_card.host,
                port=self.redis_card.port,
                password=self.redis_card.password,
                db=self.redis_card.db
            )

        # 4. 保存提示词到 Redis（此时连接已更新）
        instructions = self.prompt_card.getConfig()["instructions"]
        redis_client = get_redis_client()
        redis_client.set(
            f"shop:{self.current_shop_id}:prompt_instructions",
            json.dumps(instructions, ensure_ascii=False)
        )

        # 5. 内存环境变量热刷新
        load_dotenv(str(ENV_FILE), override=True)

        # 6. 成功提示
        InfoBar.success(
            title="配置已同步",
            content="配置已保存至 .env 和 Redis，部分配置需重启生效",
            duration=3000
        )
    except Exception as e:
        logger.exception("保存配置失败")
        InfoBar.error(title="保存失败", content=str(e))

def _checkRedisConfigChanged(self) -> bool:
    """检查 Redis 配置是否变更"""
    try:
        current_host = os.getenv("REDIS_HOST") or "localhost"
        current_port = int(os.getenv("REDIS_PORT") or 6379)
        current_password = os.getenv("REDIS_PASSWORD") or "123456"
        current_db = int(os.getenv("REDIS_DB") or 0)
    except ValueError:
        # 容错：遇到脏数据自动降级为默认值
        current_host = "localhost"
        current_port = 6379
        current_password = "123456"
        current_db = 0

    return (
        self.redis_card.host != current_host or
        self.redis_card.port != current_port or
        self.redis_card.password != current_password or
        self.redis_card.db != current_db
    )
```

#### 3. 多店铺命名空间隔离

```python
# Redis 键名格式
REDIS_KEY_PROMPT = "shop:{shop_id}:prompt_instructions"
REDIS_KEY_KNOWLEDGE = "shop:{shop_id}:knowledge:{knowledge_id}"

# 使用示例
def savePromptInstructions(self, shop_id: str, instructions: list):
    """保存店铺的提示词指令"""
    redis_client = get_redis_client()
    key = REDIS_KEY_PROMPT.format(shop_id=shop_id)
    redis_client.set(key, json.dumps(instructions, ensure_ascii=False))

def loadPromptInstructions(self, shop_id: str) -> list:
    """加载店铺的提示词指令"""
    redis_client = get_redis_client()
    key = REDIS_KEY_PROMPT.format(shop_id=shop_id)
    data = redis_client.get(key)
    return json.loads(data) if data else []
```

---

## SignalBus 升级设计

### 新增信号

```python
class SignalBus(QObject):
    """全局信号广播站"""

    # 人工接管警报信号
    human_fallback_signal = pyqtSignal(str, str, str, str)

    # AI 思考链路信号：session_id, intent, latency, knowledge_source, response_preview
    ai_thought_chain_signal = pyqtSignal(str, str, float, str, str)
```

---

## LogUI 升级设计

### 新增 AIThoughtChainCard

```python
class AIThoughtChainCard(CardWidget):
    """AI 思考链路展示卡片"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUI()
        self.connectSignals()

    def setupUI(self):
        layout = QVBoxLayout(self)

        # 标题
        title = StrongBodyLabel("AI 思考链路监控")
        title.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(title)

        # 日志列表
        self.log_list = QListWidget()
        self.log_list.setStyleSheet("""
            QListWidget {
                background-color: #f5f5f5;
                border: 1px solid #ddd;
                font-family: 'Consolas', 'Microsoft YaHei';
                font-size: 11px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #e0e0e0;
            }
        """)
        layout.addWidget(self.log_list)

        # 清空按钮
        clear_btn = PushButton("清空日志", self, FIF.DELETE)
        clear_btn.clicked.connect(self.log_list.clear)
        layout.addWidget(clear_btn)

    def connectSignals(self):
        """连接信号"""
        global_signal_bus.ai_thought_chain_signal.connect(self.onAIThoughtChain)

    def onAIThoughtChain(self, session_id, intent, latency, knowledge_source, response_preview):
        """接收 AI 思考链路信号（禁止弹窗）"""
        # 格式化日志文本
        log_text = (
            f"[AI思考链路] 会话:{session_id} | "
            f"意图:{intent} | "
            f"耗时:{latency:.2f}s | "
            f"知识:{knowledge_source} | "
            f"回复:{response_preview[:50]}..."
        )

        # 添加到列表（不触发 InfoBar/MessageBox）
        self.log_list.addItem(log_text)

        # 自动滚动到最新
        self.log_list.scrollToBottom()
```

### 红线保底逻辑

```python
# 在 AI 处理线程中
def process_message(self, message: str, shop_id: str, user_id: str):
    """处理消息"""
    # ... 意图识别、知识检索、回复生成

    # 发射 AI 思考链路信号（不弹窗）
    global_signal_bus.ai_thought_chain_signal.emit(
        session_id,
        intent,
        latency,
        knowledge_source,
        response_preview
    )

    # 只有红线意图才触发人工接管警报（弹窗）
    if intent == "redline":
        global_signal_bus.human_fallback_signal.emit(
            shop_id,
            user_id,
            "检测到高危红线意图",
            "high"
        )
```

---

## app.py 启动逻辑

### 关键顺序

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
客服智能体主程序
"""
# =============================================================================
# 第一步：加载 .env（必须在所有自定义模块导入之前）
# =============================================================================
from pathlib import Path
from dotenv import load_dotenv

# 锁定 .env 绝对路径
BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

# 强制加载 .env，覆盖已有环境变量
load_dotenv(str(ENV_FILE), override=True)

# =============================================================================
# 第二步：导入系统模块
# =============================================================================
import sys
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import FluentTranslator

# =============================================================================
# 第三步：导入自定义模块（此时 .env 已加载完成）
# =============================================================================
from ui.main_ui import MainWindow
from utils.logger_loguru import get_logger
from core.config import validate_config

# =============================================================================
# 第四步：主程序
# =============================================================================
def main():
    """主函数"""
    # 验证配置
    if not validate_config():
        logger = get_logger("App")
        logger.error("配置验证失败，请检查 .env 文件")
        sys.exit(1)

    # 创建应用
    app = QApplication(sys.argv)

    # 设置国际化
    translator = FluentTranslator()
    app.installTranslator(translator)

    # 创建主窗口
    window = MainWindow()
    window.show()

    # 运行应用
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

---

## .env 初始化脚本

### scripts/init_env.py

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
.env 文件初始化脚本
从 config.json 迁移数据并添加 V2.0 默认参数
"""
from pathlib import Path
import json

def init_env_file():
    """初始化 .env 文件"""
    base_dir = Path(__file__).resolve().parent.parent
    env_file = base_dir / ".env"

    if env_file.exists():
        print(".env 文件已存在")
        return

    # 从 config.json 迁移数据
    config_file = base_dir / "config.json"

    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)

        # 生成 .env 内容 (补充 V2.0 默认兜底参数)
        env_content = f"""# ==========================================
# 核心业务配置 (自 config.json 迁移)
# ==========================================
LLM_API_KEY={config.get('llm', {}).get('api_key', '')}
LLM_API_BASE={config.get('llm', {}).get('api_base', '')}
LLM_MODEL_NAME={config.get('llm', {}).get('model_name', '')}

LOCAL_MODEL_ENABLED=true
LOCAL_MODEL_BASE_URL={config.get('local_model', {}).get('base_url', 'http://localhost:11434')}
LOCAL_MODEL_NAME={config.get('local_model', {}).get('model_name', 'customer-service')}
LOCAL_MODEL_MAX_TOKENS={config.get('local_model', {}).get('max_tokens', 50)}
LOCAL_MODEL_TEMPERATURE={config.get('local_model', {}).get('temperature', 0.3)}
LOCAL_MODEL_TIMEOUT={config.get('local_model', {}).get('timeout', 30)}

ROUTING_LOCAL_MAX_LENGTH={config.get('routing', {}).get('local_max_length', 15)}
ROUTING_FALLBACK_ON_ERROR={config.get('routing', {}).get('fallback_on_error', 'true')}

BUSINESS_HOURS_START={config.get('business_hours', {}).get('start', '08:00')}
BUSINESS_HOURS_END={config.get('business_hours', {}).get('end', '23:00')}

DB_PATH={config.get('db_path', './temp/channel_shop.db')}

# ==========================================
# V2.0 引擎新增依赖配置 (默认兜底值)
# ==========================================
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=123456
REDIS_DB=0

QDRANT_HOST=localhost
QDRANT_PORT=6333

HUMAN_LOCK_TTL=240
INFERENCE_LOCK_TTL=10
INTENT_CACHE_TTL=600
ALERT_COOLDOWN_TTL=60
SHORT_SENTENCE_THRESHOLD=5
"""

        # 写入 .env
        env_file.write_text(env_content, encoding="utf-8")
        print(f".env 文件已创建: {env_file}")
    else:
        print("config.json 不存在，请手动创建 .env")

if __name__ == "__main__":
    init_env_file()
```

---

## 依赖处理

### pyproject.toml 新增依赖

```toml
[project.dependencies]
python-dotenv = "^1.0.0"
```

---

## 测试要点

1. **.env 加载顺序** - 确保 load_dotenv() 在所有自定义模块导入之前
2. **绝对路径安全** - 测试在不同目录启动程序
3. **Redis 连接重建** - 测试修改 Redis 配置后保存提示词
4. **多店铺隔离** - 测试切换店铺时配置加载
5. **内存热刷新** - 测试修改配置后立即生效
6. **容错类型转换** - 测试 .env 文件损坏时的降级处理
7. **AI 思考链路** - 测试信号发射和日志展示
8. **红线保底** - 测试红线意图触发弹窗

---

## 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| .env 文件路径错误 | 使用绝对路径 BASE_DIR / ".env" |
| Redis 配置变更导致连接失败 | 先重建连接池再保存提示词 |
| 多店铺配置混乱 | 使用命名空间隔离 shop:{shop_id}:* |
| 配置修改不生效 | 内存热刷新 load_dotenv(override=True) |
| .env 文件损坏 | 容错类型转换，降级为默认值 |
| V2.0 参数缺失 | 初始化脚本写入默认兜底值 |

---

## 实施步骤

1. 创建 `.env` 文件（运行 `scripts/init_env.py`）
2. 更新 `app.py` 启动逻辑（添加 load_dotenv）
3. 重构 `ui/setting_ui.py`（使用 python-dotenv）
4. 升级 `ui/signal_bus.py`（新增信号）
5. 升级 `ui/log_ui.py`（新增 AIThoughtChainCard）
6. 更新 `pyproject.toml`（添加依赖）
7. 测试所有功能点
8. 废弃 `config.json`
