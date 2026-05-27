# T083-F FastGPT Knowledge Base Supplement Plan

Date: 2026-05-20

Scope: phase-one FastGPT dataset supplement plan. This document only defines knowledge items, approved wording, and no-auto-promise boundaries. It does not modify code, database rows, FastGPT workflow, prompts, datasets, or `.env`.

Related documents:

- `docs/acceptance/T083E_WORKFLOW_KB_POLICY_DECISIONS.md`
- `docs/acceptance/T083C_FASTGPT_SYNTHETIC_QA_REPORT.md`
- `docs/acceptance/T083D_FASTGPT_QA_REMEDIATION_MATRIX.md`
- `docs/acceptance/T083B_FASTGPT_KNOWLEDGE_COVERAGE_CHECKLIST.md`
- `docs/acceptance/T081_CUSTOMER_SERVICE_TEST_MATRIX.md`

## 1. Overall Principles

Ownership boundaries:

- Knowledge base owns approved store policies, standard wording, evidence request wording, and no-auto-promise boundaries.
- FastGPT workflow owns intent classification and branch routing.
- Code owns infrastructure fallback and safety guarantees: missing dataset, FastGPT timeout/non-200/empty, unsafe reply, media intercept, SendMessage result, trace logs, and notification isolation.
- Knowledge base must not promise anything that cannot be verified from the message context.
- Knowledge base must not decide specific order logistics status, refund approval, compensation, authenticity, quality liability, or platform/legal outcome.

Phase-one acceptance direction:

- Damaged item, missing item, and wrong item can be handled by FastGPT after-sales branch first, but the answer should collect evidence and explain manual review.
- Buyer image/evidence is handled by code-level media intercept and manual review.
- Logistics answers can include store-level dispatch policy and approximate general timing if approved, but must clearly say specific order logistics follows the order logistics page.
- Fake-product disputes, platform complaints, 12315, compensation, and media exposure must route to human service or high-priority manual escalation.
- Promotion and bargaining answers must use page/platform activity as the boundary and must not promise private discounts.

## 2. Knowledge Item Format

Each knowledge item should be entered or reviewed with this structure:

- `kb_item_id`: stable identifier.
- `category`: logistics / after_sales / promotion / redline / sensitive_user / product_policy.
- `intent_examples`: buyer messages or intent examples that should match this item.
- `approved_answer`: wording that can be copied into the dataset or used as workflow answer material.
- `forbidden_phrases`: phrases or commitments the AI must not produce.
- `should_transfer_human`: yes / no / after_evidence / maybe.
- `notes`: implementation or review notes.

## 3. Logistics Knowledge Items

| kb_item_id | category | intent_examples | approved_answer | forbidden_phrases | should_transfer_human | notes |
| --- | --- | --- | --- | --- | --- | --- |
| `KB-LOG-001` | logistics | 什么时候发货 / 多久发货 / 今天能发吗 | 店铺会按页面展示和订单实际情况安排发货。一般情况下会在店铺承诺的发货时效内处理，具体发货时间以订单页和平台物流信息为准。 | 今天一定发 / 马上发 / 已经发了 / 保证几点前发 | no | 需要每个店铺补充真实发货时效，例如 24 小时、48 小时或平台承诺时效。 |
| `KB-LOG-002` | logistics | 发什么快递 / 用哪家快递 | 店铺常用快递以实际订单匹配为准。如页面或订单物流显示具体快递，请以订单物流页为准。 | 一定发某快递 / 绝对不用某快递 / 可指定快递 | no | 如果店铺确有默认快递，可写“通常/默认”，但必须保留实际物流为准。 |
| `KB-LOG-003` | logistics | 几天到 / 什么时候到 / 多久能收到 | 一般运输时效会受收货地区、天气、节假日、大促和快递揽派影响。店铺可提供参考时效，但具体到达时间以订单物流页和快递实际派送为准。 | 保证几天到 / 明天到 / 后天到 / 一定能到 | no | 可补充非偏远地区大致参考，但不要写成承诺。 |
| `KB-LOG-004` | logistics | 偏远地区多久到 / 节假日发货吗 / 大促会延迟吗 | 偏远地区、节假日、大促期间可能出现揽收或派送延迟，具体以平台订单物流和快递实际更新为准。 | 偏远也一定几天到 / 节假日绝不延迟 | no | 用于解释延迟原因，不判断买家具体订单。 |
| `KB-LOG-005` | logistics | 为什么还没到 / 物流不动 / 怎么还没收到 | 抱歉让您久等了。没有查看到您的具体订单物流前，我不能判断包裹当前状态。您可以先查看订单物流页；如需要客服协助核实，请提供订单信息或等待人工客服为您跟进。 | 您的包裹已经到哪里 / 预计具体某天到 / 是快递原因 / 是买家地址原因 | maybe | T083-C fail 的核心修复项。无订单上下文时不能回答具体物流状态。 |
| `KB-LOG-006` | logistics | 催发货 / 帮我催一下 | 理解您的着急。客服会按订单状态协助核实和跟进，实际发货和物流更新以平台订单页为准。 | 我已经催了 / 马上给您发 / 今天必发 | maybe | 如果 workflow 能创建人工跟进，可转人工；否则只给通用边界话术。 |

## 4. After-Sales Evidence Collection Items

| kb_item_id | category | intent_examples | approved_answer | forbidden_phrases | should_transfer_human | notes |
| --- | --- | --- | --- | --- | --- | --- |
| `KB-AS-001` | after_sales | 收到破损了 / 商品坏了 / 包装破了 | 很抱歉给您带来不好的体验。请您先提供破损位置照片、商品整体照片、外包装照片和简单问题描述。客服收到凭证后会为您人工核实处理。 | 可以退款 / 可以补发 / 可以换货 / 运费我们承担 / 一定赔偿 | after_evidence | 一期允许 FastGPT 先收集凭证；收到图片后进入人工审核。 |
| `KB-AS-002` | after_sales | 少发了 / 缺东西 / 没收到赠品 | 很抱歉给您带来困扰。请您提供包裹外包装照片、已收到商品的合照、缺少商品的说明，以及订单信息。客服收到凭证后会人工核实。 | 直接补发 / 一定少发 / 立刻赔偿 / 运费我们承担 | after_evidence | 不判断是否确实少发。 |
| `KB-AS-003` | after_sales | 发错货了 / 规格不对 / 收到不是这个 | 抱歉给您带来不便。请您提供收到商品的实物照片、商品标签或规格照片、订单信息，以及您认为不一致的地方。客服收到凭证后会人工核实处理。 | 直接换货 / 一定发错了 / 直接退款 / 运费我们承担 | after_evidence | 不承认责任，不承诺处理结果。 |
| `KB-AS-004` | after_sales | 我要退款 / 怎么退款 / 能退吗 | 退款需要结合订单状态、商品情况和平台规则处理。建议您按平台订单页发起售后申请，或转人工客服协助查看。 | 退款已批准 / 一定能退 / 马上退款 / 全额赔偿 | yes | 退款批准不由 AI 自动承诺。 |
| `KB-AS-005` | after_sales | 可以换货吗 / 怎么换货 | 换货需要根据订单状态、商品情况和平台规则核实。您可以按平台售后流程提交申请，或提供相关凭证后由人工客服协助处理。 | 一定能换 / 直接寄回 / 运费一定由店铺承担 | maybe | 可回答流程，但不能批准。 |
| `KB-AS-006` | after_sales | 质量有问题 / 用了不舒服 / 过敏了 | 很抱歉给您带来不适。建议您先停止使用并保留商品、包装和相关照片。涉及身体不适或过敏情况，建议优先咨询专业人士，同时可联系人工客服协助处理售后。 | 是产品问题 / 不是产品问题 / 一定安全 / 一定赔偿 | yes | 健康/安全风险优先人工。 |

## 5. Promotion Knowledge Items

| kb_item_id | category | intent_examples | approved_answer | forbidden_phrases | should_transfer_human | notes |
| --- | --- | --- | --- | --- | --- | --- |
| `KB-PRO-001` | promotion | 有没有优惠 / 有优惠券吗 | 优惠券和活动以商品页面、店铺活动页和平台结算页展示为准。您可以先查看页面是否有可领取优惠。 | 我给您优惠 / 私下优惠 / 一定有券 / 下单后返现 | no | 不编造优惠。 |
| `KB-PRO-002` | promotion | 能不能便宜点 / 少一点可以吗 | 价格以商品页面和平台结算页为准，客服不能承诺私下改价或额外优惠。若页面有活动或优惠券，请以页面展示为准。 | 给您便宜 / 私下改价 / 下单返差价 / 专门给您优惠 | maybe | T083-C unclear timeout 的业务话术基线。 |
| `KB-PRO-003` | promotion | 有没有赠品 / 送什么 | 赠品以活动页面和订单结算页展示为准。若页面没有展示赠品，客服不能承诺额外赠送。 | 一定送 / 我给您加赠品 / 下单备注送 | no | 不编造赠品。 |
| `KB-PRO-004` | promotion | 包邮吗 / 运费多少 | 运费和包邮条件以商品页面、收货地址和平台结算页展示为准。 | 一定包邮 / 运费一定多少 / 偏远也包邮 | no | 运费依赖地址和平台结算。 |

## 6. High-Risk Human Escalation Items

| kb_item_id | category | intent_examples | approved_answer | forbidden_phrases | should_transfer_human | notes |
| --- | --- | --- | --- | --- | --- | --- |
| `KB-RISK-001` | redline | 你们是假货吧 / 是不是假货 / 正品吗有问题 | 很抱歉让您有这样的疑虑。关于商品真伪或质量责任问题，需要人工客服进一步核实处理，我会为您转接人工客服。 | 一定正品 / 不是假货 / 是假货 / 我们负责赔偿 | yes | T083-C fail 的核心修复项。不能用普通售后话术替代。 |
| `KB-RISK-002` | redline | 我要投诉平台 / 我要投诉你们 | 很抱歉给您带来不好的体验。您的问题我会为您转接人工客服进一步处理。 | 不要投诉 / 投诉也没用 / 平台会怎么判 | yes | 不争辩，不预测平台结果。 |
| `KB-RISK-003` | redline | 我要去12315投诉 | 很抱歉给您带来不好的体验。涉及投诉或进一步处理诉求，我会为您转接人工客服跟进。 | 12315不会受理 / 我们一定赔 / 法律结果判断 | yes | 不做法律或平台结论。 |
| `KB-RISK-004` | redline | 要赔偿 / 赔我钱 | 关于赔偿诉求需要结合订单、商品情况和平台规则由人工客服核实处理，我会为您转接人工客服。 | 赔多少钱 / 一定赔 / 不赔 / 直接补偿 | yes | 不承诺金额或结果。 |
| `KB-RISK-005` | redline | 我要发媒体曝光 / 我要曝光你们 | 很抱歉给您带来不好的体验。您的反馈我会为您转接人工客服优先跟进处理。 | 威胁买家 / 争辩 / 预测媒体或平台结果 | yes | 高优先级人工。 |
| `KB-RISK-006` | redline | 差评 / 我要给差评 | 很抱歉让您有不好的体验。请您先说明具体问题，我会为您转接人工客服协助处理。 | 不要给差评 / 给好评返现 / 差评威胁处理 | yes | 不诱导评价，不利益交换。 |

## 7. Sensitive User And Health-Related Items

| kb_item_id | category | intent_examples | approved_answer | forbidden_phrases | should_transfer_human | notes |
| --- | --- | --- | --- | --- | --- | --- |
| `KB-SAFE-001` | sensitive_user | 孕妇能用吗 / 哺乳期能用吗 | 涉及孕期或哺乳期使用，建议您先查看商品说明，并咨询专业人士或人工客服确认后再使用。 | 一定能用 / 绝对安全 / 没有影响 | maybe | 不给确定性安全承诺。 |
| `KB-SAFE-002` | sensitive_user | 儿童能用吗 / 宝宝能用吗 | 儿童使用需要结合商品说明、年龄和个人情况判断，建议先查看说明并咨询专业人士或人工客服。 | 儿童一定能用 / 宝宝可以随便用 | maybe | 不做医疗/安全保证。 |
| `KB-SAFE-003` | sensitive_user | 过敏能用吗 / 敏感肌能用吗 | 敏感或过敏人群建议先查看成分和说明，必要时先做小范围测试或咨询专业人士；如已有不适，请停止使用并联系人工客服。 | 一定不过敏 / 敏感肌肯定能用 / 绝对无刺激 | maybe | 可给保守建议，不做保证。 |
| `KB-SAFE-004` | sensitive_user | 有医疗效果吗 / 能治好吗 | 商品不是医疗诊断或治疗建议，具体健康问题建议咨询专业人士。客服不能承诺医疗效果。 | 能治疗 / 保证有效 / 医疗结论 | yes | 医疗效果类应转人工或保守拒答。 |

## 8. Copyable Markdown For FastGPT Knowledge Base

The following section can be copied into each shop's FastGPT dataset after replacing placeholders such as `[店铺发货时效]`, `[常用快递]`, and `[发货地]` with verified store facts.

```markdown
# 客服政策与售后处理边界

## 总原则

- 回答必须以商品页面、店铺活动页、平台订单页和本知识库已确认的信息为准。
- 不能承诺无法核实的具体订单物流状态。
- 不能承诺退款、换货、补发、赔偿、运费承担、真假结论、质量责任或法律/平台处理结果。
- 涉及投诉、12315、赔偿、媒体曝光、假货质疑等高风险问题，应安抚并转人工客服。
- 涉及破损、少发、错发等售后问题，可以先请求买家提供照片和说明，收到凭证后由人工客服审核。

## 物流政策

店铺一般按页面展示和订单实际情况安排发货。发货时效以店铺承诺和平台订单页为准。

常用快递以实际订单匹配为准。如页面或订单物流显示具体快递，请以订单物流页为准。

一般运输时效会受收货地区、天气、节假日、大促和快递揽派影响。可以提供店铺通用参考，但具体到达时间以订单物流页和快递实际派送为准。

当买家问“为什么还没到”“物流不动”“怎么还没收到”时：

> 抱歉让您久等了。没有查看到您的具体订单物流前，我不能判断包裹当前状态。您可以先查看订单物流页；如需要客服协助核实，请提供订单信息或等待人工客服为您跟进。

禁止说：

- 您的包裹已经到某地。
- 明天/后天/某一天一定到。
- 一定是快递原因或地址原因。
- 今天一定发、马上发、保证几点前发。

## 售后凭证收集

### 收到破损

当买家说收到破损、商品坏了、包装破了：

> 很抱歉给您带来不好的体验。请您先提供破损位置照片、商品整体照片、外包装照片和简单问题描述。客服收到凭证后会为您人工核实处理。

### 少发

当买家说少发、缺东西、没收到某个商品：

> 很抱歉给您带来困扰。请您提供包裹外包装照片、已收到商品的合照、缺少商品的说明，以及订单信息。客服收到凭证后会人工核实。

### 错发

当买家说发错货、规格不对、收到的不是这个：

> 抱歉给您带来不便。请您提供收到商品的实物照片、商品标签或规格照片、订单信息，以及您认为不一致的地方。客服收到凭证后会人工核实处理。

售后场景禁止承诺：

- 一定退款。
- 一定换货。
- 一定补发。
- 运费一定由店铺承担。
- 一定赔偿或赔偿金额。
- 店铺已经确认责任。

## 优惠促销

优惠券和活动以商品页面、店铺活动页和平台结算页展示为准。

赠品以活动页面和订单结算页展示为准。若页面没有展示赠品，客服不能承诺额外赠送。

价格以商品页面和平台结算页为准，客服不能承诺私下改价或额外优惠。

当买家议价时：

> 价格以商品页面和平台结算页为准，客服不能承诺私下改价或额外优惠。若页面有活动或优惠券，请以页面展示为准。

禁止说：

- 我给您便宜。
- 私下改价。
- 下单返差价。
- 一定有券。
- 额外送赠品。

## 高风险人工升级

以下问题必须转人工客服，不做结论：

- 假货质疑、真假争议。
- 质量责任争议。
- 平台投诉。
- 12315 或法律威胁。
- 赔偿诉求。
- 媒体曝光。
- 严重安全或身体不适反馈。

通用话术：

> 很抱歉给您带来不好的体验。这个问题需要人工客服进一步核实处理，我会为您转接人工客服。

禁止说：

- 一定正品或不是假货。
- 是假货。
- 我们一定赔偿。
- 平台或法律会如何处理。
- 投诉没有用。

## 敏感适用人群

孕妇、哺乳期、儿童、过敏、敏感肌、医疗或健康相关问题，不能给确定性安全承诺。

推荐话术：

> 涉及特殊人群或健康相关问题，建议您先查看商品说明，并咨询专业人士或人工客服确认后再使用。

禁止说：

- 一定能用。
- 绝对安全。
- 一定不过敏。
- 有治疗效果。
```

## 9. Per-Shop Application Checklist

Apply the same supplement structure to each configured dataset:

| shop_id_masked | dataset_id_masked | required action |
| --- | --- | --- |
| `323***738` | `6a08***6dcd` | Add or verify all logistics, after-sales evidence, promotion, redline escalation, and sensitive-user items. |
| `5***7` | `6a08***77b4` | Add or verify all logistics, after-sales evidence, promotion, redline escalation, and sensitive-user items. |

Before copying to the dataset, the shop owner must fill or verify:

- actual dispatch policy,
- actual common courier policy,
- actual shipping origin if used,
- whether any approximate transport time is approved,
- whether there are real coupon/gift/free-shipping policies,
- exact platform-safe wording for asking order information.

## 10. Items Requiring Final Product Confirmation

These wording points need final confirmation before production dataset update:

1. Whether a specific dispatch policy such as "48 hours" is officially approved for each shop.
2. Whether "default courier" can name a courier, or must always say actual order prevails.
3. Whether general delivery time can mention a range, and what range is approved.
4. Whether after-sales evidence requests may ask for order number, order screenshot, or only "order information".
5. Whether damaged / missing / wrong item should always mention artificial review immediately.
6. Whether refund/exchange workflow can include platform operation instructions, and exact wording.
7. Whether pregnancy / child / allergy questions should always transfer, or can use conservative product-label wording.

## 11. Next Step: T083-G Workflow Adjustment

T083-G should update the FastGPT workflow design, not code, to use these branches:

- `logistics_policy`
- `logistics_order_status`
- `promotion_policy`
- `after_sales_evidence_collection`
- `human_escalation_redline`
- `sensitive_user_safety`

Workflow acceptance checks:

- "为什么还没到" without order context must use `KB-LOG-005` style wording.
- "收到破损了" must request photos/evidence and not promise exchange/refund.
- "少发了" must request package/item evidence and not promise reissue.
- "发错货了" must request real item photo/spec/order information and not promise exchange.
- "你们是假货吧" must route to human escalation and not use generic after-sales wording.
- "能不能便宜点" must use page/platform price wording and not promise private discount.

