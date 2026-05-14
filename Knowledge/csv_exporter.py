"""CSV 导出 — 导出 FastGPT 知识库格式"""
import csv
import os
from datetime import datetime


def export_fastgpt_csv(db_manager, shop_db_id: int, output_path: str = None) -> str:
    from database.models import ProductKnowledge
    if output_path is None:
        output_path = f"./temp/fastgpt_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with db_manager.session_scope() as session:
        products = session.query(ProductKnowledge).filter(
            ProductKnowledge.shop_id == shop_db_id,
            ProductKnowledge.knowledge_status == 'pending'
        ).all()

        with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'goods_id', 'goods_name', 'content'])
            for p in products:
                content_parts = []
                if p.goods_name:
                    content_parts.append(f"商品名称: {p.goods_name}")
                if p.price:
                    content_parts.append(f"价格: {p.price}")
                if p.specifications:
                    content_parts.append(f"规格: {p.specifications}")
                if p.raw_detail_json:
                    content_parts.append(f"详情: {p.raw_detail_json[:2000]}")
                writer.writerow([p.id, p.goods_id, p.goods_name, '\n'.join(content_parts)])

        for p in products:
            p.knowledge_status = 'synced'

    return output_path
