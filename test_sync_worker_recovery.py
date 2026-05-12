"""
灾难恢复自测脚本

测试 AsyncKnowledgeSyncWorker 的健壮性：
1. 造数据：插入 3 条客服知识记录（is_vectorized=False）
2. 模拟断网：Mock qdrant_manager.upsert_knowledge 抛出 ConnectionError
3. 启动 Worker：展示捕获报错并存活
4. 模拟网络恢复：撤销 Mock
5. 对账成功：展示最终同步成功

运行方式:
    cd E:\develop\customer-agent-refactor
    python test_sync_worker_recovery.py
"""
import sys
import os
import time
import logging
from unittest.mock import patch, MagicMock
from typing import List

# 设置日志格式
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database.models import CustomerServiceKnowledge, Shop, Channel, Base
from database.db_manager import DatabaseManager, get_db_manager
from database.sync_worker import AsyncKnowledgeSyncWorker
from sqlalchemy import text


class MockQdrantManager:
    """模拟 QdrantManager，用于测试"""

    def __init__(self, failure_count: int = 2):
        self.call_count = 0
        self.failure_count = failure_count
        self.success_count = 0

    def upsert_knowledge(self, **kwargs):
        """模拟 upsert_knowledge 方法"""
        self.call_count += 1

        # 前 N 次调用模拟网络故障
        if self.call_count <= self.failure_count:
            logging.error(f"[MockQdrant] 模拟断网，第 {self.call_count} 次调用抛出 ConnectionError")
            raise ConnectionError("Qdrant 网络超时 - 模拟断网")

        # 网络恢复后正常工作
        self.success_count += 1
        logging.info(f"[MockQdrant] 网络恢复，第 {self.call_count} 次调用成功")
        return True

    def health_check(self):
        return True


def setup_test_data(db_manager: DatabaseManager, shop_id: int) -> List[int]:
    """插入 3 条测试数据"""
    test_knowledge = [
        {"title": "退货流程说明", "content": "收到商品后7天内，如有质量问题可申请退货。", "tags": "退货,售后"},
        {"title": "发货时间说明", "content": "下单后24小时内发货，节假日可能延迟。", "tags": "发货,物流"},
        {"title": "会员优惠政策", "content": "会员购买满99元免运费，满199元享95折。", "tags": "会员,优惠"},
    ]

    inserted_ids = []
    with db_manager.session_scope() as session:
        for data in test_knowledge:
            record = CustomerServiceKnowledge(
                shop_id=shop_id,
                title=data["title"],
                content=data["content"],
                tags=data["tags"],
                enabled=True,
                is_vectorized=False,
            )
            session.add(record)
            session.flush()
            inserted_ids.append(record.id)
            logging.info(f"[造数据] 插入知识: id={record.id}, title='{record.title}'")

    return inserted_ids


def verify_sync_status(db_manager: DatabaseManager, knowledge_ids: List[int]) -> dict:
    """验证同步状态"""
    with db_manager.session_scope() as session:
        records = session.query(CustomerServiceKnowledge).filter(
            CustomerServiceKnowledge.id.in_(knowledge_ids)
        ).all()

        return {
            "total": len(records),
            "vectorized": sum(1 for r in records if r.is_vectorized),
            "pending": sum(1 for r in records if not r.is_vectorized),
        }


def cleanup_test_data(db_manager: DatabaseManager, knowledge_ids: List[int]):
    """清理测试数据"""
    with db_manager.session_scope() as session:
        session.query(CustomerServiceKnowledge).filter(
            CustomerServiceKnowledge.id.in_(knowledge_ids)
        ).delete(synchronize_session=False)
        logging.info(f"[清理] 已删除 {len(knowledge_ids)} 条测试数据")


def main():
    """主测试流程"""
    logging.info("=" * 70)
    logging.info("灾难恢复自测脚本启动")
    logging.info("=" * 70)

    # Step 1: 初始化数据库
    logging.info("\n[Step 1] 初始化数据库连接...")
    db_manager = get_db_manager()

    # 执行数据库迁移
    try:
        with db_manager.session_scope() as session:
            session.execute(
                text("ALTER TABLE customer_service_knowledge ADD COLUMN is_vectorized BOOLEAN DEFAULT 0")
            )
        logging.info("[Step 1] 迁移成功：is_vectorized 字段已添加")
    except Exception as e:
        if "duplicate column name" in str(e).lower() or "already exists" in str(e).lower():
            logging.info("[Step 1] 字段已存在，跳过迁移")
        else:
            logging.warning(f"[Step 1] 迁移警告: {e}")

    # Step 2: 获取测试店铺
    logging.info("\n[Step 2] 准备测试店铺...")
    with db_manager.session_scope() as session:
        # 先获取或创建渠道
        channel = session.query(Channel).filter(Channel.channel_name == "pinduoduo").first()
        if not channel:
            channel = Channel(channel_name="pinduoduo", description="测试渠道")
            session.add(channel)
            session.flush()

        shop = session.query(Shop).first()
        if not shop:
            shop = Shop(channel_id=channel.id, shop_id="TEST_001", shop_name="测试店铺")
            session.add(shop)
            session.flush()
        shop_id = shop.id
    logging.info(f"[Step 2] 使用店铺: id={shop_id}")

    # Step 3: 造数据
    logging.info("\n[Step 3] 插入测试数据（3条，is_vectorized=False）...")
    knowledge_ids = setup_test_data(db_manager, shop_id)
    logging.info(f"[Step 3] 成功插入 {len(knowledge_ids)} 条测试数据")

    # Step 4: 初始化 Mock QdrantManager
    logging.info("\n[Step 4] 初始化 Mock QdrantManager...")
    mock_qdrant = MockQdrantManager(failure_count=2)
    logging.info(f"[Step 4] 配置：前 {mock_qdrant.failure_count} 次调用模拟断网")

    # Step 5: 创建同步 Worker
    logging.info("\n[Step 5] 创建 AsyncKnowledgeSyncWorker...")
    worker = AsyncKnowledgeSyncWorker(
        db_manager=db_manager,
        qdrant_manager=mock_qdrant,
    )
    worker.SYNC_INTERVAL = 1
    logging.info("[Step 5] Worker 创建成功")

    # Step 6: 第一次同步（断网场景）
    logging.info("\n" + "=" * 70)
    logging.info("[Step 6] 第一次同步循环（模拟断网）...")
    logging.info("=" * 70)
    worker._sync_batch()

    status_after_first = verify_sync_status(db_manager, knowledge_ids)
    logging.info(f"[Step 6] 同步后状态: 已向量化={status_after_first['vectorized']}, 待同步={status_after_first['pending']}")
    logging.info(f"[Step 6] Qdrant 调用次数: {mock_qdrant.call_count}")

    # Step 7: 第二次同步（网络恢复）
    logging.info("\n" + "=" * 70)
    logging.info("[Step 7] 第二次同步循环（模拟网络恢复）...")
    logging.info("=" * 70)
    worker._sync_batch()

    status_after_second = verify_sync_status(db_manager, knowledge_ids)
    logging.info(f"[Step 7] 同步后状态: 已向量化={status_after_second['vectorized']}, 待同步={status_after_second['pending']}")
    logging.info(f"[Step 7] Qdrant 调用次数: {mock_qdrant.call_count}")

    # Step 8: 最终验证
    logging.info("\n" + "=" * 70)
    logging.info("[Step 8] 最终验证")
    logging.info("=" * 70)
    with db_manager.session_scope() as session:
        records = session.query(CustomerServiceKnowledge).filter(
            CustomerServiceKnowledge.id.in_(knowledge_ids)
        ).all()

        logging.info("\n最终同步状态:")
        for record in records:
            status_icon = "✅" if record.is_vectorized else "❌"
            logging.info(f"  {status_icon} id={record.id}, title='{record.title}', is_vectorized={record.is_vectorized}")

    # Step 9: 清理
    logging.info("\n[Step 9] 清理测试数据...")
    cleanup_test_data(db_manager, knowledge_ids)

    # Step 10: 总结
    logging.info("\n" + "=" * 70)
    logging.info("测试总结")
    logging.info("=" * 70)

    if status_after_second["vectorized"] == 3 and mock_qdrant.success_count >= 3:
        logging.info("✅ 最终一致性架构验证成功！")
        logging.info(f"   - 第一次循环：前 {mock_qdrant.failure_count} 次调用失败（网络故障），Worker 存活")
        logging.info(f"   - 第二次循环：后续调用成功（网络恢复），全部同步完成")
        logging.info(f"   - 总调用次数：{mock_qdrant.call_count} 次")
        logging.info(f"   - 成功次数：{mock_qdrant.success_count} 次")
        logging.info(f"   - 最终状态：{status_after_second['vectorized']}/3 条已向量化")
        return True
    else:
        logging.error("❌ 最终一致性架构验证失败！")
        logging.error(f"   - 已向量化：{status_after_second['vectorized']}/3")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
