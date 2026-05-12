# 商品 Slot 体系设计

## 目标

商品问答链路采用 `intent -> slot -> fact -> answer`：

1. `intent` 只判断业务域：售前、售后、物流、转人工、闲聊。
2. `slot` 判断买家在问当前商品的哪个字段。
3. `fact` 只从 MySQL `ProductKnowledge.attribute_json` 和基础字段读取。
4. `answer` 使用模板或 LLM 润色，但不能编造商品事实。

这套设计替代“二级路由抢控制权”的做法。Slot 不是业务分流，而是商品事实字段解析。

## Slot Taxonomy

| slot_id | 中文含义 | 主字段 | 字段类型 | 说明 |
| --- | --- | --- | --- | --- |
| `brand` | 品牌 | `attribute_json.brand` | string | 品牌、牌子、正品来源类问题 |
| `sku_options` | 可选规格 | `attribute_json.sku_options` | list | 一瓶、2瓶、3瓶、款式、容量选择 |
| `sku_summary` | 默认规格/容量 | `attribute_json.sku_summary` | string | 20ml、90ML、200片等核心规格 |
| `price` | 价格 | `ProductKnowledge.price` | string | 价格区间、多少钱 |
| `category` | 商品类目 | `attribute_json.category` | string | 商品类型、是不是某类产品 |
| `effect` | 功效卖点 | `attribute_json.effect` | list | 止汗、保湿、美白、清洁、留香等 |
| `ingredients` | 成分/材质 | `attribute_json.ingredients` | string | 酒精、香精、材质、成分安全 |
| `usage_method` | 使用方法 | `attribute_json.usage_method` | string | 怎么用、喷哪里、涂哪里、一天几次 |
| `usage_duration` | 使用时长 | `attribute_json.usage_duration` | string | 一瓶用多久、能用几天 |
| `suitable_age` | 适用年龄 | `attribute_json.suitable_age` | string | 几岁、小孩、儿童、年龄 |
| `skin_type` | 适用肤质/肤色 | `attribute_json.skin_type` | string | 黄皮、油皮、干皮、敏感肌 |
| `fragrance` | 香味 | `attribute_json.fragrance` | string | 什么味、香不香、留香 |
| `foaming` | 起泡情况 | `attribute_json.foaming` | string | 泡沫、起泡、绵密 |
| `shelf_life` | 保质期 | `attribute_json.shelf_life` | string | 保质期、过期、能放多久 |
| `warnings` | 注意事项/禁忌 | `attribute_json.warnings` | list | 孕妇、禁忌、注意事项、慎用 |
| `accessories` | 赠品/附属品 | `attribute_json.accessories` | list | 赠品、小样、送什么 |
| `unknown_product_slot` | 商品字段未知 | 无 | none | 商品追问但无法稳定映射字段 |
| `non_product` | 非商品字段 | 无 | none | 物流、售后、支付、转人工、闲聊 |

## 关键边界

- `能用/可以用` 不能单独映射到 `suitable_age`。
- `黄皮/黑皮/白皮/肤色/肤质/油皮/干皮/敏感肌` 优先映射 `skin_type`。
- `孕妇/哺乳期/禁忌/注意事项` 优先映射 `warnings`，字段为空时不能拿 `suitable_age` 代答。
- `几岁/多少岁/儿童/小孩/宝宝/婴儿/青少年` 映射 `suitable_age`。
- `止汗/除臭/保湿/美白/清洁/控油/防水` 映射 `effect`。
- `什么品牌/什么牌子/啥牌子/品牌` 必须映射 `brand`，并保持当前商品上下文。

## 事实读取优先级

```text
当前商品 goods_id
-> attribute_json 精确字段
-> ProductKnowledge 基础字段(price/goods_name)
-> 字段为空统一兜底
-> 必要时 LLM 只做话术润色
```

## 空字段兜底

字段不存在时必须说“页面/商品信息暂未明确标注”，不能用相邻字段硬答。

示例：

- 问：孕妇能用吗？
- `warnings` 为空：
- 答：`商品信息里没有明确标注孕妇/哺乳期适用情况，建议谨慎选择或咨询人工客服确认。`

## 评估指标

| 指标 | 目标 |
| --- | --- |
| slot accuracy | >= 92% |
| product slot false positive | <= 3% |
| field retrieval accuracy | >= 95% |
| empty-field graceful fallback | 100% |
| current product inheritance | >= 98% |

## 数据集字段

| 字段 | 含义 |
| --- | --- |
| `case_id` | 用例 ID |
| `goods_id` | 商品 ID |
| `goods_name` | 商品名 |
| `query` | 买家自然问法 |
| `expected_intent` | 一级意图 |
| `expected_slot` | 期望 slot |
| `expected_fact_field` | 期望读取字段 |
| `field_value` | 当前商品字段值 |
| `answer_policy` | 回复策略 |
| `is_empty_field` | 字段是否为空 |
| `source` | 生成来源 |

