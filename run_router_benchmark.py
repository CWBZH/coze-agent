"""
Router 模块高并发评测引擎

读取 CSV 数据集，批量推理，计算高阶算法指标。

运行方式:
    cd E:\develop\customer-agent-refactor
    python run_router_benchmark.py
"""
import csv
import os
import time
import random
from typing import Dict, List, Tuple, Any
from collections import defaultdict
from dataclasses import dataclass

# 进度条
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False
    print("[WARNING] tqdm 未安装，将使用简单进度显示")


# =============================================================================
# 评测数据结构
# =============================================================================
@dataclass
class EvalResult:
    """单条评测结果"""
    query: str
    expected_intent: str
    expected_alert: str
    predicted_intent: str
    predicted_alert: str
    is_correct: bool
    error_type: str = ""  # 错误类型描述


# =============================================================================
# Router 模拟器（隔离外部依赖）- V2.0 重构版
# =============================================================================
class RouterSimulator:
    """
    Router 模块模拟器 - 三级漏斗混合路由

    不连接真实数据库和 LLM，直接模拟 Router 的关键词检测逻辑。
    """

    # 红线关键词（V2.0 大幅扩充）
    REDLINE_KEYWORDS = frozenset({
        # 投诉举报类
        "投诉", "举报", "工商局", "12315", "报警", "律师", "曝光",
        "欺诈", "骗子", "骗人", "黑店",

        # 假货质量类
        "假货", "假", "仿品", "山寨", "质量问题",

        # 身体伤害类（扩充）
        "过敏", "烂脸", "脸烂", "红肿", "肿", "疹子", "呼吸困难", "副作用",
        "中毒", "不适", "刺激", "眼睛肿", "肿了",

        # 极端情绪类（扩充）
        "垃圾", "差评", "退钱", "赔偿", "十倍",
        "不解决", "不退款", "不赔偿", "等着", "走着瞧",
        "再也不买", "不买了", "再也不",

        # 媒体曝光类
        "朋友圈", "小红书", "媒体", "记者", "直播",

        # 安全风险类（孕妇/儿童使用问题）
        "孕妇用了", "孕妇用", "有问题吗"
    })

    # 售后关键词（优先级高于售前）
    AFTER_SALES_KEYWORDS = frozenset({
        # 退换货类
        "退货", "换货", "退款", "退", "换",

        # 质量问题类
        "漏液", "破损", "坏了", "坏", "破", "漏",
        "按不出", "喷不出", "堵住", "堵了",
        "变质", "异味", "发霉",

        # 物流问题类
        "没收到", "丢件", "发错", "少发", "错发",
        "签收", "快递问题", "催一下", "催快递", "改地址",

        # 价格问题类
        "降价", "差价", "补差价",

        # 使用问题类
        "不喜欢", "不合适", "不满意",

        # 质量反馈类
        "划痕", "颜色不对", "味道淡", "味道太淡"
    })

    # 售前关键词
    PRE_SALE_KEYWORDS = frozenset({
        # 价格活动类
        "多少钱", "价格", "优惠", "打折", "活动", "赠品",
        "会员", "折扣",

        # 物流咨询类
        "发什么快递", "快递", "发货", "包邮", "顺丰",
        "多久能到", "几天",

        # 产品咨询类
        "留香", "前调", "中调", "后调", "香调",
        "成分", "容量", "规格", "保质期",
        "适合", "孕妇", "敏感肌",

        # 使用咨询类
        "怎么用", "怎么喷", "喷哪里", "喷衣服",

        # 对比咨询类
        "推荐", "好闻", "差别", "区别", "哪个好"
    })

    # 售前负向关键词
    NEGATIVE_PRE_SALE = frozenset({
        "退", "换", "坏", "破", "漏", "丢", "错"
    })

    # 极短句阈值
    SHORT_THRESHOLD = 5

    def predict(self, query: str) -> Tuple[str, str]:
        """
        预测意图和警报级别 - 三级漏斗混合路由

        优先级顺序（绝对不可乱）：
        1. 红线关键词检测（最高优先级）
        2. 极短句意图继承（排除危险词后）
        3. 售后关键词检测
        4. 售前关键词检测（带负向词过滤）

        Returns:
            (predicted_intent, predicted_alert)
        """
        query_lower = query.lower()

        # =====================================================
        # Level 0: 红线关键词检测（最高优先级）
        # =====================================================
        for keyword in self.REDLINE_KEYWORDS:
            if keyword in query_lower:
                return ("redline", "high")

        # =====================================================
        # Level 1: 极短句检测（排除危险词后）
        # =====================================================
        if len(query) <= self.SHORT_THRESHOLD:
            # 模拟：极短句返回 unknown（实际应从 Redis 继承）
            return ("unknown", "none")

        # =====================================================
        # Level 2: 售后关键词检测
        # =====================================================
        for keyword in self.AFTER_SALES_KEYWORDS:
            if keyword in query_lower:
                return ("after_sales", "none")

        # =====================================================
        # Level 3: 售前关键词检测（带负向词过滤）
        # =====================================================
        has_negative = any(neg_kw in query_lower for neg_kw in self.NEGATIVE_PRE_SALE)

        if not has_negative:
            for keyword in self.PRE_SALE_KEYWORDS:
                if keyword in query_lower:
                    return ("pre_sale", "none")

        # =====================================================
        # Level 4: 最终兜底 - unknown
        # =====================================================
        return ("unknown", "none")


# =============================================================================
# 评测引擎
# =============================================================================
class RouterBenchmarkEngine:
    """Router 评测引擎"""

    def __init__(self, dataset_path: str):
        self.dataset_path = dataset_path
        self.router = RouterSimulator()
        self.results: List[EvalResult] = []
        self.failed_cases: List[EvalResult] = []

    def load_dataset(self) -> List[Tuple[str, str, str]]:
        """加载 CSV 数据集"""
        queries = []
        with open(self.dataset_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                queries.append((
                    row['query'],
                    row['expected_intent'],
                    row['expected_alert']
                ))
        return queries

    def run_evaluation(self):
        """运行评测"""
        queries = self.load_dataset()
        total = len(queries)

        print(f"\n[评测引擎] 开始评测 {total} 条数据...")

        start_time = time.time()

        # 使用进度条
        if HAS_TQDM:
            iterator = tqdm(queries, desc="评测进度", unit="条")
        else:
            iterator = queries
            print(f"[评测引擎] 0/{total}")

        for i, (query, expected_intent, expected_alert) in enumerate(iterator):
            # 预测
            predicted_intent, predicted_alert = self.router.predict(query)

            # 判断正确性
            is_correct = (
                predicted_intent == expected_intent and
                predicted_alert == expected_alert
            )

            # 记录结果
            result = EvalResult(
                query=query,
                expected_intent=expected_intent,
                expected_alert=expected_alert,
                predicted_intent=predicted_intent,
                predicted_alert=predicted_alert,
                is_correct=is_correct
            )

            if not is_correct:
                result.error_type = f"{expected_intent}->{predicted_intent}"
                self.failed_cases.append(result)

            self.results.append(result)

            # 简单进度显示（无 tqdm 时）
            if not HAS_TQDM and (i + 1) % 100 == 0:
                print(f"[评测引擎] {i + 1}/{total}")

        elapsed = time.time() - start_time
        print(f"\n[评测引擎] 完成，耗时 {elapsed:.2f} 秒")

    def calculate_metrics(self) -> Dict[str, Any]:
        """计算高阶算法指标"""
        metrics = {}

        # 1. 全局准确率
        correct_count = sum(1 for r in self.results if r.is_correct)
        total_count = len(self.results)
        metrics['overall_accuracy'] = correct_count / total_count

        # 2. 各意图的 Precision 和 Recall
        intent_labels = ['pre_sale', 'after_sales', 'redline', 'unknown']

        for intent in intent_labels:
            # True Positive: 预测为 intent 且实际为 intent
            tp = sum(1 for r in self.results
                     if r.predicted_intent == intent and r.expected_intent == intent)

            # False Positive: 预测为 intent 但实际不是
            fp = sum(1 for r in self.results
                     if r.predicted_intent == intent and r.expected_intent != intent)

            # False Negative: 实际为 intent 但预测不是
            fn = sum(1 for r in self.results
                     if r.expected_intent == intent and r.predicted_intent != intent)

            # Precision = TP / (TP + FP)
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0

            # Recall = TP / (TP + FN)
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0

            # F1 = 2 * P * R / (P + R)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

            metrics[f'{intent}_precision'] = precision
            metrics[f'{intent}_recall'] = recall
            metrics[f'{intent}_f1'] = f1
            metrics[f'{intent}_tp'] = tp
            metrics[f'{intent}_fp'] = fp
            metrics[f'{intent}_fn'] = fn

        # 3. 混淆矩阵
        confusion_matrix = defaultdict(int)
        for r in self.results:
            key = f"{r.expected_intent}->{r.predicted_intent}"
            confusion_matrix[key] += 1

        metrics['confusion_matrix'] = dict(confusion_matrix)

        return metrics

    def save_failed_cases(self, filepath: str):
        """保存失败案例"""
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['query', 'expected_intent', 'predicted_intent', 'error_type'])
            for case in self.failed_cases:
                writer.writerow([
                    case.query,
                    case.expected_intent,
                    case.predicted_intent,
                    case.error_type
                ])

        print(f"[失败案例] 已保存到 {filepath}")

    def print_metrics_report(self, metrics: Dict[str, Any]):
        """打印高阶指标报告"""
        print("\n" + "=" * 70)
        print("Router 评测高阶指标报告")
        print("=" * 70)

        # 1. 全局准确率
        print(f"\n[全局准确率] {metrics['overall_accuracy']:.4f} ({metrics['overall_accuracy']*100:.2f}%)")

        # 2. 各意图指标
        print("\n[各意图指标]")
        print("-" * 70)
        print(f"{'意图':<12} {'Precision':<12} {'Recall':<12} {'F1':<12} {'TP':<6} {'FP':<6} {'FN':<6}")
        print("-" * 70)

        for intent in ['pre_sale', 'after_sales', 'redline', 'unknown']:
            p = metrics[f'{intent}_precision']
            r = metrics[f'{intent}_recall']
            f1 = metrics[f'{intent}_f1']
            tp = metrics[f'{intent}_tp']
            fp = metrics[f'{intent}_fp']
            fn = metrics[f'{intent}_fn']

            # 高亮 redline
            if intent == 'redline':
                print(f"{'[REDLINE]':<12} {p:.4f}       {r:.4f}       {f1:.4f}       {tp:<6} {fp:<6} {fn:<6}  <-- 重点关注")
            else:
                print(f"{intent:<12} {p:.4f}       {r:.4f}       {f1:.4f}       {tp:<6} {fp:<6} {fn:<6}")

        # 3. 混淆矩阵简报
        print("\n[混淆矩阵简报]")
        print("-" * 70)

        confusion = metrics['confusion_matrix']

        # 按错误类型分组
        error_types = defaultdict(int)
        for key, count in confusion.items():
            if '->' in key and key.split('->')[0] != key.split('->')[1]:
                error_types[key] = count

        # 打印主要错误类型
        for error_type, count in sorted(error_types.items(), key=lambda x: -x[1]):
            print(f"  {error_type}: {count} 条")

        # 特别关注 redline 被误判的情况
        redline_errors = {k: v for k, v in error_types.items() if k.startswith('redline->')}
        if redline_errors:
            print("\n[REDLINE 误判详情]")
            for error_type, count in redline_errors.items():
                print(f"  {error_type}: {count} 条 <-- 严重！红线被漏判")

    def analyze_bad_cases(self, top_n: int = 5) -> List[Dict[str, Any]]:
        """分析典型 Bad Case"""
        # 按错误类型分组
        error_groups = defaultdict(list)
        for case in self.failed_cases:
            error_groups[case.error_type].append(case)

        # 选择代表性案例
        bad_cases_analysis = []

        # 1. redline 被误判（最严重）
        redline_errors = [c for c in self.failed_cases if c.expected_intent == 'redline']
        if redline_errors:
            for case in redline_errors[:2]:
                analysis = {
                    'query': case.query,
                    'expected': case.expected_intent,
                    'predicted': case.predicted_intent,
                    'reason': f"红线关键词未覆盖: '{case.query}' 中未检测到红线关键词",
                    'suggestion': "扩展 REDLINE_KEYWORDS，增加口语化表达如 '曝光'、'曝光朋友圈'、'找媒体' 等"
                }
                bad_cases_analysis.append(analysis)

        # 2. after_sales 被误判为 pre_sale
        after_to_pre = [c for c in self.failed_cases
                       if c.expected_intent == 'after_sales' and c.predicted_intent == 'pre_sale']
        if after_to_pre:
            case = after_to_pre[0]
            analysis = {
                'query': case.query,
                'expected': case.expected_intent,
                'predicted': case.predicted_intent,
                'reason': f"关键词冲突: 同时包含售前和售后关键词",
                'suggestion': "调整关键词优先级，售后关键词应高于售前"
            }
            bad_cases_analysis.append(analysis)

        # 3. unknown 被误判
        unknown_errors = [c for c in self.failed_cases if c.expected_intent == 'unknown']
        if unknown_errors:
            case = unknown_errors[0]
            analysis = {
                'query': case.query,
                'expected': case.expected_intent,
                'predicted': case.predicted_intent,
                'reason': f"极短句阈值问题: 长度 {len(case.query)} > {self.router.SHORT_THRESHOLD}",
                'suggestion': "调整 SHORT_SENTENCE_THRESHOLD 或增加闲聊关键词库"
            }
            bad_cases_analysis.append(analysis)

        return bad_cases_analysis[:top_n]


def main():
    # 数据集路径
    dataset_path = os.path.join(os.path.dirname(__file__), "router_eval_dataset.csv")
    failed_cases_path = os.path.join(os.path.dirname(__file__), "failed_cases_report.csv")

    # 检查数据集是否存在
    if not os.path.exists(dataset_path):
        print(f"[ERROR] 数据集不存在: {dataset_path}")
        print("[提示] 请先运行 generate_eval_dataset.py 生成数据集")
        return

    # 创建评测引擎
    engine = RouterBenchmarkEngine(dataset_path)

    # 运行评测
    engine.run_evaluation()

    # 计算指标
    metrics = engine.calculate_metrics()

    # 打印报告
    engine.print_metrics_report(metrics)

    # 保存失败案例
    engine.save_failed_cases(failed_cases_path)

    # 分析 Bad Case
    print("\n" + "=" * 70)
    print("典型 Bad Case 分析")
    print("=" * 70)

    bad_cases = engine.analyze_bad_cases(5)

    for i, case in enumerate(bad_cases, 1):
        print(f"\n[Bad Case {i}]")
        print(f"  Query: {case['query']}")
        print(f"  Expected: {case['expected']}")
        print(f"  Predicted: {case['predicted']}")
        print(f"  原因: {case['reason']}")
        print(f"  建议: {case['suggestion']}")

    # 总结
    print("\n" + "=" * 70)
    print("评测总结")
    print("=" * 70)
    print(f"  总数据量: {len(engine.results)}")
    print(f"  正确数: {sum(1 for r in engine.results if r.is_correct)}")
    print(f"  错误数: {len(engine.failed_cases)}")
    print(f"  准确率: {metrics['overall_accuracy']*100:.2f}%")
    print(f"  Redline Recall: {metrics['redline_recall']*100:.2f}% <-- 关键指标")


if __name__ == "__main__":
    main()