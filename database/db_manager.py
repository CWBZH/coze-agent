import os
import uuid
import threading
from contextlib import contextmanager
from datetime import datetime
from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from database.models import (Base, Channel, Shop, Account, ProductKnowledge, Keyword,
                              CustomerServiceKnowledge, AppConfig,
                              Conversation, AgentMessage)
from typing import Any, Dict, List, Optional
from core import settings
from utils.logger_loguru import get_logger


class DatabaseManager:
    """Database manager — 方法签名与 V2.0 完全兼容，返回 dict 而非 ORM 对象。"""

    def __init__(self, db_path: str = None):
        db_file = settings.resolve_path(db_path) if db_path else settings.db_path()
        settings.ensure_dir(db_file.parent)
        self.engine = create_engine(f'sqlite:///{db_file}')
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)
        self.logger = get_logger()
        self.init_db()

    def init_db(self):
        self.add_channel("pinduoduo", "拼多多")

    def get_session(self):
        return self.Session()

    @contextmanager
    def session_scope(self):
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            self.logger.error(f"DB error: {e}")
            raise
        finally:
            session.close()

    # ==================== 私有辅助方法 ====================
    def _get_channel(self, session, channel_name):
        return session.query(Channel).filter(Channel.channel_name == channel_name).first()

    def _get_shop(self, session, channel, shop_id):
        return session.query(Shop).filter(
            Shop.channel_id == channel.id, Shop.shop_id == shop_id
        ).first()

    def _get_account_by_user_id(self, session, shop, user_id):
        return session.query(Account).filter(
            Account.shop_id == shop.id, Account.user_id == user_id
        ).first()

    # ========== Channel ==========
    def add_channel(self, channel_name: str, description: str = None) -> bool:
        with self.session_scope() as session:
            if session.query(Channel).filter(Channel.channel_name == channel_name).first():
                return True
            session.add(Channel(channel_name=channel_name, description=description))
            return True

    def get_channel(self, channel_name: str):
        with self.session_scope() as session:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return None
            return {'id': channel.id, 'channel_name': channel.channel_name, 'description': channel.description}

    def get_all_channels(self):
        with self.session_scope() as session:
            return [
                {'id': c.id, 'channel_name': c.channel_name, 'description': c.description}
                for c in session.query(Channel).all()
            ]

    def delete_channel(self, channel_name: str) -> bool:
        with self.session_scope() as session:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return False
            session.delete(channel)
            return True

    # ========== Shop ==========
    def add_shop(self, channel_name: str, shop_id: str, shop_name: str,
                 shop_logo: str = None, description: str = None,
                 fastgpt_dataset_id: str = None) -> bool:
        with self.session_scope() as session:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                self.logger.error(f"店铺添加失败: 渠道 {channel_name} 不存在")
                return False
            existing = session.query(Shop).filter(
                Shop.channel_id == channel.id, Shop.shop_id == shop_id
            ).first()
            if existing:
                self.logger.warning(f"店铺 {shop_id} 已存在于渠道 {channel_name}")
                return False
            shop = Shop(
                channel_id=channel.id, shop_id=shop_id, shop_name=shop_name,
                shop_logo=shop_logo, description=description,
                fastgpt_dataset_id=fastgpt_dataset_id
            )
            session.add(shop)
            self.logger.info(f"成功添加店铺: {shop_name}({shop_id})")
            return True

    def get_shop(self, channel_name: str, shop_id: str):
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                return None
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                return None
            return {
                'id': shop.id, 'channel_id': shop.channel_id,
                'channel_name': channel_name,
                'shop_id': shop.shop_id, 'shop_name': shop.shop_name,
                'shop_logo': shop.shop_logo, 'description': getattr(shop, 'description', None),
                'fastgpt_dataset_id': getattr(shop, 'fastgpt_dataset_id', None),
            }

    def get_shops(self, channel_name: str = "pinduoduo"):
        return self.get_shops_by_channel(channel_name)

    def get_shops_by_channel(self, channel_name: str):
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                return []
            shops = session.query(Shop).filter(Shop.channel_id == channel.id).all()
            return [
                {
                    'id': shop.id, 'channel_id': shop.channel_id,
                    'channel_name': channel_name,
                    'shop_id': shop.shop_id, 'shop_name': shop.shop_name,
                    'shop_logo': shop.shop_logo, 'description': getattr(shop, 'description', None),
                    'fastgpt_dataset_id': getattr(shop, 'fastgpt_dataset_id', None),
                }
                for shop in shops
            ]

    def get_shop_by_platform_id(self, channel_name: str, shop_id: str):
        return self.get_shop(channel_name, shop_id)

    def get_shop_by_id(self, shop_db_id: int):
        with self.session_scope() as session:
            shop = session.query(Shop).filter(Shop.id == shop_db_id).first()
            if not shop:
                return None
            return {
                'id': shop.id, 'channel_id': shop.channel_id,
                'shop_id': shop.shop_id, 'shop_name': shop.shop_name,
                'shop_logo': shop.shop_logo, 'description': getattr(shop, 'description', None),
                'fastgpt_dataset_id': getattr(shop, 'fastgpt_dataset_id', None),
            }

    def update_shop_info(self, channel_name: str, shop_id: str,
                         shop_name: str = None, shop_logo: str = None,
                         description: str = None,
                         fastgpt_dataset_id: str = None) -> bool:
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                return False
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                return False
            if shop_name is not None:
                shop.shop_name = shop_name
            if shop_logo is not None:
                shop.shop_logo = shop_logo
            if description is not None:
                shop.description = description
            if fastgpt_dataset_id is not None:
                shop.fastgpt_dataset_id = fastgpt_dataset_id
            return True

    def delete_shop(self, channel_name: str, shop_id: str) -> bool:
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                return False
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                return False
            session.delete(shop)
            return True

    # ========== Account ==========
    def add_account(self, channel_name: str, shop_id: str, user_id: str,
                    username: str, password: str, cookies: str = None) -> bool:
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                self.logger.error(f"添加账号失败: 渠道 {channel_name} 不存在")
                return False
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                self.logger.error(f"添加账号失败: 店铺 {shop_id} 不存在")
                return False
            existing = session.query(Account).filter(
                Account.shop_id == shop.id, Account.username == username
            ).first()
            if existing:
                self.logger.warning(f"账号 {username} 已存在于店铺 {shop_id}")
                return False
            account = Account(
                shop_id=shop.id, user_id=user_id, username=username,
                password=password, cookies=cookies, status=None
            )
            session.add(account)
            self.logger.info(f"成功添加账号: {username} 到店铺 {shop_id}")
            return True

    def get_account(self, channel_name: str, shop_id: str, user_id: str):
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                return None
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                return None
            account = self._get_account_by_user_id(session, shop, user_id)
            if not account:
                return None
            return {
                'id': account.id, 'shop_id': account.shop_id,
                'user_id': account.user_id, 'username': account.username,
                'password': account.password, 'cookies': account.cookies,
                'status': account.status,
            }

    def get_accounts(self, channel_name: str, shop_platform_id: str):
        return self.get_accounts_by_shop(channel_name, shop_platform_id)

    def get_accounts_by_shop(self, channel_name: str, shop_id: str):
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                return []
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                return []
            accounts = session.query(Account).filter(Account.shop_id == shop.id).all()
            return [
                {
                    'id': a.id, 'shop_id': a.shop_id,
                    'user_id': a.user_id, 'username': a.username,
                    'password': a.password, 'cookies': a.cookies,
                    'status': a.status,
                }
                for a in accounts
            ]

    def get_all_accounts_with_details(self):
        with self.session_scope() as session:
            results = (
                session.query(Account, Shop, Channel)
                .join(Shop, Account.shop_id == Shop.id)
                .join(Channel, Shop.channel_id == Channel.id)
                .all()
            )
            return [
                {
                    'channel_name': channel.channel_name,
                    'shop_id': shop.shop_id,
                    'shop_name': shop.shop_name,
                    'shop_logo': shop.shop_logo,
                    'username': account.username,
                    'password': account.password,
                    'status': account.status,
                    'user_id': account.user_id,
                    'cookies': account.cookies,
                }
                for account, shop, channel in results
            ]

    def update_account_cookies(self, channel_name: str, shop_id: str, user_id: str, cookies: str) -> bool:
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                return False
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                return False
            account = self._get_account_by_user_id(session, shop, user_id)
            if not account:
                return False
            account.cookies = cookies
            return True

    def update_account_status(self, channel_name: str, shop_id: str, user_id: str, status: int) -> bool:
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                return False
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                return False
            account = self._get_account_by_user_id(session, shop, user_id)
            if not account:
                return False
            account.status = status
            return True

    def update_account_info(self, channel_name: str, shop_id: str, user_id: str,
                            username: str = None, password: str = None,
                            cookies: str = None, status: int = None) -> bool:
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                self.logger.error(f"更新账号失败: 渠道 {channel_name} 不存在")
                return False
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                self.logger.error(f"更新账号失败: 店铺 {shop_id} 不存在")
                return False
            account = self._get_account_by_user_id(session, shop, user_id)
            if not account:
                self.logger.error(f"更新账号失败: 账号 {user_id} 不存在")
                return False
            if username is not None:
                account.username = username
            if password is not None:
                account.password = password
            if cookies is not None:
                account.cookies = cookies
            if status is not None:
                account.status = status
            return True

    def delete_account(self, channel_name: str, shop_id: str, user_id: str) -> bool:
        with self.session_scope() as session:
            channel = self._get_channel(session, channel_name)
            if not channel:
                return False
            shop = self._get_shop(session, channel, shop_id)
            if not shop:
                return False
            account = self._get_account_by_user_id(session, shop, user_id)
            if not account:
                return False
            session.delete(account)
            return True

    # ========== Product Knowledge ==========
    def add_product(self, shop_db_id: int, goods_id: str, goods_name: str, **kwargs) -> ProductKnowledge:
        with self.session_scope() as session:
            existing = session.query(ProductKnowledge).filter(
                ProductKnowledge.shop_id == shop_db_id,
                ProductKnowledge.goods_id == str(goods_id)
            ).first()
            if existing:
                for k, v in kwargs.items():
                    if v is not None and hasattr(existing, k):
                        setattr(existing, k, v)
                return existing
            product = ProductKnowledge(shop_id=shop_db_id, goods_id=str(goods_id),
                                       goods_name=goods_name, **{k: v for k, v in kwargs.items() if v is not None})
            session.add(product)
            session.flush()
            return product

    def get_products(self, shop_db_id: int, status: str = None):
        with self.session_scope() as session:
            q = session.query(ProductKnowledge).filter(ProductKnowledge.shop_id == shop_db_id)
            if status:
                q = q.filter(ProductKnowledge.knowledge_status == status)
            return q.all()

    def get_product_by_goods_id(self, shop_db_id: int, goods_id: str):
        with self.session_scope() as session:
            return session.query(ProductKnowledge).filter(
                ProductKnowledge.shop_id == shop_db_id,
                ProductKnowledge.goods_id == str(goods_id)
            ).first()

    def update_product_status(self, product_ids: list, status: str):
        with self.session_scope() as session:
            session.query(ProductKnowledge).filter(
                ProductKnowledge.id.in_(product_ids)
            ).update({ProductKnowledge.knowledge_status: status}, synchronize_session=False)

    # ========== Keyword ==========
    def add_keyword(self, shop_db_id: int, keyword: str, reply_text: str = None,
                    action: str = 'auto_reply', enabled: bool = True):
        with self.session_scope() as session:
            kw = Keyword(shop_id=shop_db_id, keyword=keyword, reply_text=reply_text,
                        action=action, enabled=enabled)
            session.add(kw)
            session.flush()
            return kw

    def get_keywords(self, shop_db_id: int, enabled_only: bool = True):
        with self.session_scope() as session:
            q = session.query(Keyword).filter(Keyword.shop_id == shop_db_id)
            if enabled_only:
                q = q.filter(Keyword.enabled == True)
            return q.all()

    def delete_keyword(self, keyword_id: int):
        with self.session_scope() as session:
            session.query(Keyword).filter(Keyword.id == keyword_id).delete()

    # ========== AppConfig ==========
    def get_config(self, config_key: str) -> Optional[Dict[str, Any]]:
        with self.session_scope() as session:
            row = session.query(AppConfig).filter(AppConfig.config_key == config_key).first()
            if not row:
                return None
            return {"config_key": row.config_key, "config_value": row.config_value}

    def set_config(self, config_key: str, config_value: str) -> bool:
        with self.session_scope() as session:
            row = session.query(AppConfig).filter(AppConfig.config_key == config_key).first()
            if row:
                row.config_value = config_value
                row.updated_at = datetime.now()
            else:
                session.add(AppConfig(config_key=config_key, config_value=config_value))
            return True

    def delete_config(self, config_key: str) -> bool:
        with self.session_scope() as session:
            session.query(AppConfig).filter(AppConfig.config_key == config_key).delete()
            return True

    def get_configs_by_prefix(self, prefix: str) -> List[Dict[str, Any]]:
        with self.session_scope() as session:
            rows = session.query(AppConfig).filter(
                AppConfig.config_key.like(f"{prefix}%")
            ).all()
            return [{"config_key": r.config_key, "config_value": r.config_value} for r in rows]

    # ========== Conversation ==========
    def get_or_create_conversation(self, shop_db_id: int, buyer_id: str, user_id: str = None):
        with self.session_scope() as session:
            conv = session.query(Conversation).filter(
                Conversation.shop_id == shop_db_id,
                Conversation.buyer_id == buyer_id,
                Conversation.status.in_(['active', 'pending_human'])
            ).order_by(Conversation.created_at.desc()).first()
            if conv:
                return conv
            conv = Conversation(
                session_id=str(uuid.uuid4()),
                shop_id=shop_db_id,
                buyer_id=buyer_id,
                user_id=user_id,
                status='active'
            )
            session.add(conv)
            session.flush()
            return conv

    def get_conversation(self, session_id: str):
        with self.session_scope() as session:
            return session.query(Conversation).filter(Conversation.session_id == session_id).first()

    def update_conversation_status(self, session_id: str, status: str):
        with self.session_scope() as session:
            conv = session.query(Conversation).filter(Conversation.session_id == session_id).first()
            if conv:
                conv.status = status
                conv.updated_at = datetime.now()

    # ========== Agent Message ==========
    def add_message(self, session_id: str, role: str, content: str):
        with self.session_scope() as session:
            msg = AgentMessage(session_id=session_id, role=role, content=content, timestamp=datetime.now())
            session.add(msg)

    def get_messages(self, session_id: str, limit: int = 40):
        with self.session_scope() as session:
            return session.query(AgentMessage).filter(
                AgentMessage.session_id == session_id
            ).order_by(desc(AgentMessage.timestamp)).limit(limit).all()[::-1]

    def count_messages(self, session_id: str) -> int:
        with self.session_scope() as session:
            return session.query(AgentMessage).filter(AgentMessage.session_id == session_id).count()

    def delete_messages(self, message_ids: list):
        with self.session_scope() as session:
            session.query(AgentMessage).filter(AgentMessage.id.in_(message_ids)).delete(synchronize_session=False)


_db_instance = None
_db_lock = threading.Lock()


def get_db_manager() -> "DatabaseManager":
    """Get the DatabaseManager singleton (thread-safe)."""
    global _db_instance
    try:
        from core.di_container import container
        if container.is_registered(DatabaseManager):
            return container.get(DatabaseManager)
    except ImportError:
        pass

    if _db_instance is None:
        with _db_lock:
            if _db_instance is None:
                _db_instance = DatabaseManager()
    return _db_instance


class _LazyDBProxy:
    """Lazy proxy for backward compatibility with legacy code."""

    def __getattr__(self, name: str):
        return getattr(get_db_manager(), name)


db_manager = _LazyDBProxy()
