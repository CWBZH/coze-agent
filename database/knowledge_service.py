"""
知识库服务
=============

提供知识库的CRUD操作和检索功能。

V2.0 新增：
- refine_and_store: 将非结构化文本改写为标准QA并存入向量库
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import select, and_, or_, text
from sqlalchemy.orm import Session
import jieba
from utils.logger_loguru import get_logger
from database.models import Base, ProductKnowledge, ProductSearchTerm, CustomerServiceKnowledge, Shop
from database.db_manager import db_manager

# 导入 Qdrant 管理器
from database.qdrant_manager import qdrant_manager

logger = get_logger("KnowledgeService")


class KnowledgeService:
    """知识库服务，提供产品知识和客服知识的CRUD和检索功能"""

    def __init__(self):
        """初始化知识库服务"""
        # 复用现有的数据库管理器，确保路径一致
        self.session_factory = db_manager.Session
        # 确保知识库相关的表存在
        Base.metadata.create_all(db_manager.engine)
        self._ensure_product_knowledge_columns()
        logger.info("KnowledgeService 初始化成功，复用全局数据库连接")

    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.session_factory()

    def _ensure_product_knowledge_columns(self) -> None:
        """兼容已有库，补齐产品结构化知识字段。"""
        columns = {
            "raw_detail_json": "TEXT NULL",
            "attribute_json": "TEXT NULL",
            "attribute_source_json": "TEXT NULL",
            "knowledge_status": "VARCHAR(30) NOT NULL DEFAULT 'pending'",
            "knowledge_version": "INTEGER NOT NULL DEFAULT 1",
        }
        try:
            with db_manager.engine.begin() as conn:
                dialect = db_manager.engine.dialect.name
                if dialect == "sqlite":
                    existing = {
                        row[1] for row in conn.execute(text("PRAGMA table_info(product_knowledge)")).fetchall()
                    }
                else:
                    db_name = conn.execute(text("SELECT DATABASE()")).scalar()
                    existing = {
                        row[0] for row in conn.execute(
                            text(
                                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                                "WHERE TABLE_SCHEMA=:schema AND TABLE_NAME='product_knowledge'"
                            ),
                            {"schema": db_name},
                        ).fetchall()
                    }
                for name, ddl in columns.items():
                    if name not in existing:
                        conn.execute(text(f"ALTER TABLE product_knowledge ADD COLUMN {name} {ddl}"))
                        logger.info(f"产品知识表补齐字段: {name}")
        except Exception as e:
            logger.warning(f"产品知识表字段检查/补齐失败，继续使用现有字段: {e}")

    # ========== 产品知识 ==========

    def get_product_by_goods_id(self, shop_id: int, goods_id: int) -> Optional[ProductKnowledge]:
        """根据商品ID获取产品知识"""
        with self.get_session() as session:
            stmt = select(ProductKnowledge).where(
                and_(
                    ProductKnowledge.shop_id == shop_id,
                    ProductKnowledge.goods_id == goods_id
                )
            )
            return session.scalar(stmt)

    def list_products_by_shop(self, shop_id: int) -> List[ProductKnowledge]:
        """获取店铺所有产品知识"""
        with self.get_session() as session:
            stmt = select(ProductKnowledge).where(
                ProductKnowledge.shop_id == shop_id
            ).order_by(ProductKnowledge.created_at.desc())
            return list(session.scalars(stmt))

    def count_products_by_shop(self, shop_id: int) -> int:
        """统计店铺产品知识数量"""
        with self.get_session() as session:
            return session.query(ProductKnowledge).filter(
                ProductKnowledge.shop_id == shop_id
            ).count()

    def add_or_update_product(
        self,
        shop_id: int,
        goods_id: int,
        goods_name: str,
        price: Optional[str] = None,
        price_min: Optional[int] = None,
        price_max: Optional[int] = None,
        sold_quantity: Optional[int] = None,
        thumb_url: Optional[str] = None,
        specifications: Optional[str] = None,
        extracted_content: Optional[str] = None,
    ) -> ProductKnowledge:
        """添加或更新产品知识"""
        with self.get_session() as session:
            # 在同一个 session 中查询
            stmt = select(ProductKnowledge).where(
                and_(
                    ProductKnowledge.shop_id == shop_id,
                    ProductKnowledge.goods_id == goods_id
                )
            )
            existing = session.scalar(stmt)

            if existing:
                # 更新现有记录
                if goods_name is not None:
                    existing.goods_name = goods_name
                if price is not None:
                    existing.price = price
                if price_min is not None:
                    existing.price_min = price_min
                if price_max is not None:
                    existing.price_max = price_max
                if sold_quantity is not None:
                    existing.sold_quantity = sold_quantity
                if thumb_url is not None:
                    existing.thumb_url = thumb_url
                if specifications is not None:
                    existing.specifications = specifications
                if extracted_content is not None:
                    existing.extracted_content = extracted_content
                existing.last_extracted_at = datetime.now()
                product = existing
                session.flush()
            else:
                # 创建新记录
                product = ProductKnowledge(
                    shop_id=shop_id,
                    goods_id=goods_id,
                    goods_name=goods_name,
                    price=price,
                    price_min=price_min,
                    price_max=price_max,
                    sold_quantity=sold_quantity,
                    thumb_url=thumb_url,
                    specifications=specifications,
                    extracted_content=extracted_content,
                )
                session.add(product)
                session.flush()

            session.commit()
            # 重新查询以确保返回的是附加到 session 的对象
            stmt = select(ProductKnowledge).where(
                and_(
                    ProductKnowledge.shop_id == shop_id,
                    ProductKnowledge.goods_id == goods_id
                )
            )
            result = session.scalar(stmt)
            logger.info(f"产品知识保存成功: shop_id={shop_id}, goods_id={goods_id}")
            return result

    def update_product_extracted_content(
        self,
        shop_id: int,
        goods_id: int,
        specifications: Optional[str] = None,
        extracted_content: Optional[str] = None,
    ) -> bool:
        """仅更新产品的提取内容（用于第二阶段更新）"""
        with self.get_session() as session:
            stmt = select(ProductKnowledge).where(
                and_(
                    ProductKnowledge.shop_id == shop_id,
                    ProductKnowledge.goods_id == goods_id
                )
            )
            product = session.scalar(stmt)
            if not product:
                logger.warning(f"产品不存在，无法更新提取内容: shop_id={shop_id}, goods_id={goods_id}")
                return False

            if specifications is not None:
                product.specifications = specifications
            if extracted_content is not None:
                product.extracted_content = extracted_content
            product.last_extracted_at = datetime.now()

            session.commit()
            logger.info(f"产品提取内容更新成功: shop_id={shop_id}, goods_id={goods_id}")
            return True

    def update_product_knowledge_payload(
        self,
        shop_id: int,
        goods_id: int,
        specifications: Optional[str] = None,
        extracted_content: Optional[str] = None,
        raw_detail_json: Optional[str] = None,
        attribute_json: Optional[str] = None,
        attribute_source_json: Optional[str] = None,
        knowledge_status: str = "extracted",
        knowledge_version: int = 1,
    ) -> bool:
        """更新产品结构化知识 payload。"""
        with self.get_session() as session:
            stmt = select(ProductKnowledge).where(
                and_(
                    ProductKnowledge.shop_id == shop_id,
                    ProductKnowledge.goods_id == goods_id
                )
            )
            product = session.scalar(stmt)
            if not product:
                logger.warning(f"产品不存在，无法更新结构化知识: shop_id={shop_id}, goods_id={goods_id}")
                return False

            if specifications is not None:
                product.specifications = specifications
            if extracted_content is not None:
                product.extracted_content = extracted_content
            if raw_detail_json is not None:
                product.raw_detail_json = raw_detail_json
            if attribute_json is not None:
                product.attribute_json = attribute_json
            if attribute_source_json is not None:
                product.attribute_source_json = attribute_source_json
            product.knowledge_status = knowledge_status
            product.knowledge_version = knowledge_version
            product.last_extracted_at = datetime.now()

            session.commit()
            logger.info(f"产品结构化知识更新成功: shop_id={shop_id}, goods_id={goods_id}, status={knowledge_status}")
            return True

    def replace_product_search_terms(
        self,
        shop_id: int,
        goods_id: int,
        terms: List[Dict[str, Any]],
    ) -> int:
        """替换单个商品的检索词倒排记录。"""
        with self.get_session() as session:
            session.query(ProductSearchTerm).filter(
                ProductSearchTerm.shop_id == shop_id,
                ProductSearchTerm.goods_id == goods_id,
            ).delete(synchronize_session=False)

            inserted = 0
            for item in terms:
                term = str(item.get("term", "")).strip()
                if not term:
                    continue
                session.add(ProductSearchTerm(
                    shop_id=shop_id,
                    goods_id=goods_id,
                    term=term[:100],
                    term_type=str(item.get("term_type", "attribute"))[:30],
                    weight=int(item.get("weight", 10) or 10),
                    source=str(item.get("source", ""))[:100],
                ))
                inserted += 1

            session.commit()
            logger.info(f"商品检索词已更新: shop_id={shop_id}, goods_id={goods_id}, terms={inserted}")
            return inserted

    def list_shop_search_terms(self, shop_id: int) -> List[str]:
        """列出店铺词典，用于运行期长词优先匹配。"""
        with self.get_session() as session:
            rows = session.query(ProductSearchTerm.term).filter(
                ProductSearchTerm.shop_id == shop_id
            ).distinct().all()
            return [row[0] for row in rows if row and row[0]]

    def search_products_by_terms(
        self,
        shop_id: int,
        terms: List[str],
        limit: int = 80,
    ) -> List[Dict[str, Any]]:
        """通过商品词典倒排表召回商品，并返回加权分数。"""
        if not terms:
            return []

        normalized_terms = []
        for term in terms:
            term = str(term).strip().lower()
            if term and term not in normalized_terms:
                normalized_terms.append(term)

        with self.get_session() as session:
            rows = (
                session.query(ProductSearchTerm)
                .filter(
                    ProductSearchTerm.shop_id == shop_id,
                    ProductSearchTerm.term.in_(normalized_terms),
                )
                .all()
            )

            scores: Dict[int, Dict[str, Any]] = {}
            for row in rows:
                bucket = scores.setdefault(row.goods_id, {
                    "score": 0,
                    "matched_terms": [],
                    "term_types": [],
                })
                bucket["score"] += row.weight or 0
                if row.term not in bucket["matched_terms"]:
                    bucket["matched_terms"].append(row.term)
                if row.term_type not in bucket["term_types"]:
                    bucket["term_types"].append(row.term_type)

            if not scores:
                return []

            products = session.query(ProductKnowledge).filter(
                ProductKnowledge.shop_id == shop_id,
                ProductKnowledge.goods_id.in_(list(scores.keys())),
            ).all()

            results = []
            for product in products:
                meta = scores.get(product.goods_id, {})
                results.append({
                    "product": product,
                    "score": meta.get("score", 0),
                    "matched_terms": meta.get("matched_terms", []),
                    "term_types": meta.get("term_types", []),
                })

            results.sort(
                key=lambda item: (
                    item["score"],
                    item["product"].sold_quantity or 0,
                ),
                reverse=True,
            )
            return results[:limit]

    def delete_product(self, product_id: int) -> bool:
        """删除产品知识"""
        with self.get_session() as session:
            product = session.get(ProductKnowledge, product_id)
            if not product:
                return False
            session.query(ProductSearchTerm).filter(
                ProductSearchTerm.shop_id == product.shop_id,
                ProductSearchTerm.goods_id == product.goods_id,
            ).delete(synchronize_session=False)
            session.delete(product)
            session.commit()
            logger.info(f"产品知识删除成功: id={product_id}")
            return True

    def clear_products_by_shop(self, shop_id: int) -> int:
        """清空店铺所有产品知识，返回删除数量"""
        with self.get_session() as session:
            session.query(ProductSearchTerm).filter(
                ProductSearchTerm.shop_id == shop_id
            ).delete(synchronize_session=False)
            count = session.query(ProductKnowledge).filter(
                ProductKnowledge.shop_id == shop_id
            ).delete()
            session.commit()
            logger.info(f"清空店铺产品知识: shop_id={shop_id}, deleted={count}")
            return count

    # ========== 客服知识 ==========

    def get_customer_service_by_id(self, cs_id: int) -> Optional[CustomerServiceKnowledge]:
        """根据ID获取客服知识"""
        with self.get_session() as session:
            return session.get(CustomerServiceKnowledge, cs_id)

    def list_customer_service_by_shop(self, shop_id: int) -> List[CustomerServiceKnowledge]:
        """获取店铺所有启用的客服知识"""
        with self.get_session() as session:
            stmt = select(CustomerServiceKnowledge).where(
                and_(
                    CustomerServiceKnowledge.shop_id == shop_id,
                    CustomerServiceKnowledge.enabled == True
                )
            ).order_by(CustomerServiceKnowledge.created_at.desc())
            return list(session.scalars(stmt))

    def list_customer_service_with_disabled(self, shop_id: int) -> List[CustomerServiceKnowledge]:
        """获取店铺所有客服知识（包括禁用的）"""
        with self.get_session() as session:
            stmt = select(CustomerServiceKnowledge).where(
                CustomerServiceKnowledge.shop_id == shop_id
            ).order_by(CustomerServiceKnowledge.created_at.desc())
            return list(session.scalars(stmt))

    def count_customer_service_by_shop(self, shop_id: int) -> int:
        """统计店铺客服知识数量"""
        with self.get_session() as session:
            return session.query(CustomerServiceKnowledge).filter(
                CustomerServiceKnowledge.shop_id == shop_id
            ).count()

    def add_customer_service(
        self,
        shop_id: int,
        title: str,
        content: str,
        tags: Optional[str] = None,
        enabled: bool = True,
    ) -> CustomerServiceKnowledge:
        """添加客服知识"""
        with self.get_session() as session:
            cs = CustomerServiceKnowledge(
                shop_id=shop_id,
                title=title,
                content=content,
                tags=tags,
                enabled=enabled,
            )
            session.add(cs)
            session.commit()
            logger.info(f"客服知识添加成功: shop_id={shop_id}, title={title}")
            return cs

    def update_customer_service(
        self,
        cs_id: int,
        title: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[CustomerServiceKnowledge]:
        """更新客服知识"""
        with self.get_session() as session:
            cs = session.get(CustomerServiceKnowledge, cs_id)
            if not cs:
                return None
            if title is not None:
                cs.title = title
            if content is not None:
                cs.content = content
            if tags is not None:
                cs.tags = tags
            if enabled is not None:
                cs.enabled = enabled
            session.commit()
            logger.info(f"客服知识更新成功: id={cs_id}")
            return cs

    def delete_customer_service(self, cs_id: int) -> bool:
        """删除客服知识"""
        with self.get_session() as session:
            cs = session.get(CustomerServiceKnowledge, cs_id)
            if not cs:
                return False
            session.delete(cs)
            session.commit()
            logger.info(f"客服知识删除成功: id={cs_id}")
            return True

    def batch_import_customer_service(
        self,
        shop_id: int,
        rows: List[Dict[str, Any]],
    ) -> tuple[int, int]:
        """批量导入客服知识，跳过重复项（同店铺内标题+内容完全相同）

        Args:
            shop_id: 店铺数据库ID
            rows: 待导入行列表，每项含 title, content, tags

        Returns:
            (success_count, skipped_count)
        """
        success = 0
        skipped = 0
        with self.get_session() as session:
            for row in rows:
                title = row.get("title", "")
                content = row.get("content", "")
                tags = row.get("tags")

                # 重复检测：同店铺下标题+内容完全相同
                stmt = select(CustomerServiceKnowledge).where(
                    and_(
                        CustomerServiceKnowledge.shop_id == shop_id,
                        CustomerServiceKnowledge.title == title,
                        CustomerServiceKnowledge.content == content,
                    )
                )
                if session.scalar(stmt) is not None:
                    skipped += 1
                    continue

                cs = CustomerServiceKnowledge(
                    shop_id=shop_id,
                    title=title,
                    content=content,
                    tags=tags,
                    enabled=True,
                )
                session.add(cs)
                success += 1

            session.commit()
        logger.info(f"批量导入客服知识: shop_id={shop_id}, success={success}, skipped={skipped}")
        return success, skipped

    def filter_customer_service_by_tag(self, shop_id: int, tag: str) -> List[CustomerServiceKnowledge]:
        """按标签筛选客服知识"""
        with self.get_session() as session:
            # LIKE 查询匹配标签
            stmt = select(CustomerServiceKnowledge).where(
                and_(
                    CustomerServiceKnowledge.shop_id == shop_id,
                    CustomerServiceKnowledge.enabled == True,
                    CustomerServiceKnowledge.tags.like(f"%{tag}%"),
                )
            ).order_by(CustomerServiceKnowledge.created_at.desc())
            return list(session.scalars(stmt))

    def get_all_tags(self, shop_id: int) -> List[str]:
        """获取店铺所有标签（去重）"""
        with self.get_session() as session:
            stmt = select(CustomerServiceKnowledge.tags).where(
                CustomerServiceKnowledge.shop_id == shop_id
            )
            tags_list = []
            for row in session.execute(stmt):
                if row[0]:
                    tags_list.extend([t.strip() for t in row[0].split(',') if t.strip()])
            # 去重
            return sorted(list(set(tags_list)))

    # ========== 检索 ==========

    def _resolve_shop_id(self, shop_id: int) -> int:
        """
        将店铺原始ID转换为数据库中的Shop.id

        Args:
            shop_id: 店铺原始ID（如591119888）

        Returns:
            数据库中的Shop.id（如1），如果找不到返回原值
        """
        with self.get_session() as session:
            stmt = select(Shop).where(Shop.shop_id == str(shop_id))
            shop = session.scalar(stmt)
            if shop:
                return shop.id
            # 如果没找到，尝试直接用整数查询（兼容已有数据）
            stmt2 = select(Shop).where(Shop.id == shop_id)
            shop2 = session.scalar(stmt2)
            if shop2:
                return shop2.id
            # 找不到时返回原值，让后续查询返回空结果
            logger.warning(f"未找到店铺: shop_id={shop_id}")
            return shop_id

    def search_knowledge(
        self,
        shop_id: int,
        query: Optional[str] = None,
        goods_id: Optional[int] = None,
        limit: int = 10,
    ) -> Dict[str, Any]:
        """
        检索知识库

        Args:
            shop_id: 店铺原始ID
            query: 关键词查询，可为空
            goods_id: 精确查询特定商品，可为空
            limit: 返回结果最大数量

        Returns:
            {
                "product_knowledge": [...],
                "customer_service_knowledge": [...],
            }
        """
        result = {
            "product_knowledge": [],
            "customer_service_knowledge": [],
        }

        # 将店铺原始ID转换为数据库中的Shop.id
        db_shop_id = self._resolve_shop_id(shop_id)

        with self.get_session() as session:
            # 如果指定了 goods_id，精确查询产品知识
            if goods_id is not None:
                product = self.get_product_by_goods_id(db_shop_id, goods_id)
                if product:
                    result["product_knowledge"] = [product]
            # 如果有关键词查询
            elif query and query.strip():
                # 分词
                words = jieba.cut_for_search(query.strip())
                product_conditions = [ProductKnowledge.shop_id == db_shop_id]
                cs_conditions = [
                    CustomerServiceKnowledge.shop_id == db_shop_id,
                    CustomerServiceKnowledge.enabled == True,
                ]

                # 对每个关键词添加 LIKE 条件
                for word in words:
                    if len(word.strip()) >= 2:  # 太短的词忽略
                        product_conditions.append(
                            or_(
                                ProductKnowledge.goods_name.contains(word),
                                ProductKnowledge.extracted_content.contains(word),
                            )
                        )
                        cs_conditions.append(
                            or_(
                                CustomerServiceKnowledge.title.contains(word),
                                CustomerServiceKnowledge.content.contains(word),
                            )
                        )

                # 查询产品知识
                stmt_p = select(ProductKnowledge).where(and_(*product_conditions))\
                    .order_by(ProductKnowledge.created_at.desc())\
                    .limit(limit)
                result["product_knowledge"] = list(session.scalars(stmt_p))

                # 查询客服知识
                stmt_cs = select(CustomerServiceKnowledge).where(and_(*cs_conditions))\
                    .order_by(CustomerServiceKnowledge.created_at.desc())\
                    .limit(limit)
                result["customer_service_knowledge"] = list(session.scalars(stmt_cs))
            else:
                # 没有关键词，返回最新的产品知识和客服知识
                stmt_p = select(ProductKnowledge).where(ProductKnowledge.shop_id == db_shop_id)\
                    .order_by(ProductKnowledge.created_at.desc())\
                    .limit(limit)
                result["product_knowledge"] = list(session.scalars(stmt_p))

                stmt_cs = select(CustomerServiceKnowledge).where(
                    and_(
                        CustomerServiceKnowledge.shop_id == shop_id,
                        CustomerServiceKnowledge.enabled == True,
                    )
                ).order_by(CustomerServiceKnowledge.created_at.desc())\
                    .limit(limit)
                result["customer_service_knowledge"] = list(session.scalars(stmt_cs))

        return result

    def format_search_result(
        self,
        result: Dict[str, Any],
    ) -> str:
        """
        将检索结果格式化为Agent可读的字符串

        Args:
            result: search_knowledge 返回的结果

        Returns:
            格式化后的字符串
        """
        output_parts = []

        products = result.get("product_knowledge", [])
        if products:
            output_parts.append("【产品知识】")
            for i, p in enumerate(products, 1):
                info = []
                info.append(f"{i}. {p.goods_name} (ID: {p.goods_id})")
                if p.price:
                    info.append(f"  价格: {p.price}")
                if p.extracted_content:
                    # 截断避免太长
                    content = p.extracted_content
                    if len(content) > 500:
                        content = content[:500] + "..."
                    info.append(f"  {content}")
                output_parts.append("\n".join(info))
                output_parts.append("")

        cs_list = result.get("customer_service_knowledge", [])
        if cs_list:
            output_parts.append("【客服知识】")
            for i, cs in enumerate(cs_list, 1):
                info = []
                info.append(f"{i}. {cs.title}")
                content = cs.content
                if len(content) > 300:
                    content = content[:300] + "..."
                info.append(f"  {content}")
                output_parts.append("\n".join(info))
                output_parts.append("")

        if not output_parts:
            return "未找到相关知识。"

        return "\n".join(output_parts).strip()

    def get_all_shops(self) -> List[Shop]:
        """获取所有店铺列表（用于UI选择器）"""
        with self.get_session() as session:
            stmt = select(Shop).order_by(Shop.shop_name.asc())
            return list(session.scalars(stmt))

    # ========== V2.0 新增：非结构化知识入库 ==========

    def refine_and_store(
        self,
        shop_id: int,
        raw_text: str,
        intent_domain: str = "after_sales",
        source: str = "merchant_input",
    ) -> Dict[str, Any]:
        """
        将非结构化文本改写为标准QA并存入向量库

        Args:
            shop_id: 店铺ID
            raw_text: 商家输入的非结构化文本（如："漏液发照片补发"）
            intent_domain: 意图域（默认 after_sales）
            source: 知识来源标识

        Returns:
            {
                "success": bool,
                "question": str,  # 改写后的问题
                "answer": str,    # 改写后的答案
                "error": Optional[str],
            }
        """
        try:
            # Step 1: 调用 LLM 改写为标准 QA
            qa_pair = self._refine_to_qa(raw_text)
            if not qa_pair:
                return {
                    "success": False,
                    "question": "",
                    "answer": "",
                    "error": "LLM 改写失败",
                }

            question = qa_pair.get("question", "")
            answer = qa_pair.get("answer", "")

            if not question or not answer:
                return {
                    "success": False,
                    "question": question,
                    "answer": answer,
                    "error": "改写结果不完整",
                }

            # Step 2: 存入 Qdrant 向量库
            success = qdrant_manager.upsert_knowledge(
                shop_id=str(shop_id),
                intent_domain=intent_domain,
                question=question,
                answer=answer,
                source=source,
            )

            if success:
                logger.info(
                    f"知识入库成功: shop_id={shop_id}, domain={intent_domain}, "
                    f"Q={question[:30]}..."
                )
                return {
                    "success": True,
                    "question": question,
                    "answer": answer,
                    "error": None,
                }
            else:
                return {
                    "success": False,
                    "question": question,
                    "answer": answer,
                    "error": "Qdrant 写入失败",
                }

        except Exception as e:
            logger.error(f"refine_and_store 失败: {e}")
            return {
                "success": False,
                "question": "",
                "answer": "",
                "error": str(e),
            }

    def _refine_to_qa(self, raw_text: str) -> Optional[Dict[str, str]]:
        """
        调用 LLM 将非结构化文本改写为标准 QA 对

        Args:
            raw_text: 非结构化文本

        Returns:
            {"question": "...", "answer": "..."} 或 None
        """
        try:
            # 尝试从 DI 容器获取 LLM 客户端
            try:
                from core.di_container import container
                from Agent.CustomerAgent.custom.customer_agent import CustomerAgent
                bot = container.get(CustomerAgent)
                if bot and hasattr(bot, 'llm_client'):
                    llm = bot.llm_client
                else:
                    llm = None
            except Exception:
                llm = None

            if llm is None:
                # 降级：使用简单规则改写
                logger.warning("LLM 客户端不可用，使用简单规则改写")
                return self._simple_refine(raw_text)

            # 构造 Prompt
            prompt = f"""请将以下非结构化的客服知识改写为标准的问答对格式。

原始文本：
{raw_text}

要求：
1. 提取核心问题，以"Q: "开头
2. 提取核心答案，以"A: "开头
3. 保持简洁，问题不超过20字，答案不超过100字
4. 如果原文不完整，请根据常识补充

请直接输出改写结果，格式如下：
Q: [问题]
A: [答案]"""

            # 调用 LLM
            if hasattr(llm, 'chat'):
                response = llm.chat(prompt)
            elif hasattr(llm, 'invoke'):
                response = llm.invoke(prompt)
            elif hasattr(llm, 'generate'):
                response = llm.generate(prompt)
            else:
                logger.warning("LLM 客户端不支持已知接口，使用简单规则改写")
                return self._simple_refine(raw_text)

            # 解析 LLM 响应
            response_text = response if isinstance(response, str) else str(response)
            return self._parse_qa_response(response_text)

        except Exception as e:
            logger.error(f"LLM 改写失败: {e}，使用简单规则改写")
            return self._simple_refine(raw_text)

    def _simple_refine(self, raw_text: str) -> Dict[str, str]:
        """
        简单规则改写（降级方案）

        将 "漏液发照片补发" 改写为：
        Q: 漏液怎么办？
        A: 发照片补发
        """
        # 常见关键词映射
        keyword_to_question = {
            "漏液": "漏液怎么办？",
            "破损": "破损怎么办？",
            "少件": "少件怎么办？",
            "发错": "发错货怎么办？",
            "退货": "如何退货？",
            "退款": "如何退款？",
            "换货": "如何换货？",
            "发票": "如何开发票？",
            "物流": "物流问题怎么处理？",
            "快递": "快递问题怎么处理？",
        }

        # 尝试匹配关键词
        for keyword, question in keyword_to_question.items():
            if keyword in raw_text:
                # 提取答案部分（去除关键词后的内容）
                answer = raw_text.replace(keyword, "", 1).strip()
                if not answer:
                    answer = raw_text
                return {
                    "question": question,
                    "answer": answer,
                }

        # 无法匹配时，使用通用格式
        return {
            "question": f"{raw_text[:10]}怎么处理？" if len(raw_text) > 10 else f"{raw_text}怎么处理？",
            "answer": raw_text,
        }

    def _parse_qa_response(self, response_text: str) -> Optional[Dict[str, str]]:
        """
        解析 LLM 响应为 QA 对

        Args:
            response_text: LLM 返回的文本

        Returns:
            {"question": "...", "answer": "..."} 或 None
        """
        import re

        # 尝试匹配 Q: ... A: ... 格式
        q_match = re.search(r'Q[:：]\s*(.+?)(?=A[:：]|$)', response_text, re.DOTALL)
        a_match = re.search(r'A[:：]\s*(.+?)$', response_text, re.DOTALL)

        if q_match and a_match:
            question = q_match.group(1).strip()
            answer = a_match.group(1).strip()
            return {
                "question": question,
                "answer": answer,
            }

        # 尝试按行分割
        lines = [line.strip() for line in response_text.split('\n') if line.strip()]
        if len(lines) >= 2:
            # 假设第一行是问题，第二行是答案
            question = lines[0].replace("Q:", "").replace("Q：", "").strip()
            answer = lines[1].replace("A:", "").replace("A：", "").strip()
            return {
                "question": question,
                "answer": answer,
            }

        return None
