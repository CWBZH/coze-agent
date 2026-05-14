from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean, UniqueConstraint, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Channel(Base):
    __tablename__ = 'channels'
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_name = Column(String(50), unique=True, nullable=False)
    description = Column(String(255))
    shops = relationship('Shop', back_populates='channel', cascade='all, delete-orphan')


class Shop(Base):
    __tablename__ = 'shops'
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey('channels.id'), nullable=False)
    shop_id = Column(String(100), nullable=False)
    shop_name = Column(String(100), nullable=False)
    shop_logo = Column(String(255), nullable=True)
    description = Column(String(255), nullable=True)
    fastgpt_dataset_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    channel = relationship('Channel', back_populates='shops')
    accounts = relationship('Account', back_populates='shop', cascade='all, delete-orphan')


class Account(Base):
    __tablename__ = 'accounts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False)
    user_id = Column(String(100), nullable=False)
    username = Column(String(100), nullable=False)
    password = Column(String(255), nullable=False)
    cookies = Column(Text, nullable=True)
    status = Column(Integer, default=None)
    shop = relationship('Shop', back_populates='accounts')


class ProductKnowledge(Base):
    __tablename__ = 'product_knowledge'
    __table_args__ = (UniqueConstraint('shop_id', 'goods_id', name='uix_product_shop_goods'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id', ondelete='CASCADE'), nullable=False)
    goods_id = Column(String(50), nullable=False)
    goods_name = Column(String(255), nullable=False)
    price = Column(String(50), nullable=True)
    price_min = Column(Integer, nullable=True)
    price_max = Column(Integer, nullable=True)
    sold_quantity = Column(Integer, nullable=True)
    thumb_url = Column(String(500), nullable=True)
    specifications = Column(Text, nullable=True)
    raw_detail_json = Column(Text, nullable=True)
    knowledge_status = Column(String(30), nullable=False, default='pending')
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    shop = relationship('Shop', backref='product_knowledge')


class Keyword(Base):
    __tablename__ = 'keywords'
    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id', ondelete='CASCADE'), nullable=False)
    keyword = Column(String(100), nullable=False)
    reply_text = Column(Text, nullable=True)
    action = Column(String(30), nullable=False, default='auto_reply')
    enabled = Column(Boolean, default=True, nullable=False)
    shop = relationship('Shop', backref='keywords')


class CustomerServiceKnowledge(Base):
    __tablename__ = 'customer_service_knowledge'
    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id', ondelete='CASCADE'), nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    shop = relationship('Shop', backref='customer_service_knowledge')


class AppConfig(Base):
    __tablename__ = 'app_config'
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(255), unique=True, nullable=False, index=True)
    config_value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class Conversation(Base):
    __tablename__ = 'conversations'
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), unique=True, nullable=False, index=True)
    shop_id = Column(Integer, ForeignKey('shops.id', ondelete='CASCADE'), nullable=False)
    buyer_id = Column(String(100), nullable=False)
    user_id = Column(String(100), nullable=True)
    status = Column(String(30), nullable=False, default='active')
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    shop = relationship('Shop', backref='conversations')
    messages = relationship('AgentMessage', back_populates='conversation', cascade='all, delete-orphan')


class AgentMessage(Base):
    __tablename__ = 'agent_messages'
    __table_args__ = (Index('ix_agent_messages_session_timestamp', 'session_id', 'timestamp'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey('conversations.session_id', ondelete='CASCADE'), nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    conversation = relationship('Conversation', back_populates='messages')
