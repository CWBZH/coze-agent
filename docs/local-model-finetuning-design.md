# 本地模型微调方案设计

## 1. 方案概述

### 1.1 背景

当前客服助手使用远程 GLM-5 API，存在以下问题：
- API调用成本持续产生
- 回复风格过于AI化（emoji多、字数多、机械口吻）
- 专业知识需进一步定制

### 1.2 目标

- **降低成本**：减少 60%+ API 调用
- **提升专业性**：针对电商客服场景优化回复风格
- **保证质量**：复杂问题仍由远程大模型兜底

### 1.3 方案选择

采用**混合路由方案**：短问题本地处理，长问题远程兜底。

---

## 2. 系统架构

### 2.1 整体架构

```
用户消息
    │
    ▼
┌─────────────────────┐
│  路由器（长度判断）   │
│  len(query) ≤ 15    │ → 本地
│  len(query) > 15    │ → 远程
└─────────────────────┘
    │
    ├── ≤ 15字符
    │       │
    │       ▼
    │   本地 Qwen2.5-7B-Int4 回复
    │
    └── > 15字符
            │
            ▼
        远程 GLM-5 回复
```

### 2.2 路由规则

```python
def route(query: str) -> str:
    """
    路由判断：短问题走本地，长问题走远程
    
    短问题示例：多少钱、有货吗、能退吗、什么时候发货
    长问题示例：复杂咨询、投诉、多条件查询
    """
    return 'local' if len(query) <= 15 else 'remote'
```

### 2.3 预期效果

| 问题类型 | 占比 | 处理方式 |
|----------|------|----------|
| 短问题（≤15字） | 60-70% | 本地模型 |
| 长问题（>15字） | 30-40% | 远程API |

预计节省 **60%+ API调用成本**。

---

## 3. 模型选型

### 3.1 基座模型

**Qwen2.5-7B-Instruct**

| 特性 | 说明 |
|------|------|
| 参数量 | 7B |
| 中文能力 | 优秀（阿里通义团队） |
| 电商场景 | 表现良好 |
| 量化后显存 | 4-bit量化后约 4-5GB |
| 运行环境 | RTX 4060 8GB 可运行 |

### 3.2 量化方案

- **量化方式**：4-bit量化（GPTQ/AWQ）
- **推理引擎**：Ollama 或 vLLM
- **显存占用**：约 4-5GB

### 3.3 微调方法

- **微调方式**：LoRA（Low-Rank Adaptation）
- **优势**：参数高效、训练快速、易于迭代
- **工具**：LLaMA-Factory

---

## 4. 训练数据设计

### 4.1 数据来源

| 来源 | 数量目标 | 说明 |
|------|----------|------|
| 产品知识生成 | 1500条 | 基于36个产品生成多样化问答 |
| 客服知识生成 | 600条 | 售后、物流、退换货等场景 |
| 多轮对话 | 600条 | 模拟真实对话场景，包含上下文理解 |
| 工具调用 | 300条 | 学习调用知识库工具 |
| 拒绝/转人工 | 150条 | 边界情况处理 |
| **生成合计** | **3150条** | 原始生成数据 |
| **筛选后预计** | **2000-2500条** | 人工筛选后保留高质量数据 |

### 4.2 数据筛选流程

```
┌─────────────────────────────────────────────────────────────┐
│                    数据筛选工作流                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ① GLM-5 批量生成 3150 条                                   │
│     多种问题模板，覆盖不同场景                                │
│            │                                                │
│            ▼                                                │
│  ② 自动过滤（去重+格式校验）                                 │
│     - 去除重复问题                                           │
│     - 校验 JSON 格式                                         │
│     - 过滤过短/过长回复                                      │
│            │                                                │
│            ▼                                                │
│  ③ 人工筛选修正（预计 1-2 天）                               │
│     - 标注数据质量（1-5分）                                  │
│     - 修改回复风格（自然化）                                 │
│     - 删除低质量/错误数据                                    │
│     - 保留 2000-2500 条高质量数据                            │
│            │                                                │
│            ▼                                                │
│  ④ 数据集划分                                                │
│     训练集 80% / 验证集 10% / 测试集 10%                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.3 筛选标准

| 维度 | 标准 | 处理方式 |
|------|------|----------|
| 准确性 | 信息是否正确 | 错误则删除或修正 |
| 风格自然度 | 是否像真人说话 | 修改为自然口吻 |
| 长度 | 是否 ≤30 字 | 过长则精简 |
| Emoji使用 | 是否 ≤2 个 | 过多则删除 |
| 重复性 | 是否与已有数据相似 | 保留一条，删除重复 |

### 4.2 数据格式（Alpaca格式）

**基础问答格式**：
```json
{
  "instruction": "你是{shop_name}的电商客服。请用中文简短回复用户问题，控制在30字以内。回复要自然亲切，像真人聊天，偶尔用1-2个emoji点缀。根据提供的商品知识准确回答，不要编造信息。",
  "input": "【商品知识】\n商品名称：氨基酸洗面奶\n主要成分：氨基酸表活、神经酰胺\n适用肤质：所有肤质，敏感肌可用\n价格：89元\n\n【用户问题】\n这款洗面奶适合油皮吗",
  "output": "适合的，这款是氨基酸配方，控油不紧绷，油皮放心用~"
}
```

**多轮对话格式**：
```json
{
  "instruction": "你是{shop_name}的电商客服...",
  "input": "【历史对话】\n用户：这款洗面奶多少钱\n客服：89元哦\n\n【当前问题】\n用户：适合敏感肌吗",
  "output": "温和配方，敏感肌也能用的~"
}
```

**工具调用格式**：
```json
{
  "instruction": "你是{shop_name}的电商客服...",
  "input": "【用户问题】\n这个面霜成分是什么\n\n【可用工具】\nget_product_knowledge(goods_id, shop_id)",
  "output": "[CALL] get_product_knowledge(goods_id=750535008531, shop_id=323473738)"
}
```

**拒绝回答格式**：
```json
{
  "instruction": "你是{shop_name}的电商客服...",
  "input": "你们能不能帮我代购其他牌子的东西",
  "output": "抱歉亲，我们只售本店商品哦，其他品牌建议去官方渠道看看~"
}
```

**转人工格式**：
```json
{
  "instruction": "你是{shop_name}的电商客服...",
  "input": "我要投诉你们发错货了！",
  "output": "实在抱歉给您添麻烦了，帮您转接人工客服处理~"
}
```

### 4.3 数据生成流程

```
┌─────────────────────────────────────────────────────────────┐
│                    数据生成工作流                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ① 提取知识库数据                                            │
│     从 product_knowledge 表提取商品信息                       │
│            │                                                │
│            ▼                                                │
│  ② GLM-5 生成问答对                                          │
│     使用现有API批量生成，多种问题模板                          │
│            │                                                │
│            ▼                                                │
│  ③ 人工筛选修正                                              │
│     过滤低质量数据，调整回复风格                               │
│            │                                                │
│            ▼                                                │
│  ④ 格式转换                                                  │
│     转为 Alpaca JSON 格式                                    │
│            │                                                │
│            ▼                                                │
│  ⑤ 数据集划分                                                │
│     训练集 80% / 验证集 10% / 测试集 10%                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.4 Instruction 模板

```
你是{shop_name}的电商客服。请用中文简短回复用户问题，控制在30字以内。回复要自然亲切，像真人聊天，偶尔用1-2个emoji点缀。根据提供的商品知识准确回答，不要编造信息。
```

**设计要点**：
- 角色定义明确
- 输出约束（30字以内）
- 风格要求（自然、少emoji）
- 防幻觉（不编造）

---

## 5. 微调流程

### 5.1 环境准备

```bash
# 安装 LLaMA-Factory
git clone https://github.com/hiyouga/LLaMA-Factory.git
cd LLaMA-Factory
pip install -r requirements.txt

# 下载基座模型
# 方式1：HuggingFace
# 方式2：ModelScope（国内更快）
```

### 5.2 LoRA 配置

```yaml
# lora_config.yaml
model_name_or_path: Qwen/Qwen2.5-7B-Instruct
stage: sft
do_train: true
finetuning_type: lora
lora_target: all

# 数据配置
dataset: customer_service
template: qwen
cutoff_len: 1024

# 训练参数
num_train_epochs: 3
per_device_train_batch_size: 4
gradient_accumulation_steps: 4
learning_rate: 5e-5
lr_scheduler_type: cosine
warmup_ratio: 0.1

# LoRA 参数
lora_rank: 8
lora_alpha: 16
lora_dropout: 0.05

# 量化
quantization_bit: 4
```

### 5.3 训练命令

```bash
llamafactory-cli train lora_config.yaml
```

### 5.4 模型导出

```bash
# 合并 LoRA 权重
llamafactory-cli export \
  --model_name_or_path Qwen/Qwen2.5-7B-Instruct \
  --adapter_name_or_path ./saves/qwen_lora \
  --export_dir ./merged_model \
  --export_size 2

# 量化为 GGUF（可选，用于 Ollama）
python -m llama.cpp.convert ./merged_model --outtype q4_k_m
```

---

## 6. 部署方案

### 6.1 本地推理引擎

**推荐方案：Ollama**

```bash
# 安装 Ollama
# Windows: 下载安装包 https://ollama.com/download

# 拉取模型
ollama pull qwen2.5:7b

# API 调用
curl http://localhost:11434/api/chat -d '{
  "model": "qwen2.5:7b",
  "messages": [{"role": "user", "content": "这款洗面奶多少钱"}],
  "stream": false
}'
```

**优势**：
- 安装简单，开箱即用
- 自动管理模型下载和量化
- 支持多种模型格式
- 社区活跃，模型丰富
- 内置 REST API

**微调模型导入 Ollama**：

```bash
# 1. 转换为 GGUF 格式
python convert-hf-to-gguf.py ./merged_model --outfile qwen-cs.gguf --outtype q4_k_m

# 2. 创建 Modelfile
echo 'FROM ./qwen-cs.gguf
PARAMETER temperature 0.7
PARAMETER num_predict 50
SYSTEM 你是电商客服。请简短回复（30字以内），像真人聊天，偶尔用emoji。' > Modelfile

# 3. 导入 Ollama
ollama create customer-service -f Modelfile
```

### 6.2 代码集成

修改 `customer_agent.py`：

```python
class CustomerAgent(Bot):
    def __init__(self, ...):
        # 新增本地模型客户端（Ollama）
        self._local_client = LocalLLMClient(config.local_model)

    async def async_reply(self, query: str, context: Context = None) -> Reply:
        # 路由判断：短问题本地，长问题远程
        if len(query) <= 15:
            return await self._local_reply(query, context)
        else:
            return await self._remote_reply(query, context)

    async def _local_reply(self, query: str, context: Context) -> Reply:
        """本地模型回复（Ollama）"""
        messages = [
            {"role": "system", "content": "你是电商客服。请简短回复（30字以内），像真人聊天，偶尔用emoji。"},
            {"role": "user", "content": query},
        ]
        response = await self._local_client.chat(messages)

        if response.success:
            return Reply(ReplyType.TEXT, response.content)
        else:
            # 本地模型失败，回退到远程
            if self._config.local_model.fallback_on_error:
                return await self._remote_reply(query, context)
            return Reply(ReplyType.TEXT, "抱歉，我现在无法回复，请稍后再试。")

    async def _remote_reply(self, query: str, context: Context) -> Reply:
        """远程API回复（现有逻辑）"""
        # 保持原有 GLM-5 实现
        ...
```

### 6.3 配置扩展

```json
// config.json 新增配置
{
    "local_model": {
        "enabled": false,
        "base_url": "http://localhost:11434",
        "model_name": "qwen2.5:7b",
        "max_tokens": 50,
        "temperature": 0.7
    },
    "routing": {
        "local_max_length": 15,
        "fallback_on_error": true
    }
}
```

---

## 7. 评估方案

### 7.1 测试集设计

| 类型 | 数量 | 来源 |
|------|------|------|
| 简单问答 | 100条 | 产品知识衍生 |
| 多轮对话 | 50条 | 模拟真实场景 |
| 工具调用 | 30条 | 验证工具能力 |
| 边界情况 | 20条 | 拒绝/转人工 |

### 7.2 评估指标

| 指标 | 说明 | 目标值 |
|------|------|--------|
| 准确率 | 回答是否正确 | > 90% |
| 风格评分 | 人工1-5分 | > 4分 |
| 字数达标率 | ≤30字 | > 85% |
| API节省率 | 路由到本地比例 | > 60% |

### 7.3 对比测试

```bash
# 同一测试集，对比微调前后
python evaluate.py --test-set test.json \
  --model-before qwen-base \
  --model-after qwen-finetuned \
  --metrics accuracy,style,length
```

---

## 8. 实施计划

### 8.1 阶段划分

| 阶段 | 任务 | 预计时间 |
|------|------|----------|
| **Phase 1** | 数据准备 | 4天 |
| | - 编写数据生成脚本 | 1天 |
| | - GLM-5批量生成 3150条 | 1天 |
| | - 自动过滤去重 | 0.5天 |
| | - 人工筛选修正（2000-2500条） | 1.5天 |
| **Phase 2** | 模型微调 | 2天 |
| | - 环境搭建 | 0.5天 |
| | - LoRA训练 | 0.5天 |
| | - 模型导出量化 | 0.5天 |
| | - 本地测试验证 | 0.5天 |
| **Phase 3** | 系统集成 | 2天 |
| | - 路由逻辑开发 | 1天 |
| | - 本地推理集成 | 0.5天 |
| | - 配置管理 | 0.5天 |
| **Phase 4** | 测试上线 | 2天 |
| | - 内部测试 | 1天 |
| | - 灰度发布 | 0.5天 |
| | - 监控告警 | 0.5天 |

**总计：约 10 天**（含数据筛选时间）

### 8.2 风险与应对

| 风险 | 应对措施 |
|------|----------|
| 数据量不足 | 目标生成3150条，筛选后保留2000+，足够微调 |
| 数据质量不均 | 多轮人工筛选，只保留4分以上数据 |
| 本地模型答错 | 关键信息强制走远程，错误回退机制 |
| 显存不足 | 使用4-bit量化，或换小模型 |
| 质量下降 | 保留远程兜底，监控转人工率 |
| vLLM 部署问题 | 备选 Ollama 方案 |

---

## 9. 后续优化方向

1. **持续微调**：收集真实对话数据，定期迭代
2. **路由优化**：基于问题类型而非长度判断
3. **多店铺适配**：训练通用模型或按店铺微调
4. **性能优化**：模型蒸馏、更大量化工

---

**文档版本**：1.0
**创建时间**：2026-05-03
**作者**：Claude Code
