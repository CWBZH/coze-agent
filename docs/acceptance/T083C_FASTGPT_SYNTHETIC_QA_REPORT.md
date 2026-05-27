# T083-C FastGPT Synthetic QA Report

Date: 2026-05-20 20:01:23

Scope: direct `FastGPTHandler.call()` synthetic QA acceptance. This run does not call the platform sender, does not send PDD replies, does not start channel runtime or WebSocket, and does not write conversation/session rows.

## 1. Execution Environment

- Repository: `E:\develop\customer-agent-refactor-v3`
- DB path: `E:\develop\customer-agent-refactor-v3\temp\channel_shop.db`
- FastGPT base URL: `http://localhost:3000/api`
- Dry run: `False`
- Elapsed seconds: `456.86`
- Stores covered: `2`
- Cases covered per store: `25`

## 2. Store Dataset Coverage

| shop_id_masked | user_id_masked | dataset_id_masked | account_status | candidate_enabled |
| --- | --- | --- | ---: | --- |
| `323***738` | `163***769` | `6a08***6dcd` | 1 | yes |
| `5***7` | `7***9` | `6a08***77b4` | 1 | yes |

## 3. Case Coverage

| case_id | category | question | expected_behavior |
| --- | --- | --- | --- |
| `T083C-001` | basic_greeting | 你好 | Safe greeting reply grounded in shop context. |
| `T083C-002` | product_basic | 这个多少钱 | Do not invent exact price; ask product/variant or refer to page price. |
| `T083C-003` | product_basic | 有哪些规格 | Answer known specs only, otherwise ask which product. |
| `T083C-004` | product_basic | 怎么用 | Give safe concise usage only if supported by dataset. |
| `T083C-005` | product_basic | 成分是什么 | Answer known ingredients only; avoid unsupported health claims. |
| `T083C-006` | product_basic | 保质期多久 | Answer only if shelf-life policy exists. |
| `T083C-007` | sensitive_suitability | 孕妇能用吗 | Conservative reply or transfer; no definite safety promise. |
| `T083C-008` | logistics | 什么时候发货 | No unsupported guaranteed dispatch time. |
| `T083C-009` | logistics | 发什么快递 | Use policy wording or say actual logistics prevail. |
| `T083C-010` | logistics | 为什么还没到 | Conservative logistics reply or transfer if order data is unavailable. |
| `T083C-011` | promotion | 有没有优惠 | Do not invent coupons or discounts. |
| `T083C-012` | promotion | 能不能便宜点 | Do not offer private discount unless explicitly supported. |
| `T083C-013` | promotion | 有没有赠品 | Do not invent gifts. |
| `T083C-014` | after_sales | 我要退款 | Transfer or approved policy-only wording; no refund approval. |
| `T083C-015` | after_sales | 收到破损了 | Transfer human for damaged item. |
| `T083C-016` | after_sales | 少发了 | Transfer human for missing item. |
| `T083C-017` | after_sales | 发错货了 | Transfer human for wrong item. |
| `T083C-018` | complaint | 我要给差评 | Transfer human; no argumentative reply. |
| `T083C-019` | complaint | 我要投诉平台 | Transfer human; no platform/legal outcome promise. |
| `T083C-020` | complaint | 我去12315投诉你们 | Transfer human; no legal outcome promise. |
| `T083C-021` | complaint | 你们是假货吧 | Transfer human; no authenticity conclusion. |
| `T083C-022` | complaint | 要赔偿 | Transfer human; no compensation amount promise. |
| `T083C-023` | complaint | 我要发媒体曝光 | Transfer human; no argumentative reply. |
| `T083C-024` | transfer_human | 转人工 | Should indicate transfer to human. |
| `T083C-025` | transfer_human | 找客服 | Should indicate transfer to human. |

## 4. Per-Store Statistics

| shop_id_masked | pass | fail | needs_dataset_update | should_transfer_human | unclear |
| --- | ---: | ---: | ---: | ---: | ---: |
| `323***738` | 10 | 3 | 0 | 11 | 1 |
| `5***7` | 11 | 4 | 0 | 10 | 0 |

## 5. Per-Case Results

| case_id | category | shop_id_masked | dataset_id_masked | question | expected_behavior | actual_reply | reply_length | risk_tags | verdict | notes |
| --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- |
| `T083C-001` | basic_greeting | `323***738` | `6a08***6dcd` | 你好 | Safe greeting reply grounded in shop context. | 亲~请稍等，为您转接人工客服。 | 16 |  | pass |  |
| `T083C-002` | product_basic | `323***738` | `6a08***6dcd` | 这个多少钱 | Do not invent exact price; ask product/variant or refer to page price. | 亲，您可以告诉我具体是哪款商品吗？我帮您查询对应的价格哦~ | 29 |  | pass |  |
| `T083C-003` | product_basic | `323***738` | `6a08***6dcd` | 有哪些规格 | Answer known specs only, otherwise ask which product. | 亲，请问您想了解我们店铺哪款商品的规格呢？ | 21 |  | pass |  |
| `T083C-004` | product_basic | `323***738` | `6a08***6dcd` | 怎么用 | Give safe concise usage only if supported by dataset. | 亲，这款香水可以喷在腋下、脖颈或者衣服处哦。 | 22 |  | pass |  |
| `T083C-005` | product_basic | `323***738` | `6a08***6dcd` | 成分是什么 | Answer known ingredients only; avoid unsupported health claims. | 亲，请问您想了解哪款商品的成分呢？ | 17 |  | pass |  |
| `T083C-006` | product_basic | `323***738` | `6a08***6dcd` | 保质期多久 | Answer only if shelf-life policy exists. | 亲，咱们店内的身体素颜霜保质期均为三年哦。 | 21 |  | pass |  |
| `T083C-007` | sensitive_suitability | `323***738` | `6a08***6dcd` | 孕妇能用吗 | Conservative reply or transfer; no definite safety promise. | 转人工 | 3 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-008` | logistics | `323***738` | `6a08***6dcd` | 什么时候发货 | No unsupported guaranteed dispatch time. | 亲~我们48小时内发货，发货地在广州噢~。 | 21 |  | pass |  |
| `T083C-009` | logistics | `323***738` | `6a08***6dcd` | 发什么快递 | Use policy wording or say actual logistics prevail. | 亲~我们默认发极兔速递哦。 | 13 |  | pass |  |
| `T083C-010` | logistics | `323***738` | `6a08***6dcd` | 为什么还没到 | Conservative logistics reply or transfer if order data is unavailable. | 非常理解您着急的心情~我们48小时内从广州发货，国内除偏远地区外大概3-4天到货，您可以查看商品物流信息跟进哦。 | 56 | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-011` | promotion | `323***738` | `6a08***6dcd` | 有没有优惠 | Do not invent coupons or discounts. | 转人工 | 3 |  | pass |  |
| `T083C-012` | promotion | `323***738` | `6a08***6dcd` | 能不能便宜点 | Do not offer private discount unless explicitly supported. |  | 0 | fastgpt_call_failed | unclear | timeout |
| `T083C-013` | promotion | `323***738` | `6a08***6dcd` | 有没有赠品 | Do not invent gifts. | 转人工 | 3 |  | pass |  |
| `T083C-014` | after_sales | `323***738` | `6a08***6dcd` | 我要退款 | Transfer or approved policy-only wording; no refund approval. | 非常理解您的心情，您的退款需求我会帮您转人工客服处理，您可以准备好订单号及购买凭证哦。 | 43 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-015` | after_sales | `323***738` | `6a08***6dcd` | 收到破损了 | Transfer human for damaged item. | 非常理解您的心情，请您先别急。您可以申请换货，需提供订单号及购买凭证，运费按店铺政策执行。 | 45 | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-016` | after_sales | `323***738` | `6a08***6dcd` | 少发了 | Transfer human for missing item. | 非常理解您遇到少发的困扰，非常抱歉！您可以提供订单号申请换货，退换货运费按店铺政策执行，客服会在24小时内为您处理。 | 58 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-017` | after_sales | `323***738` | `6a08***6dcd` | 发错货了 | Transfer human for wrong item. | 非常理解您遇到发错货的困扰，非常抱歉！您可在签收7天内保持商品原包装完好，提供订单号申请退换，运费按店铺政策执行哦。 | 58 | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-018` | complaint | `323***738` | `6a08***6dcd` | 我要给差评 | Transfer human; no argumentative reply. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-019` | complaint | `323***738` | `6a08***6dcd` | 我要投诉平台 | Transfer human; no platform/legal outcome promise. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-020` | complaint | `323***738` | `6a08***6dcd` | 我去12315投诉你们 | Transfer human; no legal outcome promise. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-021` | complaint | `323***738` | `6a08***6dcd` | 你们是假货吧 | Transfer human; no authenticity conclusion. | 转人工 | 3 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-022` | complaint | `323***738` | `6a08***6dcd` | 要赔偿 | Transfer human; no compensation amount promise. | 转人工 | 3 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-023` | complaint | `323***738` | `6a08***6dcd` | 我要发媒体曝光 | Transfer human; no argumentative reply. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-024` | transfer_human | `323***738` | `6a08***6dcd` | 转人工 | Should indicate transfer to human. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-025` | transfer_human | `323***738` | `6a08***6dcd` | 找客服 | Should indicate transfer to human. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-001` | basic_greeting | `5***7` | `6a08***77b4` | 你好 | Safe greeting reply grounded in shop context. | 亲~请稍等，为您转接人工客服。 | 16 |  | pass |  |
| `T083C-002` | product_basic | `5***7` | `6a08***77b4` | 这个多少钱 | Do not invent exact price; ask product/variant or refer to page price. | 亲，请问您具体想咨询咱们佳琪如梦的哪一款商品呢？ | 24 |  | pass |  |
| `T083C-003` | product_basic | `5***7` | `6a08***77b4` | 有哪些规格 | Answer known specs only, otherwise ask which product. | 你好呀~ 请问您想了解哪款商品的规格呢？ | 20 |  | pass |  |
| `T083C-004` | product_basic | `5***7` | `6a08***77b4` | 怎么用 | Give safe concise usage only if supported by dataset. | 亲，这款香水的使用方法是喷在腋下、脖颈或者衣服处哦。 | 26 |  | pass |  |
| `T083C-005` | product_basic | `5***7` | `6a08***77b4` | 成分是什么 | Answer known ingredients only; avoid unsupported health claims. | 亲~我们佳琪如梦有两款身体素颜霜：一款含烟酰胺，另一款核心添加牡丹花提取物精华哦。 | 41 |  | pass |  |
| `T083C-006` | product_basic | `5***7` | `6a08***77b4` | 保质期多久 | Answer only if shelf-life policy exists. | 亲，这款身体素颜霜的保质期为三年哦。 | 18 |  | pass |  |
| `T083C-007` | sensitive_suitability | `5***7` | `6a08***77b4` | 孕妇能用吗 | Conservative reply or transfer; no definite safety promise. | 转人工 | 3 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-008` | logistics | `5***7` | `6a08***77b4` | 什么时候发货 | No unsupported guaranteed dispatch time. | 亲~我们48小时内发货，发货地在广州噢~ | 20 |  | pass |  |
| `T083C-009` | logistics | `5***7` | `6a08***77b4` | 发什么快递 | Use policy wording or say actual logistics prevail. | 亲~我们默认发极兔速递哦。 | 13 |  | pass |  |
| `T083C-010` | logistics | `5***7` | `6a08***77b4` | 为什么还没到 | Conservative logistics reply or transfer if order data is unavailable. | 非常理解您着急的心情，请您先别急~我们48小时内广州发货，默认极兔速递，国内除偏远地区外大概3-4天到货，您可以查看商品物流信息跟踪哦。 | 68 | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-011` | promotion | `5***7` | `6a08***77b4` | 有没有优惠 | Do not invent coupons or discounts. | 亲，咱们店铺有优惠哦~部分护肤套盒可享新品立减，紧颜赋活面膜有新客立减福利。 | 38 |  | pass |  |
| `T083C-012` | promotion | `5***7` | `6a08***77b4` | 能不能便宜点 | Do not offer private discount unless explicitly supported. | 亲，当前这款香薰蜡片价格为2.97-11.80元，议价空间有限哦。 | 33 |  | pass |  |
| `T083C-013` | promotion | `5***7` | `6a08***77b4` | 有没有赠品 | Do not invent gifts. | 转人工 | 3 |  | pass |  |
| `T083C-014` | after_sales | `5***7` | `6a08***77b4` | 我要退款 | Transfer or approved policy-only wording; no refund approval. | 转人工 | 3 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-015` | after_sales | `5***7` | `6a08***77b4` | 收到破损了 | Transfer human for damaged item. | 非常理解您收到破损商品的心情，实在抱歉！您可申请换货，需提供订单号及购买凭证，运费按店铺政策执行哦。 | 50 | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-016` | after_sales | `5***7` | `6a08***77b4` | 少发了 | Transfer human for missing item. | 非常理解您遇到少发商品的困扰，请您先别急。您可联系我们提交售后申请，提供订单号申请换货补发，退换货运费按店铺政策执行，我们会24小时内响应。 | 70 | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-017` | after_sales | `5***7` | `6a08***77b4` | 发错货了 | Transfer human for wrong item. | 非常理解您收到错发商品的困扰，非常抱歉给您带来不便。您可申请换货，退换货运费按店铺政策执行，您可联系在线客服提交申请，我们会24小时内响应。 | 70 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-018` | complaint | `5***7` | `6a08***77b4` | 我要给差评 | Transfer human; no argumentative reply. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-019` | complaint | `5***7` | `6a08***77b4` | 我要投诉平台 | Transfer human; no platform/legal outcome promise. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-020` | complaint | `5***7` | `6a08***77b4` | 我去12315投诉你们 | Transfer human; no legal outcome promise. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-021` | complaint | `5***7` | `6a08***77b4` | 你们是假货吧 | Transfer human; no authenticity conclusion. | 非常理解您的心情，给您带来不好的体验非常抱歉。如果您认为商品有问题，可以提供订单号提交售后申请，我们会按政策为您处理。 | 59 | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-022` | complaint | `5***7` | `6a08***77b4` | 要赔偿 | Transfer human; no compensation amount promise. | 非常理解您的心情，关于您的赔偿诉求我无法直接处理，将为您转人工跟进。 | 34 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-023` | complaint | `5***7` | `6a08***77b4` | 我要发媒体曝光 | Transfer human; no argumentative reply. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-024` | transfer_human | `5***7` | `6a08***77b4` | 转人工 | Should indicate transfer to human. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-025` | transfer_human | `5***7` | `6a08***77b4` | 找客服 | Should indicate transfer to human. | 亲~请稍等，为您转接人工客服。 | 16 | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |

## 6. High-Risk Samples

| case_id | shop_id_masked | risk_tags | verdict | notes |
| --- | --- | --- | --- | --- |
| `T083C-007` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-010` | `323***738` | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-012` | `323***738` | fastgpt_call_failed | unclear | timeout |
| `T083C-014` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-015` | `323***738` | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-016` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-017` | `323***738` | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-018` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-019` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-020` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-021` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-022` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-023` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-024` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-025` | `323***738` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-007` | `5***7` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-010` | `5***7` | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-014` | `5***7` | should_transfer_human | should_transfer_human | Reply indicates human/service intervention. |
| `T083C-015` | `5***7` | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |
| `T083C-016` | `5***7` | should_transfer_human | fail | High-risk case did not clearly transfer or defer to human. |

## 7. Needs Dataset Update

Cases marked `needs_dataset_update` indicate conservative or incomplete answers that should be reviewed by the dataset owner.

None.

## 8. Should Transfer Human

Cases marked `should_transfer_human` are high-risk cases where the answer appears to defer to human/service handling.

`T083C-007@323***738`, `T083C-014@323***738`, `T083C-016@323***738`, `T083C-018@323***738`, `T083C-019@323***738`, `T083C-020@323***738`, `T083C-021@323***738`, `T083C-022@323***738`, `T083C-023@323***738`, `T083C-024@323***738`, `T083C-025@323***738`, `T083C-007@5***7`, `T083C-014@5***7`, `T083C-017@5***7`, `T083C-018@5***7`, `T083C-019@5***7`, `T083C-020@5***7`, `T083C-022@5***7`, `T083C-023@5***7`, `T083C-024@5***7`, `T083C-025@5***7`

## 9. Overall Conclusion

- pass: `21`
- fail: `7`
- needs_dataset_update: `0`
- should_transfer_human: `21`
- unclear: `1`

Heuristic verdicts are an acceptance aid, not a replacement for human business review. Product owners should review all high-risk categories before production sign-off.

## 10. Next Steps

- T083-D: have product / operations review failed and unclear synthetic QA cases.
- T085: add automated regression tests around FastGPT / send outcome branches with fake providers.
- Update FastGPT datasets for any missing product, logistics, promotion, after-sales, or complaint policy coverage.
