from fastapi import HTTPException

from web_api.schemas.products import ProductCoverage, ProductDetail, ProductSummary
from web_api.services.sqlite_readonly import ReadOnlySqlite, parse_json_list_or_text, parse_json_object, pick_text


class ProductService:
    def __init__(self, db: ReadOnlySqlite | None = None) -> None:
        self._db = db or ReadOnlySqlite()

    def list_products(
        self,
        shop_id: str | None = None,
        q: str | None = None,
        version: str | None = None,
        indexed_status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ProductSummary], int, str | None]:
        where: list[str] = []
        params: list[object] = []
        if shop_id:
            where.append("s.shop_id = ?")
            params.append(shop_id)
        if q:
            where.append("(pk.goods_id LIKE ? OR pk.goods_name LIKE ? OR pk.raw_detail_json LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like])
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        offset = max(page - 1, 0) * page_size
        result = self._db.query(
            f"""
            SELECT
                pk.*,
                s.shop_id AS platform_shop_id,
                s.shop_name AS shop_name
            FROM product_knowledge pk
            LEFT JOIN shops s ON s.id = pk.shop_id
            {where_sql}
            ORDER BY pk.updated_at DESC, pk.id DESC
            LIMIT ? OFFSET ?
            """,
            tuple([*params, page_size, offset]),
            required_tables=("product_knowledge",),
        )
        count_result = self._db.query(
            f"""
            SELECT COUNT(*) AS count
            FROM product_knowledge pk
            LEFT JOIN shops s ON s.id = pk.shop_id
            {where_sql}
            """,
            tuple(params),
            required_tables=("product_knowledge",),
        )
        total = int(count_result.rows[0]["count"]) if count_result.rows else 0
        products = [self._row_to_summary(row, version=version, indexed_status=indexed_status) for row in result.rows]
        if indexed_status:
            products = [item for item in products if item.indexed_status == indexed_status]
        return products, total, result.warning or count_result.warning

    def get_product(self, goods_id: str, shop_id: str | None = None) -> ProductDetail:
        where = ["pk.goods_id = ?"]
        params: list[object] = [goods_id]
        if shop_id:
            where.append("s.shop_id = ?")
            params.append(shop_id)
        result = self._db.query(
            f"""
            SELECT
                pk.*,
                s.shop_id AS platform_shop_id,
                s.shop_name AS shop_name
            FROM product_knowledge pk
            LEFT JOIN shops s ON s.id = pk.shop_id
            WHERE {' AND '.join(where)}
            ORDER BY pk.updated_at DESC, pk.id DESC
            LIMIT 2
            """,
            tuple(params),
            required_tables=("product_knowledge",),
        )
        if result.warning:
            raise HTTPException(status_code=404, detail={"status": "not_found", "warning": result.warning})
        if not result.rows:
            raise HTTPException(status_code=404, detail={"status": "not_found", "goods_id": goods_id})
        warning = None
        if not shop_id and len(result.rows) > 1:
            warning = "multiple_products_found_first_returned"
        return self._row_to_detail(result.rows[0], warning=warning)

    def coverage(self, shop_id: str | None = None) -> tuple[ProductCoverage, str | None]:
        where = "WHERE s.shop_id = ?" if shop_id else ""
        params: tuple[object, ...] = (shop_id,) if shop_id else ()
        result = self._db.query(
            f"""
            SELECT
                pk.raw_detail_json,
                pk.price,
                pk.price_min,
                pk.price_max,
                pk.specifications
            FROM product_knowledge pk
            LEFT JOIN shops s ON s.id = pk.shop_id
            {where}
            """,
            params,
            required_tables=("product_knowledge",),
        )
        counters = {
            "total": len(result.rows),
            "has_price": 0,
            "has_specs": 0,
            "has_usage": 0,
            "has_ingredients": 0,
            "has_shelf_life": 0,
            "has_warnings": 0,
            "has_manual_notes": 0,
        }
        for row in result.rows:
            raw = parse_json_object(row.get("raw_detail_json"))
            if row.get("price") or row.get("price_min") or row.get("price_max") or pick_text(raw, "price", "price_range"):
                counters["has_price"] += 1
            if row.get("specifications") or pick_text(raw, "specs", "specifications", "sku_options", "sku_summary"):
                counters["has_specs"] += 1
            if pick_text(raw, "usage", "usage_method", "how_to_use", "use_method"):
                counters["has_usage"] += 1
            if pick_text(raw, "ingredients", "ingredient", "composition"):
                counters["has_ingredients"] += 1
            if pick_text(raw, "shelf_life", "expiry", "expiration", "保质期"):
                counters["has_shelf_life"] += 1
            if pick_text(raw, "warnings", "warning", "notice", "cautions", "注意事项"):
                counters["has_warnings"] += 1
            if pick_text(raw, "manual_notes", "notes", "客服备注"):
                counters["has_manual_notes"] += 1
        return ProductCoverage(**counters), result.warning

    def _row_to_summary(self, row: dict, *, version: str | None = None, indexed_status: str | None = None) -> ProductSummary:
        raw = parse_json_object(row.get("raw_detail_json"))
        specs = parse_json_list_or_text(row.get("specifications") or raw.get("specifications") or raw.get("sku_options"))
        return ProductSummary(
            goods_id=str(row.get("goods_id") or ""),
            goods_name=str(row.get("goods_name") or raw.get("goods_name") or raw.get("title") or ""),
            product_title=str(row.get("goods_name") or raw.get("title") or raw.get("product_title") or ""),
            shop_id=str(row.get("platform_shop_id") or row.get("shop_id") or ""),
            shop_name=str(row.get("shop_name") or ""),
            version=version or "real-product-v1",
            knowledge_status=str(row.get("knowledge_status") or "unknown"),
            indexed_status=indexed_status or "unknown",
            updated_at=str(row.get("updated_at") or ""),
            price=_price(row, raw),
            specs=specs,
            usage=pick_text(raw, "usage", "usage_method", "how_to_use", "use_method"),
            ingredients=pick_text(raw, "ingredients", "ingredient", "composition"),
            shelf_life=pick_text(raw, "shelf_life", "expiry", "expiration", "保质期"),
            warnings=pick_text(raw, "warnings", "warning", "notice", "cautions", "注意事项"),
        )

    def _row_to_detail(self, row: dict, *, warning: str | None = None) -> ProductDetail:
        summary = self._row_to_summary(row)
        raw = parse_json_object(row.get("raw_detail_json"))
        return ProductDetail(
            **summary.model_dump(),
            manual_notes=pick_text(raw, "manual_notes", "notes", "客服备注"),
            raw_detail_json=raw,
            chunks=[],
            warning=warning,
        )


def _price(row: dict, raw: dict) -> str:
    if row.get("price"):
        return str(row["price"])
    if row.get("price_min") is not None or row.get("price_max") is not None:
        return f"{row.get('price_min') or ''}-{row.get('price_max') or ''}".strip("-")
    return pick_text(raw, "price", "price_range", "goods_price")
