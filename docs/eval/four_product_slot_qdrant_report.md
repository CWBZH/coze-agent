# 四款商品 Slot FAQ 与 Qdrant 检索报告

## 范围
- `946901558797` 净爽止汗喷雾保湿除臭净味爽身清新舒爽温和腋下止汗香体20ml
- `943269377110` 脖子身体懒人素颜霜提亮全身持久防水润肤不脱防蹭上衣假白学生
- `942041658034` 【好物爆款】颜里烟酰胺身体素颜霜免卸防水防汗美白遮瑕持久男女
- `941078657140` 60张眼唇卸妆巾温和面部刺激深层清洁便携一次性湿巾孕妇懒人抽取

## 文件
- FAQ CSV: `docs/eval/four_product_slot_faq_1000.csv`
- FAQ JSONL: `docs/eval/four_product_slot_faq_1000.jsonl`
- Qdrant Eval CSV: `docs/eval/four_product_qdrant_eval_1000.csv`

## 总体结果
- FAQ 总数: 1000
- Qdrant 实际检索用例: 800，跳过 price/non_product/空字段。
- Top1 内容包含期望字段: 602/800 = 75.25%
- Top1 且 score > 0: 602/800 = 75.25%
- Top1 且 score >= 0.20: 459/800 = 57.38%
- Top1 且 score >= 0.55: 60/800 = 7.50%

## Slot 分布与空字段
| slot | FAQ数 | 空字段数 | Qdrant检索数 | Top1含字段 | score>=0.20 | score>=0.55 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `accessories` | 20 | 20 | 0 | 0 | 0 | 0 |
| `brand` | 55 | 0 | 55 | 0 | 0 | 0 |
| `category` | 40 | 0 | 40 | 0 | 0 | 0 |
| `effect` | 130 | 0 | 130 | 64 | 64 | 24 |
| `foaming` | 25 | 19 | 6 | 0 | 0 | 0 |
| `fragrance` | 70 | 0 | 70 | 70 | 66 | 32 |
| `ingredients` | 65 | 0 | 65 | 65 | 54 | 4 |
| `non_product` | 20 | 20 | 0 | 0 | 0 | 0 |
| `price` | 50 | 0 | 0 | 0 | 0 | 0 |
| `shelf_life` | 30 | 30 | 0 | 0 | 0 | 0 |
| `skin_type` | 80 | 0 | 80 | 49 | 49 | 0 |
| `sku_options` | 120 | 0 | 120 | 120 | 43 | 0 |
| `suitable_age` | 80 | 0 | 80 | 80 | 80 | 0 |
| `usage_duration` | 85 | 0 | 85 | 85 | 66 | 0 |
| `usage_method` | 95 | 26 | 69 | 69 | 37 | 0 |
| `warnings` | 35 | 35 | 0 | 0 | 0 | 0 |

## 已观测风险
- Qdrant 属性片段的相似度分数普遍偏低，很多正确 Top1 在当前业务阈值 `0.55` 下会被过滤。
- `sku_options` 与 `sku_summary` 同属 `sku_spec` 域，可能出现“20ml”与“一瓶/2瓶/3瓶”混排，需要由 Answer 层区分容量与可选 SKU。
- `warnings/shelf_life/foaming/accessories` 多数为空，FAQ 会验证兜底能力；不应让 LLM 编造。
- 卸妆巾商品把 `孕妇` 写入 `suitable_age`，语义上更接近适用人群/注意事项，后续字段体系应拆分。
