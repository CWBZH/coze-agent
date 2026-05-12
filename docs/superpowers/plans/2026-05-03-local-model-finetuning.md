# Local Model Fine-tuning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement hybrid routing system with local Qwen2.5-7B model for short queries and GLM-5 fallback for complex queries, reducing API costs by 60%+.

**Architecture:** Length-based router (≤15 chars → local vLLM, >15 chars → remote GLM-5). Local model fine-tuned with LoRA on 2000-2500 curated customer service examples.

**Tech Stack:** Qwen2.5-7B-Instruct, LLaMA-Factory, LoRA, 4-bit quantization, vLLM, OpenAI-compatible API

---

## File Structure

```
E:/develop/customer-agent/
├── Agent/CustomerAgent/
│   ├── custom/
│   │   ├── agent_config.py          # MODIFY: Add local_model config
│   │   ├── customer_agent.py        # MODIFY: Add routing logic
│   │   ├── llm_client.py            # KEEP: For remote API
│   │   └── local_llm_client.py      # CREATE: Local vLLM client
│   └── tools/
│       └── ...                       # KEEP: Existing tools
├── finetune/                         # CREATE: Fine-tuning workspace
│   ├── data/
│   │   ├── raw/                      # Generated data (3150 samples)
│   │   ├── filtered/                 # Curated data (2000-2500 samples)
│   │   └── train/                    # Final training data (Alpaca format)
│   ├── scripts/
│   │   ├── generate_data.py          # Data generation script
│   │   ├── filter_data.py            # Auto-filtering script
│   │   └── convert_to_alpaca.py      # Format conversion
│   ├── lora_config.yaml              # LoRA training config
│   └── README.md                     # Fine-tuning instructions
├── config.json                        # MODIFY: Add local_model config
└── docs/
    └── local-model-finetuning-design.md  # EXISTS: Design document
```

---

## Phase 1: Data Generation (4 days)

### Task 1.1: Create Data Generation Script

**Files:**
- Create: `E:/develop/customer-agent/finetune/scripts/generate_data.py`

- [ ] **Step 1: Create finetune directory structure**

```bash
mkdir -p E:/develop/customer-agent/finetune/data/raw
mkdir -p E:/develop/customer-agent/finetune/data/filtered
mkdir -p E:/develop/customer-agent/finetune/data/train
mkdir -p E:/develop/customer-agent/finetune/scripts
```

- [ ] **Step 2: Create data generation script**

Create file `E:/develop/customer-agent/finetune/scripts/generate_data.py`:

```python
"""
训练数据生成脚本

使用 GLM-5 API 从产品知识库和客服知识库生成问答对。
目标：生成 3150 条原始数据，筛选后保留 2000-2500 条。
"""
import json
import random
import asyncio
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass

# 添加项目根目录到 path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.logger_loguru import get_logger

logger = get_logger("DataGenerator")


@dataclass
class DataGenerationConfig:
    """数据生成配置"""
    # 目标数量
    product_knowledge_target: int = 1500
    customer_service_target: int = 600
    multi_turn_target: int = 600
    tool_calling_target: int = 300
    rejection_target: int = 150
    
    # GLM-5 API 配置
    api_base: str = "http://67.230.168.254:8080"
    api_key: str = "sk-255ffd31e6932a83e94e962770a98292d5d1b074349d4d64bbcf7944b99eb4e8"
    model_name: str = "GLM-5"
    
    # 输出路径
    output_dir: Path = Path(__file__).parent.parent / "data" / "raw"


# Instruction 模板
INSTRUCTION_TEMPLATE = """你是{shop_name}的电商客服。请用中文简短回复用户问题，控制在30字以内。回复要自然亲切，像真人聊天，偶尔用1-2个emoji点缀。根据提供的商品知识准确回答，不要编造信息。"""


class DataGenerator:
    """训练数据生成器"""
    
    def __init__(self, config: DataGenerationConfig = None):
        self.config = config or DataGenerationConfig()
        self.output_dir = self.config.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 模拟的 GLM-5 客户端（实际使用时替换为真实 API 调用）
        self._client = None
    
    async def initialize(self):
        """初始化 GLM-5 客户端"""
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.api_base,
        )
        logger.info("GLM-5 客户端初始化成功")
    
    async def generate_with_glm(self, prompt: str) -> str:
        """使用 GLM-5 生成内容"""
        if not self._client:
            await self.initialize()
        
        try:
            response = await self._client.chat.completions.create(
                model=self.config.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=100,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"GLM-5 生成失败: {e}")
            return ""
    
    def generate_product_qa_prompts(self, products: List[Dict]) -> List[Dict]:
        """生成产品问答的提示词"""
        prompts = []
        
        question_templates = [
            "这款{product_name}多少钱？",
            "{product_name}有什么成分？",
            "{product_name}适合什么肤质？",
            "{product_name}怎么使用？",
            "{product_name}有货吗？",
            "{product_name}什么时候发货？",
            "{product_name}能退吗？",
            "{product_name}有什么功效？",
            "{product_name}敏感肌能用吗？",
            "{product_name}和{another_product}哪个好？",
        ]
        
        for product in products:
            product_name = product.get("name", "商品")
            product_info = json.dumps(product, ensure_ascii=False)
            
            for template in question_templates:
                if "{another_product}" in template and len(products) > 1:
                    another = random.choice([p for p in products if p != product])
                    question = template.format(
                        product_name=product_name,
                        another_product=another.get("name", "其他商品")
                    )
                else:
                    question = template.format(product_name=product_name)
                
                prompts.append({
                    "type": "product_qa",
                    "product_name": product_name,
                    "question": question,
                    "context": f"商品信息：{product_info}",
                })
        
        return prompts
    
    def generate_customer_service_prompts(self) -> List[Dict]:
        """生成客服知识问答的提示词"""
        prompts = []
        
        qa_pairs = [
            ("退货怎么操作？", "售后政策：7天无理由退货，需保持商品完好"),
            ("运费谁出？", "质量问题我们承担，其他原因买家承担"),
            ("什么时候发货？", "付款后48小时内发货，节假日顺延"),
            ("能开发票吗？", "可以的，下单时备注发票信息即可"),
            ("怎么修改地址？", "发货前联系客服修改，发货后无法修改"),
            ("发什么快递？", "默认中通，偏远地区邮政"),
            ("能加急吗？", "联系客服备注，尽量安排"),
            ("怎么查物流？", "订单详情里可以看到物流信息"),
        ]
        
        for question, context in qa_pairs:
            # 生成多种问法
            variations = self._generate_question_variations(question)
            for q in variations:
                prompts.append({
                    "type": "customer_service",
                    "question": q,
                    "context": context,
                })
        
        return prompts
    
    def _generate_question_variations(self, question: str) -> List[str]:
        """生成问题的多种问法"""
        # 简单的同义词替换
        variations = [question]
        
        # 常见的用户问法变体
        if "怎么" in question:
            variations.append(question.replace("怎么", "如何"))
        if "能" in question:
            variations.append(question.replace("能", "可以"))
        if "？" in question:
            variations.append(question.replace("？", ""))
        
        return variations
    
    def generate_multi_turn_prompts(self) -> List[Dict]:
        """生成多轮对话的提示词"""
        prompts = []
        
        scenarios = [
            {
                "history": [
                    ("用户", "这款洗面奶多少钱？"),
                    ("客服", "89元哦~"),
                ],
                "current": "适合敏感肌吗？",
                "context": "氨基酸洗面奶，温和配方",
            },
            {
                "history": [
                    ("用户", "有面霜吗？"),
                    ("客服", "有的，这款保湿面霜79元"),
                ],
                "current": "和洗面奶一起买能优惠吗？",
                "context": "套装优惠：洗面奶+面霜=149元",
            },
            {
                "history": [
                    ("用户", "什么时候发货？"),
                    ("客服", "今天下单明天发~"),
                ],
                "current": "到浙江要几天？",
                "context": "江浙沪2-3天，其他地区3-5天",
            },
        ]
        
        for scenario in scenarios:
            history_text = "\n".join([
                f"{role}：{content}"
                for role, content in scenario["history"]
            ])
            
            prompts.append({
                "type": "multi_turn",
                "question": scenario["current"],
                "context": f"历史对话：\n{history_text}\n\n相关知识：{scenario['context']}",
            })
        
        return prompts
    
    def generate_tool_calling_prompts(self) -> List[Dict]:
        """生成工具调用的提示词"""
        prompts = []
        
        tool_scenarios = [
            {
                "question": "这个面霜成分是什么？",
                "tool": "get_product_knowledge",
                "params": "goods_id=750535008531, shop_id=323473738",
            },
            {
                "question": "退货流程是怎样的？",
                "tool": "search_customer_service_knowledge",
                "params": "query='退货流程', shop_id=323473738",
            },
        ]
        
        for scenario in tool_scenarios:
            prompts.append({
                "type": "tool_calling",
                "question": scenario["question"],
                "tool": scenario["tool"],
                "params": scenario["params"],
            })
        
        return prompts
    
    def generate_rejection_prompts(self) -> List[Dict]:
        """生成拒绝回答的提示词"""
        prompts = []
        
        rejection_cases = [
            ("你们能不能帮我代购其他牌子？", "抱歉亲，我们只售本店商品哦~"),
            ("能便宜点吗？", "已经是活动价了，很划算的~"),
            ("可以送货上门吗？", "我们发快递哦，一般都送到~"),
        ]
        
        for question, expected_reply in rejection_cases:
            prompts.append({
                "type": "rejection",
                "question": question,
                "expected": expected_reply,
            })
        
        return prompts
    
    async def generate_training_sample(self, prompt_data: Dict) -> Dict:
        """生成单个训练样本"""
        question = prompt_data["question"]
        context = prompt_data.get("context", "")
        
        # 构建 GLM-5 的生成提示
        gen_prompt = f"""请作为一个电商客服，用简短自然的方式（30字以内，偶尔用emoji）回答以下问题。

问题：{question}

{f'背景信息：{context}' if context else ''}

请直接给出回复："""

        response = await self.generate_with_glm(gen_prompt)
        
        return {
            "instruction": INSTRUCTION_TEMPLATE.format(shop_name="店铺"),
            "input": f"【用户问题】\n{question}\n\n{f'【背景信息】\n{context}' if context else ''}",
            "output": response,
            "metadata": {
                "type": prompt_data["type"],
                "question": question,
            }
        }
    
    async def run_generation(self):
        """运行完整的生成流程"""
        logger.info("开始生成训练数据...")
        
        # 1. 模拟产品数据（实际应从数据库读取）
        mock_products = [
            {"name": "氨基酸洗面奶", "price": 89, "ingredients": "氨基酸表活、神经酰胺"},
            {"name": "保湿面霜", "price": 79, "ingredients": "玻尿酸、角鲨烷"},
            {"name": "爽肤水", "price": 59, "ingredients": "金缕梅、洋甘菊"},
        ]
        
        all_samples = []
        
        # 2. 生成各类提示词
        product_prompts = self.generate_product_qa_prompts(mock_products)
        cs_prompts = self.generate_customer_service_prompts()
        multi_turn_prompts = self.generate_multi_turn_prompts()
        tool_prompts = self.generate_tool_calling_prompts()
        rejection_prompts = self.generate_rejection_prompts()
        
        all_prompts = (
            product_prompts[:self.config.product_knowledge_target] +
            cs_prompts[:self.config.customer_service_target] +
            multi_turn_prompts[:self.config.multi_turn_target] +
            tool_prompts[:self.config.tool_calling_target] +
            rejection_prompts[:self.config.rejection_target]
        )
        
        logger.info(f"共生成 {len(all_prompts)} 个提示词")
        
        # 3. 批量生成回复
        for i, prompt in enumerate(all_prompts):
            sample = await self.generate_training_sample(prompt)
            all_samples.append(sample)
            
            if (i + 1) % 100 == 0:
                logger.info(f"已生成 {i + 1}/{len(all_prompts)} 条数据")
        
        # 4. 保存原始数据
        output_file = self.output_dir / "raw_data.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(all_samples, f, ensure_ascii=False, indent=2)
        
        logger.info(f"原始数据已保存到 {output_file}")
        logger.info(f"总计生成 {len(all_samples)} 条数据")
        
        return all_samples


async def main():
    """主函数"""
    generator = DataGenerator()
    await generator.run_generation()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Test data generation script**

```bash
cd E:/develop/customer-agent
python finetune/scripts/generate_data.py
```

Expected: Script runs and generates `finetune/data/raw/raw_data.json`

- [ ] **Step 4: Commit**

```bash
cd E:/develop/customer-agent
git add finetune/
git commit -m "feat: add training data generation script"
```

---

### Task 1.2: Create Data Filtering Script

**Files:**
- Create: `E:/develop/customer-agent/finetune/scripts/filter_data.py`

- [ ] **Step 1: Create filtering script**

Create file `E:/develop/customer-agent/finetune/scripts/filter_data.py`:

```python
"""
数据筛选脚本

对原始生成的数据进行自动筛选：
1. 去重
2. 格式校验
3. 长度过滤
4. 质量打分
"""
import json
import re
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass

from utils.logger_loguru import get_logger

logger = get_logger("DataFilter")


@dataclass
class FilterConfig:
    """筛选配置"""
    input_file: Path = Path(__file__).parent.parent / "data" / "raw" / "raw_data.json"
    output_file: Path = Path(__file__).parent.parent / "data" / "filtered" / "filtered_data.json"
    
    # 长度限制
    min_output_length: int = 5
    max_output_length: int = 50
    
    # Emoji 限制
    max_emoji_count: int = 3
    
    # 去重相似度阈值（简单实现）
    duplicate_threshold: int = 10  # 字符差


class DataFilter:
    """数据筛选器"""
    
    def __init__(self, config: FilterConfig = None):
        self.config = config or FilterConfig()
        self.stats = {
            "total": 0,
            "duplicate": 0,
            "too_short": 0,
            "too_long": 0,
            "too_many_emoji": 0,
            "invalid_format": 0,
            "passed": 0,
        }
    
    def load_data(self) -> List[Dict]:
        """加载原始数据"""
        with open(self.config.input_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def count_emojis(self, text: str) -> int:
        """统计 emoji 数量"""
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE,
        )
        return len(emoji_pattern.findall(text))
    
    def is_duplicate(self, sample: Dict, seen_outputs: List[str]) -> bool:
        """检查是否重复"""
        output = sample.get("output", "")
        for seen in seen_outputs:
            if abs(len(output) - len(seen)) < self.config.duplicate_threshold:
                if output == seen or self._similar(output, seen):
                    return True
        return False
    
    def _similar(self, text1: str, text2: str) -> bool:
        """简单的相似度判断"""
        # 如果前 10 个字符相同，认为相似
        return text1[:10] == text2[:10]
    
    def validate_format(self, sample: Dict) -> bool:
        """验证数据格式"""
        required_fields = ["instruction", "input", "output"]
        return all(field in sample for field in required_fields)
    
    def filter_sample(self, sample: Dict, seen_outputs: List[str]) -> tuple:
        """
        筛选单个样本
        
        Returns:
            (passed: bool, reason: str)
        """
        # 1. 格式校验
        if not self.validate_format(sample):
            return False, "invalid_format"
        
        output = sample.get("output", "")
        
        # 2. 长度检查
        if len(output) < self.config.min_output_length:
            return False, "too_short"
        
        if len(output) > self.config.max_output_length:
            return False, "too_long"
        
        # 3. Emoji 检查
        if self.count_emojis(output) > self.config.max_emoji_count:
            return False, "too_many_emoji"
        
        # 4. 重复检查
        if self.is_duplicate(sample, seen_outputs):
            return False, "duplicate"
        
        return True, "passed"
    
    def run(self) -> List[Dict]:
        """运行筛选"""
        logger.info("开始数据筛选...")
        
        raw_data = self.load_data()
        self.stats["total"] = len(raw_data)
        
        filtered_data = []
        seen_outputs = []
        
        for sample in raw_data:
            passed, reason = self.filter_sample(sample, seen_outputs)
            
            if passed:
                filtered_data.append(sample)
                seen_outputs.append(sample["output"])
                self.stats["passed"] += 1
            else:
                self.stats[reason] += 1
        
        # 保存筛选结果
        self.config.output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config.output_file, "w", encoding="utf-8") as f:
            json.dump(filtered_data, f, ensure_ascii=False, indent=2)
        
        # 打印统计
        logger.info("筛选统计:")
        for key, value in self.stats.items():
            logger.info(f"  {key}: {value}")
        
        logger.info(f"筛选完成，保留 {len(filtered_data)} 条数据")
        logger.info(f"输出文件: {self.config.output_file}")
        
        return filtered_data


def main():
    """主函数"""
    filter_tool = DataFilter()
    filter_tool.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test filtering script**

```bash
cd E:/develop/customer-agent
python finetune/scripts/filter_data.py
```

Expected: Script runs and outputs statistics

- [ ] **Step 3: Commit**

```bash
cd E:/develop/customer-agent
git add finetune/scripts/filter_data.py
git commit -m "feat: add data filtering script"
```

---

### Task 1.3: Create Format Conversion Script

**Files:**
- Create: `E:/develop/customer-agent/finetune/scripts/convert_to_alpaca.py`

- [ ] **Step 1: Create conversion script**

Create file `E:/develop/customer-agent/finetune/scripts/convert_to_alpaca.py`:

```python
"""
数据格式转换脚本

将筛选后的数据转换为 Alpaca 训练格式，并划分训练/验证/测试集。
"""
import json
import random
from pathlib import Path
from typing import List, Dict

from utils.logger_loguru import get_logger

logger = get_logger("DataConverter")


class AlpacaConverter:
    """Alpaca 格式转换器"""
    
    def __init__(
        self,
        input_file: Path = None,
        output_dir: Path = None,
        train_ratio: float = 0.8,
        val_ratio: float = 0.1,
        test_ratio: float = 0.1,
    ):
        self.input_file = input_file or Path(__file__).parent.parent / "data" / "filtered" / "filtered_data.json"
        self.output_dir = output_dir or Path(__file__).parent.parent / "data" / "train"
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio
    
    def load_data(self) -> List[Dict]:
        """加载筛选后的数据"""
        with open(self.input_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def convert_sample(self, sample: Dict) -> Dict:
        """转换单个样本为 Alpaca 格式"""
        # Alpaca 标准格式
        return {
            "instruction": sample["instruction"],
            "input": sample["input"],
            "output": sample["output"],
        }
    
    def split_data(self, data: List[Dict]) -> tuple:
        """划分数据集"""
        random.shuffle(data)
        
        total = len(data)
        train_end = int(total * self.train_ratio)
        val_end = train_end + int(total * self.val_ratio)
        
        train_data = data[:train_end]
        val_data = data[train_end:val_end]
        test_data = data[val_end:]
        
        return train_data, val_data, test_data
    
    def save_dataset(self, data: List[Dict], filename: str):
        """保存数据集"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_file = self.output_dir / filename
        
        with open(output_file, "w", encoding="utf-8") as f:
            # LLaMA-Factory 格式：每行一个 JSON 对象
            for sample in data:
                f.write(json.dumps(sample, ensure_ascii=False) + "\n")
        
        logger.info(f"保存 {len(data)} 条数据到 {output_file}")
    
    def run(self):
        """运行转换"""
        logger.info("开始数据格式转换...")
        
        # 加载数据
        data = self.load_data()
        logger.info(f"加载 {len(data)} 条数据")
        
        # 转换格式
        converted = [self.convert_sample(s) for s in data]
        
        # 划分数据集
        train, val, test = self.split_data(converted)
        
        # 保存
        self.save_dataset(train, "train.json")
        self.save_dataset(val, "val.json")
        self.save_dataset(test, "test.json")
        
        logger.info("转换完成!")
        logger.info(f"  训练集: {len(train)} 条")
        logger.info(f"  验证集: {len(val)} 条")
        logger.info(f"  测试集: {len(test)} 条")


def main():
    converter = AlpacaConverter()
    converter.run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test conversion script**

```bash
cd E:/develop/customer-agent
python finetune/scripts/convert_to_alpaca.py
```

Expected: Creates `train.json`, `val.json`, `test.json` in `finetune/data/train/`

- [ ] **Step 3: Commit**

```bash
cd E:/develop/customer-agent
git add finetune/scripts/convert_to_alpaca.py
git commit -m "feat: add Alpaca format conversion script"
```

---

## Phase 2: Model Fine-tuning (2 days)

### Task 2.1: Create LoRA Configuration

**Files:**
- Create: `E:/develop/customer-agent/finetune/lora_config.yaml`

- [ ] **Step 1: Create LoRA config file**

Create file `E:/develop/customer-agent/finetune/lora_config.yaml`:

```yaml
# LoRA 微调配置
# 基于 Qwen2.5-7B-Instruct

### 模型配置
model_name_or_path: Qwen/Qwen2.5-7B-Instruct
stage: sft
do_train: true
finetuning_type: lora
lora_target: all

### 数据配置
dataset: customer_service
dataset_dir: ./finetune/data/train
template: qwen
cutoff_len: 1024
preprocessing_num_workers: 4

### 输出配置
output_dir: ./finetune/output
logging_steps: 10
save_steps: 500
plot_loss: true
overwrite_output_dir: true

### 训练参数
num_train_epochs: 3
per_device_train_batch_size: 4
gradient_accumulation_steps: 4
learning_rate: 5.0e-5
lr_scheduler_type: cosine
warmup_ratio: 0.1
bf16: true

### LoRA 参数
lora_rank: 8
lora_alpha: 16
lora_dropout: 0.05

### 量化配置（4-bit）
quantization_bit: 4
quantization_method: bitsandbytes

### 验证配置
val_size: 0.1
per_device_eval_batch_size: 4
eval_strategy: steps
eval_steps: 500
```

- [ ] **Step 2: Create dataset info file for LLaMA-Factory**

Create file `E:/develop/customer-agent/finetune/data/dataset_info.json`:

```json
{
  "customer_service": {
    "file_name": "train.json",
    "formatting": "sharegpt",
    "columns": {
      "messages": "conversations"
    }
  }
}
```

- [ ] **Step 3: Create README for fine-tuning**

Create file `E:/develop/customer-agent/finetune/README.md`:

```markdown
# Customer Service Model Fine-tuning

## 环境准备

```bash
# 安装 LLaMA-Factory
pip install llama-factory

# 安装依赖
pip install bitsandbytes accelerate transformers
```

## 数据准备

1. 生成数据：
```bash
python scripts/generate_data.py
```

2. 筛选数据：
```bash
python scripts/filter_data.py
```

3. 转换格式：
```bash
python scripts/convert_to_alpaca.py
```

## 开始训练

```bash
llamafactory-cli train lora_config.yaml
```

## 导出模型

```bash
llamafactory-cli export \
  --model_name_or_path Qwen/Qwen2.5-7B-Instruct \
  --adapter_name_or_path ./output \
  --export_dir ./merged_model \
  --export_size 2
```

## 硬件要求

- GPU: RTX 4060 8GB 或更高
- RAM: 16GB+
- Disk: 20GB+ 可用空间
```

- [ ] **Step 4: Commit**

```bash
cd E:/develop/customer-agent
git add finetune/
git commit -m "feat: add LoRA fine-tuning configuration"
```

---

## Phase 3: vLLM Integration (2 days)

### Task 3.1: Create Local LLM Client

**Files:**
- Create: `E:/develop/customer-agent/Agent/CustomerAgent/custom/local_llm_client.py`

- [ ] **Step 1: Create local LLM client**

Create file `E:/develop/customer-agent/Agent/CustomerAgent/custom/local_llm_client.py`:

```python
"""
本地 LLM 客户端

通过 vLLM 提供 OpenAI 兼容的本地模型 API。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import httpx

from utils.logger_loguru import get_logger

logger = get_logger("LocalLLMClient")


@dataclass
class LocalLLMConfig:
    """本地 LLM 配置"""
    enabled: bool = True
    base_url: str = "http://localhost:8000/v1"
    model_name: str = "customer-service"
    max_tokens: int = 50
    temperature: float = 0.7
    timeout: float = 30.0


@dataclass
class LocalLLMResponse:
    """本地 LLM 响应"""
    content: str
    success: bool
    error: Optional[str] = None


class LocalLLMClient:
    """本地 LLM 客户端（vLLM OpenAI 兼容）"""
    
    def __init__(self, config: LocalLLMConfig = None):
        self.config = config or LocalLLMConfig()
        self._client: Optional[httpx.AsyncClient] = None
    
    async def initialize(self) -> bool:
        """初始化客户端"""
        if not self.config.enabled:
            logger.info("本地模型未启用")
            return False
        
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )
        
        # 检查服务是否可用
        try:
            response = await self._client.get("/models")
            if response.status_code == 200:
                logger.info(f"本地 LLM 服务可用: {self.config.base_url}")
                return True
        except Exception as e:
            logger.warning(f"本地 LLM 服务不可用: {e}")
            return False
        
        return False
    
    async def chat(
        self,
        messages: List[Dict[str, Any]],
    ) -> LocalLLMResponse:
        """
        发送聊天请求
        
        Args:
            messages: OpenAI 格式的消息列表
        
        Returns:
            LocalLLMResponse
        """
        if not self._client:
            return LocalLLMResponse(
                content="",
                success=False,
                error="客户端未初始化",
            )
        
        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self.config.model_name,
                    "messages": messages,
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                },
            )
            
            if response.status_code == 200:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                return LocalLLMResponse(content=content, success=True)
            else:
                return LocalLLMResponse(
                    content="",
                    success=False,
                    error=f"API 错误: {response.status_code}",
                )
        
        except Exception as e:
            logger.error(f"本地 LLM 调用失败: {e}")
            return LocalLLMResponse(
                content="",
                success=False,
                error=str(e),
            )
    
    async def close(self):
        """关闭客户端"""
        if self._client:
            await self._client.aclose()
```

- [ ] **Step 2: Commit**

```bash
cd E:/develop/customer-agent
git add Agent/CustomerAgent/custom/local_llm_client.py
git commit -m "feat: add local LLM client for vLLM"
```

---

### Task 3.2: Update Agent Config

**Files:**
- Modify: `E:/develop/customer-agent/Agent/CustomerAgent/custom/agent_config.py`

- [ ] **Step 1: Add local model config to AgentConfig**

Add to `agent_config.py` after the existing imports:

```python
from dataclasses import dataclass, field
from typing import List, Optional

# Add new config dataclass after DEFAULT_TEMPERATURE

@dataclass
class LocalModelConfig:
    """本地模型配置"""
    enabled: bool = False
    base_url: str = "http://localhost:8000/v1"
    model_name: str = "customer-service"
    max_tokens: int = 50
    temperature: float = 0.7
    local_max_length: int = 15
    fallback_on_error: bool = True


@dataclass
class AgentConfig:
    """Agent 配置数据类"""
    db_path: str = field(default_factory=lambda: get_config("db_path", DEFAULT_DB_PATH))
    token_window: int = DEFAULT_TOKEN_WINDOW
    compress_ratio: float = DEFAULT_COMPRESS_RATIO
    retain_count: int = DEFAULT_RETAIN_COUNT
    max_loops: int = DEFAULT_MAX_LOOPS
    temperature: float = DEFAULT_TEMPERATURE

    # LLM 配置
    model_name: str = field(default_factory=lambda: get_config("llm.model_name", "gpt-3.5-turbo"))
    api_key: str = field(default_factory=lambda: get_config("llm.api_key", ""))
    api_base: str = field(default_factory=lambda: get_config("llm.api_base", ""))

    # Prompt 配置
    instructions: List[str] = field(default_factory=lambda: get_config("prompt.instructions", []))
    
    # 本地模型配置
    local_model: LocalModelConfig = field(default_factory=LocalModelConfig)

    @classmethod
    def load_from_config(cls) -> "AgentConfig":
        """从配置文件加载配置"""
        config = cls()
        
        # 加载本地模型配置
        local_model_cfg = get_config("local_model", {})
        if local_model_cfg:
            config.local_model = LocalModelConfig(
                enabled=local_model_cfg.get("enabled", False),
                base_url=local_model_cfg.get("base_url", "http://localhost:8000/v1"),
                model_name=local_model_cfg.get("model_name", "customer-service"),
                max_tokens=local_model_cfg.get("max_tokens", 50),
                temperature=local_model_cfg.get("temperature", 0.7),
                local_max_length=get_config("routing.local_max_length", 15),
                fallback_on_error=get_config("routing.fallback_on_error", True),
            )
        
        logger.debug("Agent 配置加载完成")
        return config

    def validate(self) -> bool:
        """验证配置有效性"""
        if not self.api_key:
            logger.error("LLM API 密钥未配置")
            return False
        return True
```

- [ ] **Step 2: Commit**

```bash
cd E:/develop/customer-agent
git add Agent/CustomerAgent/custom/agent_config.py
git commit -m "feat: add local model config to AgentConfig"
```

---

### Task 3.3: Add Routing Logic to CustomerAgent

**Files:**
- Modify: `E:/develop/customer-agent/Agent/CustomerAgent/custom/customer_agent.py`

- [ ] **Step 1: Update imports and add local client**

Add imports and local client initialization in `customer_agent.py`:

```python
# Add to existing imports
from Agent.CustomerAgent.custom.local_llm_client import LocalLLMClient, LocalLLMConfig

# In __init__ method, add:
self._local_llm_client: Optional[LocalLLMClient] = None
```

- [ ] **Step 2: Add routing method**

Add routing method to `CustomerAgent` class:

```python
def _should_use_local_model(self, query: str) -> bool:
    """
    判断是否使用本地模型
    
    规则：查询长度 <= 配置的阈值（默认 15 字符）
    """
    if not self._config.local_model.enabled:
        return False
    
    return len(query) <= self._config.local_model.local_max_length
```

- [ ] **Step 3: Update initialize_async**

Update `initialize_async` method to initialize local client:

```python
async def initialize_async(self) -> bool:
    """异步初始化 Agent"""
    if self._is_initialized:
        return True

    try:
        # ... existing initialization code ...
        
        # 8. 初始化本地 LLM 客户端
        if self._config.local_model.enabled:
            self._local_llm_client = LocalLLMClient(self._config.local_model)
            local_ready = await self._local_llm_client.initialize()
            if local_ready:
                logger.info("本地 LLM 客户端初始化成功")
            else:
                logger.warning("本地 LLM 客户端初始化失败，将使用远程 API")
        else:
            self._local_llm_client = None

        self._is_initialized = True
        logger.info(f"CustomerAgent 初始化成功: model={self._config.model_name}")
        return True

    except Exception as e:
        logger.error(f"CustomerAgent 初始化失败: {e}")
        return False
```

- [ ] **Step 4: Add local reply method**

Add local reply method to `CustomerAgent` class:

```python
async def _local_reply(self, query: str, context: Context) -> Reply:
    """使用本地模型回复"""
    if not self._local_llm_client:
        return await self._remote_reply(query, context)
    
    # 构建简单消息
    messages = [
        {"role": "system", "content": "你是电商客服。请简短回复（30字以内），像真人聊天，偶尔用emoji。"},
        {"role": "user", "content": query},
    ]
    
    response = await self._local_llm_client.chat(messages)
    
    if response.success:
        return Reply(ReplyType.TEXT, response.content)
    else:
        # 本地模型失败，回退到远程
        logger.warning(f"本地模型失败，回退到远程: {response.error}")
        if self._config.local_model.fallback_on_error:
            return await self._remote_reply(query, context)
        else:
            return Reply(ReplyType.TEXT, "抱歉，我现在无法回复，请稍后再试。")
```

- [ ] **Step 5: Update async_reply with routing**

Update `async_reply` method:

```python
async def async_reply(self, query: str, context: Context = None) -> Reply:
    """异步回复接口"""
    # 延迟初始化
    if not self._is_initialized:
        if not await self.initialize_async():
            return Reply(ReplyType.TEXT, "AI客服初始化失败，请检查配置。")
    
    # 路由判断：短问题本地，长问题远程
    if self._should_use_local_model(query):
        logger.debug(f"使用本地模型处理短问题: {query[:20]}...")
        return await self._local_reply(query, context)
    else:
        logger.debug(f"使用远程模型处理长问题: {query[:20]}...")
        return await self._remote_reply(query, context)
```

- [ ] **Step 6: Rename existing reply logic**

Rename existing `async_reply` body to `_remote_reply`:

```python
async def _remote_reply(self, query: str, context: Context = None) -> Reply:
    """使用远程 API 回复（原有逻辑）"""
    # ... existing async_reply logic ...
```

- [ ] **Step 7: Commit**

```bash
cd E:/develop/customer-agent
git add Agent/CustomerAgent/custom/customer_agent.py
git commit -m "feat: add routing logic for local/remote model selection"
```

---

### Task 3.4: Update Config File

**Files:**
- Modify: `E:/develop/customer-agent/config.json`

- [ ] **Step 1: Add local_model config section**

Add to `config.json`:

```json
{
    "business_hours": {
        "start": "08:00",
        "end": "23:00"
    },
    "llm": {
        "model_name": "GLM-5",
        "api_key": "sk-255ffd31e6932a83e94e962770a98292d5d1b074349d4d64bbcf7944b99eb4e8",
        "api_base": "http://67.230.168.254:8080"
    },
    "local_model": {
        "enabled": false,
        "base_url": "http://localhost:8000/v1",
        "model_name": "customer-service",
        "max_tokens": 50,
        "temperature": 0.7
    },
    "routing": {
        "local_max_length": 15,
        "fallback_on_error": true
    },
    "prompt": {
        "instructions": [
            "1. 请用中文回复客户问题，回复简洁自然，像真人聊天",
            "2. 当用户询问特定商品的信息、成分、使用方法、价格、规格等问题时，请优先使用 get_product_knowledge 工具获取商品详细知识，必须提供 goods_id（商品ID）和 shop_id（店铺ID）",
            "3. 当用户询问售后政策、物流信息、退换货规则、常见问题解答等非产品特定问题时，请使用 search_customer_service_knowledge 工具搜索客服知识，必须提供 query（搜索关键词）和 shop_id（店铺ID）",
            "4. 如果知识库中有相关信息，请根据知识库内容回答用户问题",
            "5. 如果知识库中没有相关信息，再根据已有知识回答或建议用户联系人工客服",
            "6. 回复控制在30字以内，少用emoji，避免过度热情和机械口吻"
        ]
    },
    "db_path": "./temp/channel_shop.db"
}
```

- [ ] **Step 2: Commit**

```bash
cd E:/develop/customer-agent
git add config.json
git commit -m "feat: add local_model config section"
```

---

## Phase 4: Testing (2 days)

### Task 4.1: Create Test Script

**Files:**
- Create: `E:/develop/customer-agent/finetune/scripts/test_local_model.py`

- [ ] **Step 1: Create test script**

Create file `E:/develop/customer-agent/finetune/scripts/test_local_model.py`:

```python
"""
本地模型测试脚本

测试本地模型的路由和回复质量。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from Agent.CustomerAgent.custom.customer_agent import CustomerAgent
from bridge.context import Context, ContextType, ChannelType
from bridge.reply import ReplyType


class MockKwargs:
    """模拟 Context.kwargs"""
    def __init__(self):
        self.user_id = "test_user_001"
        self.shop_id = 12345
        self.shop_name = "测试店铺"
        self.from_uid = "test_from_uid"


async def test_routing():
    """测试路由逻辑"""
    print("=" * 50)
    print("测试路由逻辑")
    print("=" * 50)
    
    agent = CustomerAgent()
    await agent.initialize_async()
    
    test_cases = [
        ("多少钱", True, "短问题应使用本地模型"),
        ("有货吗", True, "短问题应使用本地模型"),
        ("能退吗", True, "短问题应使用本地模型"),
        ("这个洗面奶适合敏感肌吗？油皮可以用吗？", False, "长问题应使用远程模型"),
        ("我上周买的面霜，用了之后过敏了，想退货怎么处理？", False, "长问题应使用远程模型"),
    ]
    
    for query, expected_local, description in test_cases:
        should_use_local = agent._should_use_local_model(query)
        status = "✓" if should_use_local == expected_local else "✗"
        print(f"{status} {description}")
        print(f"  查询: {query}")
        print(f"  长度: {len(query)}")
        print(f"  预期: {'本地' if expected_local else '远程'}")
        print(f"  实际: {'本地' if should_use_local else '远程'}")
        print()


async def test_local_reply():
    """测试本地模型回复"""
    print("=" * 50)
    print("测试本地模型回复")
    print("=" * 50)
    
    agent = CustomerAgent()
    await agent.initialize_async()
    
    if not agent._local_llm_client:
        print("本地模型未启用，跳过测试")
        return
    
    context = Context(ContextType.TEXT)
    context.channel_type = ChannelType.PINDUODUO
    context.kwargs = MockKwargs()
    
    test_queries = [
        "多少钱",
        "有货吗",
        "什么时候发货",
    ]
    
    for query in test_queries:
        print(f"查询: {query}")
        reply = await agent.async_reply(query, context)
        print(f"回复: {reply.content}")
        print()


async def main():
    """主函数"""
    await test_routing()
    await test_local_reply()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run test**

```bash
cd E:/develop/customer-agent
python finetune/scripts/test_local_model.py
```

Expected: Tests pass with routing logic verified

- [ ] **Step 3: Commit**

```bash
cd E:/develop/customer-agent
git add finetune/scripts/test_local_model.py
git commit -m "feat: add local model test script"
```

---

### Task 4.2: Create Benchmark Script

**Files:**
- Create: `E:/develop/customer-agent/finetune/scripts/benchmark.py`

- [ ] **Step 1: Create benchmark script**

Create file `E:/develop/customer-agent/finetune/scripts/benchmark.py`:

```python
"""
性能基准测试

对比本地模型和远程 API 的响应时间和成本。
"""
import asyncio
import time
import json
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from Agent.CustomerAgent.custom.customer_agent import CustomerAgent
from bridge.context import Context, ContextType, ChannelType


@dataclass
class BenchmarkResult:
    """基准测试结果"""
    query: str
    model_type: str  # local / remote
    response_time: float
    response_length: int
    success: bool


class Benchmark:
    """基准测试"""
    
    def __init__(self, test_queries: List[str]):
        self.test_queries = test_queries
        self.results: List[BenchmarkResult] = []
    
    async def run_single(self, agent: CustomerAgent, query: str, use_local: bool) -> BenchmarkResult:
        """运行单个测试"""
        start_time = time.time()
        
        # 强制使用指定模型
        if use_local:
            agent._config.local_model.enabled = True
        else:
            agent._config.local_model.enabled = False
        
        try:
            reply = await agent.async_reply(query)
            response_time = time.time() - start_time
            
            return BenchmarkResult(
                query=query,
                model_type="local" if use_local else "remote",
                response_time=response_time,
                response_length=len(reply.content),
                success=True,
            )
        except Exception as e:
            return BenchmarkResult(
                query=query,
                model_type="local" if use_local else "remote",
                response_time=time.time() - start_time,
                response_length=0,
                success=False,
            )
    
    async def run(self):
        """运行完整基准测试"""
        agent = CustomerAgent()
        await agent.initialize_async()
        
        print("开始基准测试...")
        print(f"测试查询数: {len(self.test_queries)}")
        
        for query in self.test_queries:
            # 测试本地模型
            if len(query) <= 15:
                result = await self.run_single(agent, query, use_local=True)
                self.results.append(result)
            
            # 测试远程模型
            result = await self.run_single(agent, query, use_local=False)
            self.results.append(result)
        
        self.print_report()
    
    def print_report(self):
        """打印报告"""
        print("\n" + "=" * 60)
        print("基准测试报告")
        print("=" * 60)
        
        local_results = [r for r in self.results if r.model_type == "local"]
        remote_results = [r for r in self.results if r.model_type == "remote"]
        
        # 本地模型统计
        if local_results:
            avg_time = sum(r.response_time for r in local_results) / len(local_results)
            success_rate = sum(1 for r in local_results if r.success) / len(local_results) * 100
            print(f"\n本地模型:")
            print(f"  平均响应时间: {avg_time:.2f}s")
            print(f"  成功率: {success_rate:.1f}%")
        
        # 远程模型统计
        if remote_results:
            avg_time = sum(r.response_time for r in remote_results) / len(remote_results)
            success_rate = sum(1 for r in remote_results if r.success) / len(remote_results) * 100
            print(f"\n远程模型:")
            print(f"  平均响应时间: {avg_time:.2f}s")
            print(f"  成功率: {success_rate:.1f}%")
        
        # 成本节省估算
        if local_results:
            local_count = len(local_results)
            total_count = len(self.results)
            savings = local_count / total_count * 100
            print(f"\nAPI 调用节省: {savings:.1f}%")


async def main():
    """主函数"""
    test_queries = [
        "多少钱",
        "有货吗",
        "什么时候发货",
        "能退吗",
        "这个洗面奶适合敏感肌吗？",
        "我买的面霜过敏了想退货",
    ]
    
    benchmark = Benchmark(test_queries)
    await benchmark.run()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Commit**

```bash
cd E:/develop/customer-agent
git add finetune/scripts/benchmark.py
git commit -m "feat: add benchmark script"
```

---

## Summary

### Total Tasks: 13

**Phase 1: Data Generation (4 days)**
- Task 1.1: Data generation script
- Task 1.2: Data filtering script
- Task 1.3: Format conversion script

**Phase 2: Model Fine-tuning (2 days)**
- Task 2.1: LoRA configuration

**Phase 3: vLLM Integration (2 days)**
- Task 3.1: Local LLM client
- Task 3.2: Agent config update
- Task 3.3: Routing logic
- Task 3.4: Config file update

**Phase 4: Testing (2 days)**
- Task 4.1: Test script
- Task 4.2: Benchmark script

### Expected Outcomes

1. **Data Pipeline**: Automated generation → filtering → conversion workflow
2. **Model**: Fine-tuned Qwen2.5-7B with LoRA for customer service
3. **Routing**: Length-based router (≤15 chars → local, >15 → remote)
4. **Cost Savings**: 60%+ API call reduction
5. **Quality**: Natural, short responses (≤30 chars) with minimal emojis
