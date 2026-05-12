"""
Qdrant 向量数据库管理器

实现双轨定向检索：
- 轨道 A：售前问题 → 结构化数据（MySQL/缓存）
- 轨道 B：售后/规则问题 → 向量检索（Qdrant）

核心功能：
- 初始化 Collection
- 向量检索（强制 shop_id + intent_domain 元数据过滤）
- 知识入库
"""
from __future__ import annotations

import os
from typing import Optional, List, Dict, Any
from utils.logger_loguru import get_logger

logger = get_logger("QdrantManager")

# Qdrant 配置
QDRANT_CONFIG = {
    "host": os.getenv("QDRANT_HOST", "localhost"),
    "port": int(os.getenv("QDRANT_PORT", 6333)),
    "api_key": os.getenv("QDRANT_API_KEY", None),
    "collection_name": os.getenv("QDRANT_COLLECTION", "shop_knowledge"),
}

# 向量维度（使用 all-MiniLM-L6-v2 模型，384 维）
VECTOR_SIZE = 384


class QdrantManager:
    """
    Qdrant 向量数据库管理器（单例模式）

    用于知识库的向量检索，支持 SaaS 隔离。
    """

    _instance: Optional['QdrantManager'] = None
    _client = None
    _embedding_model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is not None:
            return

        self._connect()

    def _connect(self):
        """连接 Qdrant 并初始化 Collection"""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models

            # 创建客户端
            if QDRANT_CONFIG["api_key"]:
                self._client = QdrantClient(
                    host=QDRANT_CONFIG["host"],
                    port=QDRANT_CONFIG["port"],
                    api_key=QDRANT_CONFIG["api_key"],
                )
            else:
                self._client = QdrantClient(
                    host=QDRANT_CONFIG["host"],
                    port=QDRANT_CONFIG["port"],
                )

            # 初始化 Collection
            self._init_collection()

            logger.info(
                f"Qdrant 连接成功: {QDRANT_CONFIG['host']}:{QDRANT_CONFIG['port']}"
            )

        except ImportError:
            logger.error("qdrant-client 未安装，请运行: pip install qdrant-client")
            self._client = None
        except Exception as e:
            logger.error(f"Qdrant 连接失败: {e}")
            self._client = None

    def _init_collection(self):
        """初始化 Collection（不存在则创建）"""
        from qdrant_client.http import models

        collection_name = QDRANT_CONFIG["collection_name"]

        try:
            # 检查 Collection 是否存在
            collections = self._client.get_collections().collections
            collection_names = [c.name for c in collections]

            if collection_name not in collection_names:
                # 创建 Collection
                self._client.create_collection(
                    collection_name=collection_name,
                    vectors_config=models.VectorParams(
                        size=VECTOR_SIZE,
                        distance=models.Distance.COSINE,
                    ),
                )
                logger.info(f"Collection '{collection_name}' 创建成功")

                # 创建 payload 索引（用于元数据过滤）
                self._client.create_payload_index(
                    collection_name=collection_name,
                    field_name="shop_id",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                self._client.create_payload_index(
                    collection_name=collection_name,
                    field_name="intent_domain",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
                logger.info("Payload 索引创建成功: shop_id, intent_domain")
            else:
                logger.debug(f"Collection '{collection_name}' 已存在")

        except Exception as e:
            logger.error(f"初始化 Collection 失败: {e}")

    def _get_embedding(self, text: str) -> List[float]:
        """
        获取文本的向量嵌入

        使用 sentence-transformers 模型（本地运行，无 API 调用）
        """
        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
                logger.debug("Embedding 模型加载成功: all-MiniLM-L6-v2")
            except ImportError:
                logger.warning("sentence-transformers 未安装，使用简单哈希向量")
                # 降级：使用简单哈希生成伪向量（仅用于测试）
                import hashlib
                hash_obj = hashlib.md5(text.encode())
                hash_bytes = hash_obj.digest()
                vector = [float(b) / 255.0 for b in hash_bytes[:VECTOR_SIZE]]
                # 补齐到 VECTOR_SIZE
                while len(vector) < VECTOR_SIZE:
                    vector.extend(vector[:VECTOR_SIZE - len(vector)])
                return vector[:VECTOR_SIZE]

        try:
            embedding = self._embedding_model.encode(text)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"生成向量失败: {e}")
            return [0.0] * VECTOR_SIZE

    def search_knowledge(
        self,
        shop_id: str,
        intent_domain: str,
        query: str,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        向量检索知识（强制元数据过滤）

        Args:
            shop_id: 店铺ID（SaaS 隔离）
            intent_domain: 意图域（如 after_sales, general_rules）
            query: 用户查询
            top_k: 返回结果数量

        Returns:
            检索结果列表，每个元素包含 content 和 score
        """
        if self._client is None:
            logger.warning("Qdrant 未连接，返回空结果")
            return []

        try:
            from qdrant_client.http import models

            # 生成查询向量
            query_vector = self._get_embedding(query)

            # 构建元数据过滤器（双重过滤）
            filter_condition = models.Filter(
                must=[
                    models.FieldCondition(
                        key="shop_id",
                        match=models.MatchValue(value=str(shop_id)),
                    ),
                    models.FieldCondition(
                        key="intent_domain",
                        match=models.MatchValue(value=intent_domain),
                    ),
                ]
            )

            # 执行检索 - 使用 query_points 替代 search (qdrant-client >= 1.6.0)
            results = self._client.query_points(
                collection_name=QDRANT_CONFIG["collection_name"],
                query=query_vector,
                query_filter=filter_condition,
                limit=top_k,
                with_payload=True,
            )

            # 格式化结果
            knowledge_list = []
            for hit in results.points:
                knowledge_list.append({
                    "content": hit.payload.get("content", ""),
                    "question": hit.payload.get("question", ""),
                    "answer": hit.payload.get("answer", ""),
                    "score": hit.score,
                    "metadata": {
                        "shop_id": hit.payload.get("shop_id"),
                        "intent_domain": hit.payload.get("intent_domain"),
                        "source": hit.payload.get("source"),
                    },
                })

            logger.info(
                f"向量检索完成: shop_id={shop_id}, domain={intent_domain}, "
                f"results={len(knowledge_list)}, top_score={knowledge_list[0]['score'] if knowledge_list else 0:.3f}"
            )

            return knowledge_list

        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            return []

    def upsert_knowledge(
        self,
        shop_id: str,
        intent_domain: str,
        question: str,
        answer: str,
        source: str = "manual",
        knowledge_id: Optional[str] = None,
    ) -> bool:
        """
        插入或更新知识条目

        Args:
            shop_id: 店铺ID
            intent_domain: 意图域
            question: 问题文本
            answer: 答案文本
            source: 知识来源
            knowledge_id: 知识ID（可选，用于更新）

        Returns:
            是否成功
        """
        if self._client is None:
            return False

        try:
            from qdrant_client.http import models
            import uuid

            # 生成向量
            text_to_embed = f"{question} {answer}"
            vector = self._get_embedding(text_to_embed)

            # 生成 ID
            point_id = knowledge_id or str(uuid.uuid4())

            # 构建 payload
            payload = {
                "shop_id": str(shop_id),
                "intent_domain": intent_domain,
                "question": question,
                "answer": answer,
                "content": f"Q: {question}\nA: {answer}",
                "source": source,
            }

            # 插入/更新
            self._client.upsert(
                collection_name=QDRANT_CONFIG["collection_name"],
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload,
                    )
                ],
            )

            logger.info(f"知识入库成功: id={point_id}, shop_id={shop_id}, domain={intent_domain}")
            return True

        except Exception as e:
            logger.error(f"知识入库失败: {e}")
            return False

    def upsert_product_attribute_chunk(
        self,
        shop_id: str,
        goods_id: str,
        field_name: str,
        sub_intent: str,
        content: str,
        source: str = "product_sync",
        knowledge_version: int = 1,
    ) -> bool:
        """写入当前商品属性语义片段，供当前商品混合检索兜底。"""
        if self._client is None or not content:
            return False

        try:
            from qdrant_client.http import models
            import hashlib

            point_seed = f"{shop_id}:{goods_id}:{field_name}:{knowledge_version}"
            point_id = hashlib.md5(point_seed.encode("utf-8")).hexdigest()
            question = f"{field_name} {sub_intent}"
            vector = self._get_embedding(f"{question} {content}")
            intent_domain = f"product_attribute:{goods_id}:{sub_intent}"

            payload = {
                "shop_id": str(shop_id),
                "goods_id": str(goods_id),
                "intent_domain": intent_domain,
                "doc_type": "product_attribute",
                "field_name": field_name,
                "sub_intent": sub_intent,
                "question": question,
                "answer": content,
                "content": content,
                "source": source,
                "knowledge_version": knowledge_version,
            }

            self._client.upsert(
                collection_name=QDRANT_CONFIG["collection_name"],
                points=[
                    models.PointStruct(
                        id=point_id,
                        vector=vector,
                        payload=payload,
                    )
                ],
            )
            logger.info(
                f"产品属性向量入库成功: shop_id={shop_id}, goods_id={goods_id}, "
                f"field={field_name}, sub_intent={sub_intent}"
            )
            return True
        except Exception as e:
            logger.error(f"产品属性向量入库失败: {e}")
            return False

    def delete_by_shop(self, shop_id: str) -> bool:
        """
        删除指定店铺的所有知识

        Args:
            shop_id: 店铺ID

        Returns:
            是否成功
        """
        if self._client is None:
            return False

        try:
            from qdrant_client.http import models

            self._client.delete(
                collection_name=QDRANT_CONFIG["collection_name"],
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="shop_id",
                                match=models.MatchValue(value=str(shop_id)),
                            )
                        ]
                    )
                ),
            )

            logger.info(f"已删除店铺 {shop_id} 的所有知识")
            return True

        except Exception as e:
            logger.error(f"删除知识失败: {e}")
            return False

    def health_check(self) -> bool:
        """
        健康检查

        Returns:
            Qdrant 是否可用
        """
        if self._client is None:
            return False

        try:
            self._client.get_collections()
            return True
        except Exception:
            return False


# 全局单例
qdrant_manager = QdrantManager()
