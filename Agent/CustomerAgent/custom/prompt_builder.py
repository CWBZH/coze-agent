"""
V3.0 Prompt Builder - Builds product JSON and chat messages for prompt-only experiment.
"""
import json
from typing import Any


class PromptBuilder:
    """
    Builds product JSON and chat messages for V3.0 prompt-only experimental pipeline.

    This class is responsible for:
    1. Normalizing product data with consistent field ordering
    2. Building system prompts with product JSON injection
    3. Generating OpenAI/Ollama-compatible message arrays
    """

    # Field order must match docs/sdd/02_prompt_contract.md with price added
    PRODUCT_FIELDS = [
        "goods_id", "goods_name", "category", "brand", "price",
        "sku_summary", "sku_options", "fragrance", "effect",
        "ingredients", "usage_method", "usage_duration",
        "suitable_age", "skin_type", "foaming", "shelf_life",
        "warnings", "accessories"
    ]

    # List fields that should return [] when None
    LIST_FIELDS = ["sku_options", "effect", "warnings", "accessories"]

    def build_product_json(self, product: dict) -> dict:
        """
        Normalize product data with field ordering and empty field handling.

        Args:
            product: Raw product dictionary from database or test data

        Returns:
            Normalized product JSON with all 18 fields in correct order.
            Empty fields are converted to empty strings (not null/missing).
            List fields (sku_options, effect, warnings, accessories) return [] for None.
        """
        result = {}
        for field in self.PRODUCT_FIELDS:
            value = product.get(field)

            # Handle empty/None values
            if value is None:
                if field in self.LIST_FIELDS:
                    result[field] = []
                else:
                    result[field] = ""
            else:
                result[field] = value

        return result

    def build_messages(
        self,
        product_json: dict,
        user_query: str,
        history: list | None = None
    ) -> list[dict]:
        """
        Build OpenAI/Ollama-compatible message array.

        Args:
            product_json: Normalized product JSON from build_product_json()
            user_query: Current user question
            history: Optional conversation history (list of {role, content} dicts)

        Returns:
            List of message dicts with role and content keys.
            Format: [system_message, *history_messages, user_message]
        """
        system_prompt = self._build_system_prompt(product_json)

        messages = [{"role": "system", "content": system_prompt}]

        # Insert history if provided
        if history:
            messages.extend(history)

        # Add current user query
        messages.append({"role": "user", "content": user_query})

        return messages

    def _build_system_prompt(self, product_json: dict) -> str:
        """
        Build system prompt with product JSON injection.

        Follows docs/sdd/02_prompt_contract.md specifications:
        - Role definition
        - Product JSON as single source of truth
        - Answer rules (brevity, naturalness)
        - Field mapping rules
        - SKU preservation rules
        - Forbidden behaviors
        - Empty field fallback
        """
        # Format product JSON for injection
        product_json_str = self._format_product_json(product_json)

        # Build SKU examples from actual product data
        sku_examples = self._build_sku_examples(product_json.get("sku_options", []))

        system_prompt = f"""你是客服助手。商品信息如下：

商品信息：
{product_json_str}

回答规则：
1. 商品JSON是唯一事实来源，不能编造信息
2. 回复简短自然，不超过50字
3. 必须按JSON原文回复SKU，不能同义改写（例如：如果JSON中是"一瓶"，不能改写成"1瓶"、"单瓶"或"一瓶装"）
4. 空字段必须回复"这个信息我不确定，建议您咨询人工客服"
5. 价格只能引用JSON中的price字段，不能推断优惠

字段映射规则：
- 用户问"12岁/几岁/小孩/儿童能用吗"时，如果suitable_age非空，必须引用suitable_age
- 用户问"喷一次/喷一下/一次能管多久/单次持续多久"时，如果usage_method非空，优先引用usage_method
- 用户问"一瓶能用多久/一支能用多久/一瓶能撑多久"时，引用usage_duration
- 用户问孕妇/哺乳期时，除非字段明确写孕妇/哺乳期，否则不要用suitable_age替代

禁止行为：
- 编造不存在的SKU选项
- 改写SKU原文（如"一瓶"改成"1瓶"）
- 从标题推断成分
- 夸大功效
- 承诺医疗效果（如"治疗"、"治愈"、"根治"）
- 推断价格或优惠

{sku_examples}

示例对话：
用户：有什么规格？
助手：{self._get_sku_example_answer(product_json.get('sku_options', []))}

用户：保质期多久？
助手：这个信息我不确定，建议您咨询人工客服。

用户：能治狐臭吗？
助手：这是普通日化产品，不具备治疗功能。建议咨询医生。

用户：12岁可以用吗？
助手：{self._get_age_example_answer(product_json.get('suitable_age', ''))}

用户：喷一次能管多久？
助手：{self._get_usage_example_answer(product_json.get('usage_method', ''), product_json.get('usage_duration', ''))}"""

        return system_prompt

    def _format_product_json(self, product_json: dict) -> str:
        """Format product JSON for readable injection into prompt."""
        lines = []
        for field in self.PRODUCT_FIELDS:
            value = product_json.get(field, "")
            if isinstance(value, list):
                value_str = json.dumps(value, ensure_ascii=False)
            else:
                value_str = str(value) if value else ""
            lines.append(f"{field}: {value_str}")
        return "\n".join(lines)

    def _build_sku_examples(self, sku_options: list) -> str:
        """
        Build SKU preservation examples based on actual product data.

        Shows bidirectional preservation: neither format is canonical.
        """
        if not sku_options:
            return "SKU原文规则：必须按JSON原文回复，不能改写"

        # Find examples with Chinese and Arabic numerals
        examples = []
        for sku in sku_options:
            if "一" in sku or "1" in sku or "2" in sku or "3" in sku:
                examples.append(sku)

        if not examples:
            return "SKU原文规则：必须按JSON原文回复，不能改写"

        # Build example table showing bidirectional preservation
        example_sku = examples[0]
        rules_text = f"""SKU原文规则：
- 如果JSON是"{example_sku}"，必须回复"{example_sku}"，不能改写
- 示例：用户问"有什么规格？"时，回答"{example_sku}"等实际选项"""

        return rules_text

    def _get_sku_example_answer(self, sku_options: list) -> str:
        """Generate example answer for SKU query based on actual product data."""
        if not sku_options:
            return "请咨询人工客服了解详细规格"

        # Return first 2-3 SKU options
        display_options = sku_options[:3]
        return "、".join(display_options)

    def _get_age_example_answer(self, suitable_age: str) -> str:
        """Generate example answer for age query based on suitable_age field."""
        if not suitable_age or suitable_age == "":
            return "这个信息我不确定，建议您咨询人工客服"
        return suitable_age

    def _get_usage_example_answer(self, usage_method: str, usage_duration: str) -> str:
        """Generate example answer for usage query, prioritizing usage_method."""
        if usage_method and usage_method != "":
            return usage_method
        if usage_duration and usage_duration != "":
            return usage_duration
        return "这个信息我不确定，建议您咨询人工客服"
