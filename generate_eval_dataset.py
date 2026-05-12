"""
Router 模块评测数据生成器

采用"模版化+同义词替换+随机组合"策略，生成 1000 条香水电商测试集。
不依赖硬编码关键词，模拟真实用户多样化表达。

运行方式:
    cd E:\develop\customer-agent-refactor
    python generate_eval_dataset.py
"""
import csv
import random
import os
from typing import List, Tuple

# =============================================================================
# 同义词库（模拟真实用户多样化表达）
# =============================================================================

# 香水相关名词
PERFUME_NAMES = [
    "这款香水", "这个香水", "这瓶香水", "那个香水", "这款", "这个", "它",
    "桂花香水", "玫瑰香水", "茉莉香水", "薰衣草香水", "柑橘香水",
    "女士香水", "男士香水", "中性香水", "淡香水", "浓香水",
    "小样", "正装", "套装", "礼盒"
]

# 售前问题模板
PRE_SALE_TEMPLATES = [
    # 物流相关
    "{perfume}发什么快递？",
    "{perfume}多久能到？",
    "{perfume}能发顺丰吗？",
    "{perfume}包邮吗？",
    "发{city}要几天？",
    "有现货吗？什么时候发货？",
    "可以加急发货吗？",
    "能指定快递吗？",

    # 成分/规格相关
    "{perfume}是什么香调的？",
    "{perfume}留香时间多久？",
    "{perfume}前调中调后调是什么？",
    "{perfume}容量是多少？",
    "{perfume}有几种规格？",
    "{perfume}成分安全吗？",
    "{perfume}含酒精吗？",
    "{perfume}适合什么季节用？",
    "{perfume}适合什么年龄段？",
    "{perfume}味道浓吗？",

    # 价格/活动相关
    "{perfume}多少钱？",
    "{perfume}有优惠吗？",
    "{perfume}打折吗？",
    "现在有什么活动？",
    "买{num}瓶有优惠吗？",
    "有赠品吗？",
    "会员有折扣吗？",
    "新用户有优惠吗？",

    # 使用相关
    "{perfume}怎么用？",
    "{perfume}喷哪里好闻？",
    "{perfume}一天喷几次？",
    "{perfume}能喷衣服上吗？",
    "{perfume}适合约会用吗？",
    "{perfume}适合上班用吗？",

    # 对比相关
    "{perfume1}和{perfume2}哪个好闻？",
    "{perfume1}和{perfume2}区别大吗？",
    "这两款味道差别大吗？",
    "推荐哪一款？",
    "哪款留香更久？",
]

# 售后问题模板
AFTER_SALES_TEMPLATES = [
    # 退货相关
    "{perfume}不喜欢能退吗？",
    "{perfume}味道不喜欢怎么办？",
    "想退货怎么操作？",
    "退货流程是什么？",
    "退货地址在哪里？",
    "退货要自己付运费吗？",
    "七天无理由退货吗？",
    "拆开了还能退吗？",
    "用过了能退吗？",

    # 换货相关
    "{perfume}能换其他味道吗？",
    "发错货了能换吗？",
    "想换{perfume2}怎么操作？",
    "换货要补差价吗？",
    "换货流程是什么？",

    # 质量问题
    "{perfume}喷头坏了怎么办？",
    "{perfume}按不出来怎么办？",
    "{perfume}漏液了怎么办？",
    "{perfume}瓶身有划痕怎么办？",
    "{perfume}包装破损了怎么办？",
    "{perfume}味道变质了怎么办？",
    "{perfume}颜色不对怎么办？",
    "收到的是空的怎么办？",
    "少发了怎么办？",

    # 使用问题
    "{perfume}喷不出来怎么办？",
    "{perfume}堵住了怎么办？",
    "{perfume}味道太淡了怎么办？",
    "{perfume}味道太浓了怎么办？",
    "{perfume}过敏了怎么办？",

    # 物流问题
    "{perfume}还没收到怎么办？",
    "快递显示签收但没收到怎么办？",
    "快递丢件了怎么办？",
    "能催一下快递吗？",
    "能改地址吗？",
]

# 红线问题模板（极端情况）
REDLINE_TEMPLATES = [
    # 投诉相关
    "你们卖的是假货！",
    "这绝对是假货！我要投诉！",
    "我要去工商局举报你们！",
    "我要打12315投诉！",
    "我要投诉你们店铺！",
    "你们这是欺诈！",
    "我要报警！",
    "你们等着收律师函！",

    # 过敏/伤害相关
    "用了{perfume}脸烂了！",
    "用了{perfume}过敏了！",
    "用了{perfume}皮肤红肿！",
    "用了{perfume}起疹子了！",
    "用了{perfume}眼睛肿了！",
    "用了{perfume}呼吸困难！",
    "小孩用了{perfume}过敏了！",
    "孕妇用了{perfume}有问题吗？",

    # 极端情绪
    "你们是骗子！",
    "垃圾店铺！",
    "再也不买了！",
    "差评！必须差评！",
    "我要曝光你们！",
    "我要发朋友圈曝光你们！",
    "我要发小红书曝光你们！",
    "我要找媒体曝光！",

    # 极端诉求
    "不解决我就去工商局！",
    "不退款我就投诉！",
    "不赔偿我就报警！",
    "你们必须赔偿我{money}！",
    "我要十倍赔偿！",
]

# 未知/闲聊模板
UNKNOWN_TEMPLATES = [
    # 极短句
    "在吗",
    "有人吗",
    "你好",
    "哈喽",
    "亲",
    "在不在",
    "客服在吗",
    "？",
    "。。。",
    "嗯",
    "好的",
    "哦",
    "行",
    "可以",
    "嗯嗯",
    "好的呢",

    # 日常寒暄
    "今天天气真好",
    "你们店开了多久了",
    "你们客服是真人吗",
    "你们是机器人吗",
    "你们几点下班",
    "你们有实体店吗",
    "你们在哪个城市",
    "你们老板是谁",

    # 无意义内容
    "哈哈哈哈",
    "嘿嘿",
    "啦啦啦",
    "随便看看",
    "就是问问",
    "没事了",
    "算了",
    "不用了",
    "好的谢谢",
    "知道了",

    # 表情符号
    "[表情]",
    "[微笑]",
    "[大笑]",
    "[图片]",
    "[红包]",
]

# 城市列表
CITIES = ["北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉", "西安", "重庆"]

# 数字
NUMBERS = ["两", "三", "四", "五", "2", "3", "4", "5"]

# 金额
MONEYS = ["1000", "2000", "5000", "一万", "两万"]


def generate_pre_sale_queries(count: int) -> List[Tuple[str, str, str]]:
    """生成售前问题"""
    queries = []
    for _ in range(count):
        template = random.choice(PRE_SALE_TEMPLATES)

        # 随机替换变量
        query = template.format(
            perfume=random.choice(PERFUME_NAMES),
            perfume1=random.choice(PERFUME_NAMES),
            perfume2=random.choice(PERFUME_NAMES),
            city=random.choice(CITIES),
            num=random.choice(NUMBERS)
        )

        queries.append((query, "pre_sale", "none"))

    return queries


def generate_after_sales_queries(count: int) -> List[Tuple[str, str, str]]:
    """生成售后问题"""
    queries = []
    for _ in range(count):
        template = random.choice(AFTER_SALES_TEMPLATES)

        query = template.format(
            perfume=random.choice(PERFUME_NAMES),
            perfume2=random.choice(PERFUME_NAMES)
        )

        queries.append((query, "after_sales", "none"))

    return queries


def generate_redline_queries(count: int) -> List[Tuple[str, str, str]]:
    """生成红线问题"""
    queries = []
    for _ in range(count):
        template = random.choice(REDLINE_TEMPLATES)

        query = template.format(
            perfume=random.choice(PERFUME_NAMES),
            money=random.choice(MONEYS)
        )

        queries.append((query, "redline", "high"))

    return queries


def generate_unknown_queries(count: int) -> List[Tuple[str, str, str]]:
    """生成未知/闲聊问题"""
    queries = []
    for _ in range(count):
        query = random.choice(UNKNOWN_TEMPLATES)
        queries.append((query, "unknown", "none"))

    return queries


def add_noise_to_queries(queries: List[Tuple[str, str, str]]) -> List[Tuple[str, str, str]]:
    """添加噪声：随机大小写、添加语气词等"""
    noisy_queries = []

    noise_prefixes = ["", "亲，", "老板，", "客服，", "那个，", "就是，", "请问", "想问下"]
    noise_suffixes = ["", "谢谢", "麻烦了", "急", "在线等", "求回复", "拜托了"]

    for query, intent, alert in queries:
        # 随机添加前缀/后缀
        if random.random() > 0.7:
            query = random.choice(noise_prefixes) + query
        if random.random() > 0.8:
            query = query + random.choice(noise_suffixes)

        noisy_queries.append((query, intent, alert))

    return noisy_queries


def generate_dataset(total_count: int = 1000) -> List[Tuple[str, str, str]]:
    """生成完整数据集"""
    print(f"[数据生成] 开始生成 {total_count} 条测试数据...")

    # 按比例分配
    pre_sale_count = int(total_count * 0.4)
    after_sales_count = int(total_count * 0.4)
    redline_count = int(total_count * 0.1)
    unknown_count = total_count - pre_sale_count - after_sales_count - redline_count

    print(f"[数据生成] 分布: pre_sale={pre_sale_count}, after_sales={after_sales_count}, redline={redline_count}, unknown={unknown_count}")

    # 生成各类数据
    all_queries = []
    all_queries.extend(generate_pre_sale_queries(pre_sale_count))
    all_queries.extend(generate_after_sales_queries(after_sales_count))
    all_queries.extend(generate_redline_queries(redline_count))
    all_queries.extend(generate_unknown_queries(unknown_count))

    # 添加噪声
    all_queries = add_noise_to_queries(all_queries)

    # 随机打乱
    random.shuffle(all_queries)

    print(f"[数据生成] 完成，共 {len(all_queries)} 条")

    return all_queries


def save_to_csv(queries: List[Tuple[str, str, str]], filepath: str):
    """保存到 CSV 文件"""
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['query', 'expected_intent', 'expected_alert'])
        for query, intent, alert in queries:
            writer.writerow([query, intent, alert])

    print(f"[数据保存] 已保存到 {filepath}")


def main():
    # 设置随机种子（可复现）
    random.seed(42)

    # 生成数据集
    queries = generate_dataset(1000)

    # 保存
    output_path = os.path.join(os.path.dirname(__file__), "router_eval_dataset.csv")
    save_to_csv(queries, output_path)

    # 打印样本
    print("\n[样本展示]")
    print("=" * 60)
    for i, (query, intent, alert) in enumerate(queries[:10], 1):
        print(f"{i}. [{intent}] {query}")

    # 统计
    print("\n[统计信息]")
    intent_counts = {}
    for _, intent, _ in queries:
        intent_counts[intent] = intent_counts.get(intent, 0) + 1

    for intent, count in sorted(intent_counts.items()):
        print(f"  {intent}: {count}")


if __name__ == "__main__":
    main()
