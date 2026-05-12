"""
Qdrant 向量库流水线验证脚本

测试流程：
1. 连接 Qdrant (localhost:6333)
2. 调用 refine_and_store 处理口语化描述
3. 调用 search_knowledge 检索并打印结果
"""
import sys
import os
import io

# 设置标准输出为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.qdrant_manager import qdrant_manager
from database.knowledge_service import KnowledgeService


def test_qdrant_connection():
    """测试 Qdrant 连接"""
    print("\n" + "=" * 60)
    print("Step 0: 测试 Qdrant 连接")
    print("=" * 60)

    if qdrant_manager.health_check():
        print("[OK] Qdrant 连接成功 (localhost:6333)")
        return True
    else:
        print("[FAIL] Qdrant 连接失败，请确保 Docker 容器正在运行")
        print("   启动命令: docker run -p 6333:6333 qdrant/qdrant")
        print("   或者使用 Docker Desktop 启动 Qdrant 容器")
        return False


def test_refine_and_store():
    """测试知识提纯入库"""
    print("\n" + "=" * 60)
    print("Step 1: 测试 refine_and_store (知识提纯入库)")
    print("=" * 60)

    service = KnowledgeService()

    # Mock 数据
    shop_id = "test_shop_001"
    raw_text = "如果客户说香水瓶子碎了，让他拍个包装盒和碎玻璃的照片，咱们给补发"
    intent_domain = "after_sales"

    print(f"\n[INPUT] 输入:")
    print(f"   shop_id: {shop_id}")
    print(f"   intent_domain: {intent_domain}")
    print(f"   raw_text: {raw_text}")

    # 调用提纯入库
    result = service.refine_and_store(
        shop_id=shop_id,
        raw_text=raw_text,
        intent_domain=intent_domain,
        source="test_script",
    )

    print(f"\n[OUTPUT] 提纯结果:")
    print(f"   success: {result.get('success')}")
    print(f"   question: {result.get('question')}")
    print(f"   answer: {result.get('answer')}")
    print(f"   error: {result.get('error')}")

    return result.get("success", False), shop_id, intent_domain


def test_search_knowledge(shop_id: str, intent_domain: str):
    """测试向量检索"""
    print("\n" + "=" * 60)
    print("Step 2: 测试 search_knowledge (向量检索)")
    print("=" * 60)

    # 测试查询
    queries = [
        "香水瓶碎了怎么办",
        "香水破了能补发吗",
        "商品破损怎么处理",
    ]

    for query in queries:
        print(f"\n[SEARCH] 查询: {query}")

        results = qdrant_manager.search_knowledge(
            shop_id=shop_id,
            intent_domain=intent_domain,
            query=query,
            top_k=3,
        )

        if results:
            print(f"   找到 {len(results)} 条结果:")
            for i, result in enumerate(results, 1):
                score = result.get("score", 0)
                question = result.get("question", "")
                answer = result.get("answer", "")
                print(f"\n   [{i}] 相关度: {score:.4f}")
                print(f"       Q: {question}")
                print(f"       A: {answer}")
        else:
            print("   [FAIL] 未找到结果")


def test_multi_tenant_isolation():
    """测试多租户隔离"""
    print("\n" + "=" * 60)
    print("Step 3: 测试多租户隔离")
    print("=" * 60)

    service = KnowledgeService()

    # 为另一个店铺插入知识
    print("\n[INPUT] 为 test_shop_002 插入测试知识...")
    result = service.refine_and_store(
        shop_id="test_shop_002",
        raw_text="衣服尺码不对可以换，但要保持吊牌完整",
        intent_domain="after_sales",
        source="test_script",
    )
    print(f"   插入结果: {result.get('success')}")

    # 用 test_shop_001 的 query 搜索 test_shop_002 的数据
    print("\n[SEARCH] 用 test_shop_001 的身份搜索...")
    results = qdrant_manager.search_knowledge(
        shop_id="test_shop_001",
        intent_domain="after_sales",
        query="尺码不对怎么办",
        top_k=3,
    )

    if results:
        print(f"   [WARN] 警告：找到了结果（应该找不到）")
        for r in results:
            print(f"      - {r.get('question')}")
    else:
        print("   [PASS] 隔离验证通过：test_shop_001 无法搜索到 test_shop_002 的数据")


def cleanup_test_data():
    """清理测试数据"""
    print("\n" + "=" * 60)
    print("Step 4: 清理测试数据")
    print("=" * 60)

    for shop_id in ["test_shop_001", "test_shop_002"]:
        success = qdrant_manager.delete_by_shop(shop_id)
        if success:
            print(f"   [OK] 已删除 {shop_id} 的测试数据")
        else:
            print(f"   [FAIL] 删除 {shop_id} 失败")


def main():
    print("\n" + "=" * 60)
    print("Qdrant 向量库流水线验证测试")
    print("=" * 60)

    # Step 0: 测试连接
    if not test_qdrant_connection():
        print("\n[FAIL] 测试终止：Qdrant 未连接")
        return

    try:
        # Step 1: 测试提纯入库
        success, shop_id, intent_domain = test_refine_and_store()
        if not success:
            print("\n[FAIL] 提纯入库失败")
            return

        # Step 2: 测试检索
        test_search_knowledge(shop_id, intent_domain)

        # Step 3: 测试多租户隔离
        test_multi_tenant_isolation()

    finally:
        # Step 4: 清理测试数据
        cleanup_test_data()

    print("\n" + "=" * 60)
    print("[DONE] 所有测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
