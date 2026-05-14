"""
客户客服系统 V3.0 集成测试

覆盖模块：Database → Session → Keyword → FastGPT → Pipeline

运行方式：
  cd E:\develop\customer-agent-refactor-v3
  python -m pytest tests/test_integration.py -v
  或直接: python tests/test_integration.py
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDatabase(unittest.TestCase):
    """Module 1: Database 层测试"""

    @classmethod
    def setUpClass(cls):
        from database.db_manager import DatabaseManager
        cls.db_path = os.path.join(tempfile.gettempdir(), f"v3_test_{datetime.now().strftime('%H%M%S')}.db")
        cls.db = DatabaseManager(cls.db_path)

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls.db_path)
        except PermissionError:
            pass
        except FileNotFoundError:
            pass

    def test_01_init_db_has_channel(self):
        channel = self.db.get_channel("pinduoduo")
        self.assertIsNotNone(channel)
        self.assertEqual(channel.channel_name, "pinduoduo")

    def test_02_add_shop(self):
        shop = self.db.add_shop("pinduoduo", "pdd_001", "测试店铺A",
                                fastgpt_dataset_id="ds_abc123")
        self.assertIsNotNone(shop)
        self.assertEqual(shop.shop_id, "pdd_001")
        self.assertEqual(shop.fastgpt_dataset_id, "ds_abc123")
        return shop

    def test_03_get_shops(self):
        self.db.add_shop("pinduoduo", "pdd_002", "测试店铺B")
        shops = self.db.get_shops("pinduoduo")
        self.assertGreaterEqual(len(shops), 2)

    def test_04_add_shop_duplicate(self):
        """重复添加应返回已有对象"""
        s1 = self.db.add_shop("pinduoduo", "pdd_001", "测试店铺A")
        s2 = self.db.add_shop("pinduoduo", "pdd_001", "测试店铺A")
        self.assertEqual(s1.id, s2.id)

    def test_05_missing_channel_raises(self):
        with self.assertRaises(ValueError):
            self.db.add_shop("nonexistent", "x", "x")

    def test_06_add_account(self):
        self.db.add_shop("pinduoduo", "pdd_003", "店铺C")
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_003").first()
            shop_id = shop.id
        acct = self.db.add_account("pinduoduo", "pdd_003", "user_1", "测试用户", "pass123")
        self.assertIsNotNone(acct)
        self.assertEqual(acct.username, "测试用户")

    def test_07_missing_account_shop_raises(self):
        with self.assertRaises(ValueError):
            self.db.add_account("pinduoduo", "nonexistent_shop", "u", "u", "p")

    def test_08_add_product(self):
        self.db.add_shop("pinduoduo", "pdd_004", "店铺D")
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_004").first()
            shop_id = shop.id
        p = self.db.add_product(shop_id, "goods_001", "测试商品",
                                price="99.00", price_min=90, price_max=100)
        self.assertIsNotNone(p)
        self.assertEqual(p.goods_name, "测试商品")

    def test_09_product_upsert(self):
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_004").first()
            shop_id = shop.id
        p1 = self.db.add_product(shop_id, "goods_001", "测试商品", price="99.00")
        p2 = self.db.add_product(shop_id, "goods_001", "测试商品(更新)", price="88.00")
        self.assertEqual(p1.id, p2.id)
        self.assertEqual(p2.price, "88.00")

    def test_10_add_keyword(self):
        self.db.add_shop("pinduoduo", "pdd_005", "店铺E")
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_005").first()
            shop_id = shop.id
        kw = self.db.add_keyword(shop_id, "退款", "亲，退款请联系人工客服~", "transfer_human")
        self.assertIsNotNone(kw)
        self.assertEqual(kw.action, "transfer_human")

    def test_11_get_keywords(self):
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_005").first()
            shop_id = shop.id
        kws = self.db.get_keywords(shop_id)
        self.assertGreaterEqual(len(kws), 1)

    def test_12_conversation_flow(self):
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_001").first()
            shop_id = shop.id
        conv = self.db.get_or_create_conversation(shop_id, "buyer_001")
        self.assertIsNotNone(conv)
        self.assertEqual(conv.status, "active")
        self.assertEqual(conv.buyer_id, "buyer_001")
        return conv

    def test_13_add_and_get_messages(self):
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_001").first()
            shop_id = shop.id
        conv = self.db.get_or_create_conversation(shop_id, "buyer_002")
        session_id = conv.session_id
        self.db.add_message(session_id, "user", "你好，请问这个商品有货吗？")
        self.db.add_message(session_id, "assistant", "亲，有货的呢~")
        msgs = self.db.get_messages(session_id)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].content, "你好，请问这个商品有货吗？")

    def test_14_conversation_reuse_active(self):
        """活跃会话应复用而非新建"""
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_001").first()
            shop_id = shop.id
        c1 = self.db.get_or_create_conversation(shop_id, "buyer_003")
        c2 = self.db.get_or_create_conversation(shop_id, "buyer_003")
        self.assertEqual(c1.session_id, c2.session_id)

    def test_15_conversation_status_transition(self):
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_001").first()
            shop_id = shop.id
        conv = self.db.get_or_create_conversation(shop_id, "buyer_004")
        self.db.update_conversation_status(conv.session_id, "pending_human")
        updated = self.db.get_conversation(conv.session_id)
        self.assertEqual(updated.status, "pending_human")

    def test_16_session_manager(self):
        """SessionManager 包装测试"""
        from Session.session_manager import SessionManager
        sm = SessionManager(self.db)
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_001").first()
            shop_id = shop.id
        import asyncio
        conv = asyncio.run(sm.get_or_create_conversation(shop_id, "sm_buyer_001"))
        self.assertIsNotNone(conv)
        sm.set_status(conv.session_id, "pending_human")
        self.assertEqual(sm.count_messages(conv.session_id), 0)

    def test_17_xml_pipeline(self):
        """KeywordHandler 管道测试"""
        from Message.handlers.keyword_handler import KeywordHandler
        kh = KeywordHandler(self.db)
        from database.models import Shop
        with self.db.session_scope() as s:
            shop = s.query(Shop).filter(Shop.shop_id == "pdd_005").first()
            shop_id = shop.id
        # 正常消息 - 无关键词
        result = kh.check(shop_id, "你好，请问价格是多少？")
        self.assertFalse(result["matched"])
        # 关键词消息
        result = kh.check(shop_id, "我要退款")
        self.assertTrue(result["matched"])

    def test_18_set_and_get_config(self):
        """设置和获取配置项"""
        self.db.set_config("test:key1", '{"name": "value"}')
        result = self.db.get_config("test:key1")
        self.assertIsNotNone(result)
        self.assertEqual(result["config_key"], "test:key1")
        self.assertEqual(result["config_value"], '{"name": "value"}')

    def test_19_overwrite_config(self):
        """覆盖已有配置项"""
        self.db.set_config("test:key2", "old_value")
        self.db.set_config("test:key2", "new_value")
        result = self.db.get_config("test:key2")
        self.assertEqual(result["config_value"], "new_value")

    def test_20_get_configs_by_prefix(self):
        """按前缀获取配置"""
        self.db.set_config("shop:001:prompt", "prompt_data")
        self.db.set_config("shop:001:rules", "rules_data")
        self.db.set_config("shop:002:prompt", "other_data")
        results = self.db.get_configs_by_prefix("shop:001:")
        self.assertEqual(len(results), 2)

    def test_21_delete_config(self):
        """删除配置项"""
        self.db.set_config("test:del", "value")
        self.db.delete_config("test:del")
        result = self.db.get_config("test:del")
        self.assertIsNone(result)

    def test_22_config_manager_sqlite_store(self):
        """ConfigManager 通过 SQLite 存储配置"""
        from core.config_manager import config_manager
        instructions = ["测试指令1", "测试指令2"]
        result = config_manager.set_prompt_instructions(instructions, shop_id="test_shop")
        self.assertTrue(result)
        loaded = config_manager.get_prompt_instructions(shop_id="test_shop")
        self.assertEqual(loaded, instructions)

    def test_23_config_manager_returns_defaults(self):
        """ConfigManager 无配置时返回默认值"""
        from core.config_manager import config_manager
        result = config_manager.get_prompt_instructions(shop_id="nonexistent_xyz")
        self.assertGreaterEqual(len(result), 5)
        self.assertIn("请用中文回复", result[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
