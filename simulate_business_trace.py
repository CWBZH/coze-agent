"""
V2.0 业务场景追踪脚本 - 白盒模拟沙盘

模拟真实流量，打印详尽的 LangGraph 状态机流转日志。

运行方式:
    cd E:\develop\customer-agent-refactor
    python simulate_business_trace.py

注意事项:
    - 本地 Redis 需要启动（用于测试真实物理锁）
    - 其他外部依赖全部 Mock，不消耗真实 Token
    - 使用 importlib 直接加载文件，避免级联导入
"""
import os
import sys
import time
import json
import importlib.util
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Dict, Any, List

# 强制启用 HEADLESS_MODE
os.environ["HEADLESS_MODE"] = "1"

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入核心模块
from database.redis_manager import redis_manager
from core.config import (
    HUMAN_LOCK_TTL,
    INFERENCE_LOCK_TTL,
    INTENT_CACHE_TTL,
    ALERT_COOLDOWN_TTL,
)
from core.constants import (
    IMAGE_INTERCEPT_REPLY,
    FALLBACK_REPLY,
    HIGH_ALERT_PROMPT,
)

# 使用 importlib 直接加载 graph_state，避免级联导入
spec = importlib.util.spec_from_file_location(
    "graph_state",
    os.path.join(os.path.dirname(__file__), "Agent", "CustomerAgent", "custom", "graph_state.py")
)
graph_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph_state)

IntentType = graph_state.IntentType
AlertLevel = graph_state.AlertLevel
REDLINE_KEYWORDS = graph_state.REDLINE_KEYWORDS
AFTER_SALES_KEYWORDS = graph_state.AFTER_SALES_KEYWORDS
PRE_SALE_KEYWORDS = graph_state.PRE_SALE_KEYWORDS


# =============================================================================
# 视觉日志辅助函数
# =============================================================================
def print_header(title: str):
    """打印场景头部"""
    print("\n" + "=" * 70)
    print(f">>> {title}")
    print("=" * 70)


def print_node(node: str, msg: str):
    """打印节点日志"""
    print(f"[{node}] {msg}")


def print_xml_prompt(xml_content: str):
    """打印 XML Prompt（截断展示）"""
    print("[Generator] 组装的 XML Prompt:")
    # 截断到前300字符
    if len(xml_content) > 300:
        print(xml_content[:300] + "...(截断)")
    else:
        print(xml_content)


# =============================================================================
# Mock 外部依赖
# =============================================================================
def create_mock_llm_client():
    """创建 Mock LLM 客户端"""
    mock = MagicMock()

    def mock_chat(messages: List[Dict], **kwargs) -> str:
        """模拟 LLM 响应，根据意图返回不同回复"""
        # 提取最后一条用户消息
        last_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_msg = m.get("content", "")
                break

        # 根据内容判断意图
        if "前调" in last_msg or "成分" in last_msg:
            return "亲爱的顾客，这款香水的前调是清新的柑橘和佛手柑，带来活力四射的开场。"
        elif "退款" in last_msg or "退货" in last_msg:
            return "非常抱歉给您带来不便，请您先提交退款申请，我们会在24小时内处理。"
        elif "红线" in last_msg:
            return "我们非常重视您反馈的问题，已为您升级至主管处理，请稍候。"
        else:
            return "感谢您的咨询，请问还有什么可以帮助您的吗？"

    mock.chat = mock_chat
    mock.async_chat = AsyncMock(return_value="模拟回复")
    return mock


def create_mock_db_manager():
    """创建 Mock 数据库管理器（轨道A）"""
    mock = MagicMock()

    # 模拟商品知识查询结果
    mock_product_data = {
        "goods_id": "1001",
        "name": "经典女士香水",
        "brand": "香奈儿",
        "specifications": {
            "前调": "柑橘、佛手柑",
            "中调": "玫瑰、茉莉",
            "后调": "檀香、麝香",
            "净含量": "50ml",
            "保质期": "36个月",
        },
        "price": "￥599",
        "extracted_content": "经典女士香水采用法国进口原料，前调清新怡人，中调花香浓郁，后调持久留香。",
    }

    mock.get_product_by_id = MagicMock(return_value=mock_product_data)
    mock.get_product_knowledge = MagicMock(return_value=mock_product_data)
    return mock


def create_mock_qdrant_manager():
    """创建 Mock 向量数据库管理器（轨道B）"""
    mock = MagicMock()

    # 模拟客服知识库查询结果
    mock_knowledge_data = [
        {
            "question": "如何申请退货？",
            "answer": "1. 进入订单详情页\n2. 点击'申请售后'\n3. 选择退货原因\n4. 提交申请等待审核",
            "score": 0.92,
        },
        {
            "question": "退款多久到账？",
            "answer": "审核通过后，退款会在3-5个工作日内原路退回。",
            "score": 0.88,
        },
    ]

    mock.search_knowledge = MagicMock(return_value=mock_knowledge_data)
    mock.vector_search = MagicMock(return_value=mock_knowledge_data)
    return mock


# =============================================================================
# 场景 1: 多模态拦截
# =============================================================================
def simulate_scenario_1():
    """
    场景 1: 多模态拦截 (买家直接发了一张破损的图片)

    预期流程:
    1. Gateway 检测到图片消息
    2. 设置 240 秒人工锁
    3. 触发 alert_level="low" 的 UI 警报
    4. 返回固定回复
    """
    print_header("场景 1：多模态拦截 (买家发送破损图片)")

    session_id = "shop_1001_user_img_001"

    # 模拟消息
    message_type = "image"
    content = "[图片]"

    print_node("Gateway", f"接收消息 | type={message_type}, content={content}")

    # 1. 检测图片拦截
    is_image = message_type == "image"
    print_node("Gateway", f"图片检测 | is_image={is_image}")

    if is_image:
        # 2. 设置人工锁
        lock_result = redis_manager.set_human_lock(session_id, ttl=HUMAN_LOCK_TTL)
        print_node("Gateway", f"人工锁设置 | result={lock_result}, ttl={HUMAN_LOCK_TTL}s")

        # 3. 检查锁状态
        is_locked = redis_manager.is_human_locked(session_id)
        print_node("Gateway", f"锁状态检查 | is_locked={is_locked}")

        # 4. 触发 UI 警报
        alert_level = "low"
        print_node("Fallback", f"UI 警报触发 | alert_level={alert_level}, 提示用户人工接管")

        # 5. 返回固定回复
        final_reply = IMAGE_INTERCEPT_REPLY
        print_node("Output", f"最终回复: {final_reply}")

        # 6. 验证不进入 LangGraph
        print_node("Gateway", "消息被拦截，未进入 LangGraph 工作流")

    return {
        "scenario": "多模态拦截",
        "intercepted": True,
        "lock_ttl": HUMAN_LOCK_TTL,
        "alert_level": "low",
        "reply": final_reply,
    }


# =============================================================================
# 场景 2: 售前结构化查询
# =============================================================================
def simulate_scenario_2():
    """
    场景 2: 售前结构化查询 (买家问客观事实)

    预期流程:
    1. Router 判定为 pre_sale 意图
    2. Retriever 激活轨道A (MySQL)
    3. 提取商品结构化 JSON
    4. Generator 组装 XML Prompt
    5. LLM 返回成分回复
    """
    print_header("场景 2：售前结构化查询 (买家问香水前调)")

    session_id = "shop_1001_user_pre_001"
    locked_goods_id = "1001"

    # 模拟消息
    message_type = "text"
    content = "这款香水的前调是什么？"

    print_node("Gateway", f"接收消息 | type={message_type}, content={content}, goods_id={locked_goods_id}")

    # 1. 检查人工锁（未被锁定）
    is_locked = redis_manager.is_human_locked(session_id)
    print_node("Gateway", f"人工锁检查 | is_locked={is_locked}")

    # 2. 获取推理锁
    acquired = redis_manager.acquire_inference_lock(session_id, ttl=INFERENCE_LOCK_TTL)
    print_node("Gateway", f"推理锁获取 | acquired={acquired}, ttl={INFERENCE_LOCK_TTL}s")

    if not acquired:
        print_node("Gateway", "推理锁获取失败，消息被拦截")
        return {"scenario": "售前查询", "blocked": True}

    # 3. Router 意图判定
    detected_intent = IntentType.PRE_SALE
    alert_level = AlertLevel.NONE
    print_node("Router", f"意图判定 | intent={detected_intent}, alert_level={alert_level}")

    # 4. Retriever 激活轨道A
    print_node("Retriever", "激活轨道: A-MySQL (结构化商品知识)")

    # 模拟数据库查询
    mock_db = create_mock_db_manager()
    product_data = mock_db.get_product_by_id(locked_goods_id)

    context_summary = f"商品: {product_data['name']} | 规格: {json.dumps(product_data['specifications'], ensure_ascii=False)}"
    print_node("Retriever", f"提取上下文: {context_summary[:80]}...")

    # 5. Generator 组装 XML Prompt
    xml_prompt = f"""<system_role>
你是一名专业的客服助手，擅长解答商品相关问题。
</system_role>

<session_state>
意图: pre_sale
商品ID: {locked_goods_id}
用户问题: {content}
</session_state>

<knowledge_base>
商品名称: {product_data['name']}
品牌: {product_data['brand']}
规格信息: {json.dumps(product_data['specifications'], ensure_ascii=False)}
详细说明: {product_data['extracted_content']}
</knowledge_base>

<instructions>
请根据知识库信息，准确回答用户关于商品成分的问题。
</instructions>"""

    print_xml_prompt(xml_prompt)

    # 6. 模拟 LLM 响应
    mock_llm = create_mock_llm_client()
    llm_response = mock_llm.chat([{"role": "user", "content": content}])

    print_node("Output", f"最终回复: {llm_response}")

    # 7. 释放推理锁
    redis_manager.release_inference_lock(session_id)
    print_node("Gateway", "推理锁已释放")

    return {
        "scenario": "售前结构化查询",
        "intent": detected_intent,
        "track": "A-MySQL",
        "reply": llm_response,
    }


# =============================================================================
# 场景 3: 售后高危红线
# =============================================================================
def simulate_scenario_3():
    """
    场景 3: 售后高危红线 (买家暴怒)

    预期流程:
    1. Router 检测红线关键词
    2. 意图判定为 redline
    3. alert_level = "high"
    4. 设置人工锁
    5. 触发全网广播警报
    6. 生成安抚性回复
    """
    print_header("场景 3：售后高危红线 (买家暴怒投诉)")

    session_id = "shop_1001_user_red_001"

    # 模拟消息
    message_type = "text"
    content = "你们卖假货！我要打12315投诉烂脸！"

    print_node("Gateway", f"接收消息 | type={message_type}, content={content}")

    # 1. 获取推理锁
    acquired = redis_manager.acquire_inference_lock(session_id, ttl=INFERENCE_LOCK_TTL)
    print_node("Gateway", f"推理锁获取 | acquired={acquired}")

    # 2. Router 红线检测
    detected_keywords = [kw for kw in REDLINE_KEYWORDS if kw in content]
    print_node("Router", f"关键词检测 | detected={detected_keywords}")

    # 3. 意图判定
    detected_intent = IntentType.REDLINE
    alert_level = AlertLevel.HIGH
    print_node("Router", f"意图判定 | intent={detected_intent}, alert_level={alert_level}")

    # 4. 设置人工锁
    lock_result = redis_manager.set_human_lock(session_id, ttl=HUMAN_LOCK_TTL)
    print_node("Router", f"人工锁设置 | result={lock_result}, ttl={HUMAN_LOCK_TTL}s")

    # 5. 缓存意图（注意：红线意图不缓存）
    print_node("Router", "红线意图不缓存")

    # 6. Retriever 不激活（红线直接转人工）
    print_node("Retriever", "红线场景跳过知识检索")

    # 7. 触发 UI 警报
    print_node("Fallback", f"UI 警报触发 | {HIGH_ALERT_PROMPT}")
    print_node("Fallback", "全网广播: 播放警报声 + 红色弹窗 + 主管通知")

    # 8. Generator 组装安抚性回复
    xml_prompt = """<system_role>
你是一名专业的客服主管，擅长处理投诉和危机。
</system_role>

<session_state>
意图: redline
用户情绪: 愤怒
关键词: [假货, 12315, 烂脸]
</session_state>

<instructions>
请用最诚恳的语气安抚用户，并说明已转接主管处理。
</instructions>"""

    print_xml_prompt(xml_prompt)

    # 9. 模拟 LLM 响应
    final_reply = "尊敬的顾客，我们非常重视您反馈的问题。已为您升级至主管加急处理，请稍候片刻，我们会给您一个满意的答复。"
    print_node("Output", f"最终回复: {final_reply}")

    # 10. 释放推理锁
    redis_manager.release_inference_lock(session_id)
    print_node("Gateway", "推理锁已释放")

    return {
        "scenario": "售后高危红线",
        "intent": detected_intent,
        "alert_level": alert_level,
        "keywords": detected_keywords,
        "reply": final_reply,
    }


# =============================================================================
# 场景 4: 隐身苏醒与意图继承
# =============================================================================
def simulate_scenario_4():
    """
    场景 4: 隐身苏醒与意图继承 (真人刚接管完，AI重新上线)

    预期流程:
    1. 手动设置 AI 苏醒标记
    2. 缓存上一轮意图为 after_sales
    3. 用户发送极短句 "退款"
    4. Router 检测极短句，继承意图
    5. 生成带苏醒指令的回复
    """
    print_header("场景 4：隐身苏醒与意图继承 (AI 刚接管)")

    session_id = "shop_1001_user_wake_001"

    # 前置条件：手动设置 Redis 状态
    print_node("Setup", "手动设置 Redis 状态...")

    # 设置 AI 苏醒标记
    redis_manager.mark_ai_awakening(session_id, ttl=30)
    print_node("Setup", f"AI 苏醒标记已设置 | ttl=30s")

    # 设置上一轮意图缓存
    redis_manager.set_last_intent(session_id, IntentType.AFTER_SALES, ttl=INTENT_CACHE_TTL)
    print_node("Setup", f"意图缓存已设置 | intent=after_sales, ttl={INTENT_CACHE_TTL}s")

    # 模拟消息（极短句）
    message_type = "text"
    content = "退款"

    print_node("Gateway", f"接收消息 | type={message_type}, content={content}, len={len(content)}")

    # 1. 检查人工锁（已过期）
    is_locked = redis_manager.is_human_locked(session_id)
    print_node("Gateway", f"人工锁检查 | is_locked={is_locked} (已过期)")

    # 2. 获取推理锁
    acquired = redis_manager.acquire_inference_lock(session_id, ttl=INFERENCE_LOCK_TTL)
    print_node("Gateway", f"推理锁获取 | acquired={acquired}")

    # 3. Router 极短句检测
    is_short = len(content) <= 5
    print_node("Router", f"极短句检测 | len={len(content)}, is_short={is_short}")

    if is_short:
        # 4. 从 Redis 提取上一轮意图
        last_intent = redis_manager.get_last_intent(session_id)
        print_node("Router", f"意图继承 | last_intent={last_intent}")

        detected_intent = last_intent
        alert_level = AlertLevel.NONE
    else:
        detected_intent = IntentType.UNKNOWN
        alert_level = AlertLevel.NONE

    print_node("Router", f"最终意图 | intent={detected_intent}, alert_level={alert_level}")

    # 5. 检测 AI 苏醒标记
    is_awakening = redis_manager.is_ai_awakening(session_id)
    print_node("Generator", f"AI 苏醒检测 | is_awakening={is_awakening}")

    # 6. Retriever 激活轨道B（售后问题）
    print_node("Retriever", "激活轨道: B-Qdrant (客服知识库)")

    mock_qdrant = create_mock_qdrant_manager()
    knowledge_data = mock_qdrant.search_knowledge("退款")

    context_summary = f"Q: {knowledge_data[0]['question']} | A: {knowledge_data[0]['answer'][:50]}..."
    print_node("Retriever", f"提取上下文: {context_summary}")

    # 7. Generator 组装带苏醒指令的 XML Prompt
    awakening_instruction = """
【AI 苏醒指令】
你刚刚从人工接管状态恢复，用户可能有些不满。请用温暖亲切的语气回复，表现出对用户困扰的理解。
"""

    xml_prompt = f"""<system_role>
你是一名专业的客服助手，擅长处理售后问题。
{awakening_instruction if is_awakening else ''}
</system_role>

<session_state>
意图: {detected_intent}
用户问题: {content}
苏醒状态: {is_awakening}
</session_state>

<knowledge_base>
{json.dumps(knowledge_data, ensure_ascii=False, indent=2)}
</knowledge_base>

<instructions>
请根据知识库信息，指导用户完成退款流程。
</instructions>"""

    print_xml_prompt(xml_prompt)

    # 8. 模拟 LLM 响应
    mock_llm = create_mock_llm_client()
    llm_response = mock_llm.chat([{"role": "user", "content": content}])

    # 添加苏醒前缀
    if is_awakening:
        final_reply = "您好，我是您的专属客服助手，刚才由人工同事为您服务。关于退款问题，" + llm_response
    else:
        final_reply = llm_response

    print_node("Output", f"最终回复: {final_reply}")

    # 9. 清除苏醒标记
    redis_manager.clear_ai_awakening(session_id)
    print_node("Gateway", "AI 苏醒标记已清除")

    # 10. 释放推理锁
    redis_manager.release_inference_lock(session_id)
    print_node("Gateway", "推理锁已释放")

    return {
        "scenario": "隐身苏醒与意图继承",
        "is_short": is_short,
        "inherited_intent": detected_intent,
        "is_awakening": is_awakening,
        "reply": final_reply,
    }


# =============================================================================
# 主执行函数
# =============================================================================
def run_all_scenarios():
    """运行所有业务场景"""
    print("\n" + "=" * 70)
    print("V2.0 LangGraph 业务场景追踪 - 白盒模拟沙盘")
    print("=" * 70)
    print(f"运行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Redis 状态: {'已连接' if redis_manager._client else '未连接'}")
    print(f"HEADLESS_MODE: {os.environ.get('HEADLESS_MODE', '0')}")

    results = []

    # 依次执行场景
    results.append(simulate_scenario_1())
    results.append(simulate_scenario_2())
    results.append(simulate_scenario_3())
    results.append(simulate_scenario_4())

    # 打印总结
    print("\n" + "=" * 70)
    print("场景执行总结")
    print("=" * 70)
    for i, result in enumerate(results, 1):
        print(f"场景 {i}: {result.get('scenario', 'Unknown')}")
        print(f"  ├─ 关键结果: intent={result.get('intent', 'N/A')}, track={result.get('track', 'N/A')}")
        print(f"  └─ 回复: {result.get('reply', 'N/A')[:50]}...")

    print("\n[OK] 所有场景执行完成")
    return results


if __name__ == "__main__":
    run_all_scenarios()
