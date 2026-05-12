
# Claude Code Task 001B - SDD 文档审查修正

只修改 docs/sdd/ 文档，不改业务代码。

审查意见：
1. SKU 原文保持规则写错了。真实原则是保持 product_json / MySQL attribute_json 里的原文。不能固定认为 `1瓶` 正确、`一瓶` 错误。当前真实商品 `946901558797` 的可选规格是 `一瓶、2瓶、3瓶`，所以回复 `一瓶` 正确，回复 `1瓶` 反而可能是改写。修改所有固定 `1瓶` 示例，改为“以商品 JSON 原文为准”。示例使用 `sku_options: ["一瓶", "2瓶", "3瓶"]`。Validator 伪代码不要写死 `sku_rewrite_map = {"1瓶": ...}`，改为配置化同义改写风险说明。
2. Prompt JSON 标准格式缺少 `price` 字段。加入 `price`，用于价格问答，但不得推断优惠。
3. 商品定位主来源应是平台当前咨询商品/会话锁定 goods_id，关键词/链接解析只是兜底。修正 Product Context / product_locator 描述。
4. 目前真实 Prompt-only 实测只对 `946901558797` 做过：单轮 10/12，多轮 5/6。不能写四款商品“单轮已通过”。四款商品待全量回归；946 是单商品基线，其他三款待测。
5. `04_eval_plan.md` 样例测试数据错误：946 的 usage_duration 是 `一瓶可用一至两个月`，所以“一瓶能用多久？”是 direct_answer，不是 uncertain_answer。946 的 suitable_age 是 `12岁以上能使用`，孕妇问题才是 uncertain/risk。
6. 人工/售后/图片应在 L1 Gatekeeper 前置拦截。Response Validator 只能作为最后一道防线。
7. 成功指标标明“初始目标”，不要暗示四款已达成。

请直接修改 docs/sdd/ 下相关文档并输出修改摘要。不要提问。
