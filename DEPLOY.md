# Customer-Agent 部署指南

## 快速开始

### 1. 配置 API

复制配置模板并填写你的 API 信息：

```bash
copy config.json.template config.json
```

编辑 `config.json`，填入以下信息：

```json
{
    "business_hours": {
        "start": "08:00",
        "end": "23:00"
    },
    "llm": {
        "model_name": "你的模型名称",
        "api_key": "你的API密钥",
        "api_base": "你的API地址"
    },
    "prompt": {
        "instructions": [...]
    },
    "db_path": "./temp/channel_shop.db"
}
```

**重要：请勿将包含真实 API Key 的 config.json 提交到 Git！**

### 2. 启动应用

双击 `start.bat` 或运行：

```bash
.venv\Scripts\python app.py
```

### 3. 使用流程

1. **添加账号** - 在 UI 界面添加拼多多商家账号
2. **登录账号** - 使用 Playwright 自动登录或手动扫码
3. **配置知识库** - 导入商品知识和客服知识
4. **启动监听** - 开始自动回复客服消息

## 目录结构

```
customer-agent/
├── app.py              # 主程序入口
├── config.json         # 配置文件（需自行创建）
├── config.json.template # 配置模板
├── start.bat           # Windows启动脚本
├── .venv/              # Python虚拟环境
├── Agent/              # AI Agent模块
├── Channel/            # 渠道集成（拼多多）
├── Message/            # 消息处理
├── database/           # 数据库模块
├── ui/                 # PyQt6界面
└── utils/              # 工具模块
```

## 风控建议

为避免平台风控，建议：

1. **回复延迟**：3-8秒随机延迟
2. **回复频率**：每分钟不超过5条
3. **关键词转人工**：投诉、退款、举报等
4. **营业时间**：建议仅在8:00-23:00启用

## 安全提醒

- ✅ API Key 仅存储在本地 `config.json`
- ✅ 敏感文件已在 `.gitignore` 中排除
- ✅ 数据不上传第三方服务器
- ❌ 请勿将 `config.json` 提交到 Git

## 常见问题

### Q: 如何替换为本地模型？

修改 `config.json` 中的 `api_base`：

```json
{
    "llm": {
        "api_base": "http://localhost:8000/v1"
    }
}
```

### Q: 如何查看日志？

日志文件位于 `logs/app.log`
