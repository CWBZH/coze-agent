from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    TableWidget,
)

from database.db_manager import get_db_manager
from database.models import ProductKnowledge
from ui.theme import FORM_INPUT_STYLE
from utils.logger_loguru import get_logger

logger = get_logger("KnowledgeUI")


MANUAL_FIELDS = [
    ("category", "主类目", "如：止汗喷雾、素颜霜、洗脸巾"),
    ("sku_options", "完整规格/SKU", "一行一个规格，例如：1瓶20ml"),
    ("sku_summary", "默认推荐规格", "如：1瓶20ml"),
    ("effect", "功效卖点", "一行一个，例如：止汗、除臭、清爽"),
    ("usage_method", "使用方法", "如：喷在腋下、颈部等位置"),
    ("usage_duration", "使用时长", "如：一瓶可用一至两个月"),
    ("suitable_age", "适用年龄", "如：12岁以上能用"),
    ("skin_type", "适用肤质/人群", "如：学生、男女通用"),
    ("fragrance", "香味", "如：清新香"),
    ("ingredients", "成分/材质", "如：商品详情明确标注后填写"),
    ("shelf_life", "保质期", "如：三年"),
    ("warnings", "注意事项", "一行一个注意点"),
    ("manual_notes", "人工补充话术", "客服需要知道的额外口径"),
]

MULTILINE_FIELDS = {"sku_options", "effect", "warnings", "manual_notes"}


class ProductEditDialog(QDialog):
    def __init__(self, product: ProductKnowledge, parent=None):
        super().__init__(parent)
        self.product = product
        self.inputs = {}
        self.setWindowTitle("编辑产品知识")
        self.resize(860, 720)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        title = SubtitleLabel(self.product.goods_name or "未命名商品")
        subtitle = CaptionLabel(f"商品ID: {self.product.goods_id}    价格: {self.product.price or '-'}")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        attrs = self._load_manual_attributes()
        for key, label, placeholder in MANUAL_FIELDS:
            if key in MULTILINE_FIELDS:
                editor = QTextEdit()
                editor.setFixedHeight(76 if key != "manual_notes" else 110)
                editor.setPlainText(self._to_text(attrs.get(key)))
                editor.setPlaceholderText(placeholder)
            else:
                editor = QLineEdit()
                editor.setText(self._to_text(attrs.get(key)))
                editor.setPlaceholderText(placeholder)
            editor.setStyleSheet(FORM_INPUT_STYLE)
            self.inputs[key] = editor
            form.addRow(f"{label}:", editor)

        raw = QTextEdit()
        raw.setReadOnly(True)
        raw.setFixedHeight(140)
        raw.setStyleSheet(FORM_INPUT_STYLE)
        raw.setPlainText(self._raw_preview())
        form.addRow("平台原始规格:", raw)

        scroll.setWidget(form_widget)
        layout.addWidget(scroll, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_manual_attributes(self) -> dict:
        data = self._load_raw_detail()
        attrs = data.get("manual_attributes") or data.get("attribute_json") or {}
        return attrs if isinstance(attrs, dict) else {}

    def _load_raw_detail(self) -> dict:
        try:
            data = json.loads(self.product.raw_detail_json or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _raw_preview(self) -> str:
        parts = []
        if self.product.specifications:
            parts.append(self.product.specifications)
        raw = self._load_raw_detail()
        extracted = raw.get("extracted_content")
        if extracted:
            parts.append(str(extracted))
        return "\n\n".join(parts) or "-"

    @staticmethod
    def _to_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return "\n".join(str(item) for item in value if str(item).strip())
        return str(value)

    @staticmethod
    def _to_list(text: str) -> list[str]:
        return [line.strip() for line in text.splitlines() if line.strip()]

    def get_manual_attributes(self) -> dict:
        attrs = {}
        for key, editor in self.inputs.items():
            raw = editor.toPlainText() if isinstance(editor, QTextEdit) else editor.text()
            raw = raw.strip()
            attrs[key] = self._to_list(raw) if key in MULTILINE_FIELDS else raw
        return attrs


class KnowledgeUI(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProductKnowledgeUI")
        self.db = get_db_manager()
        self.current_shop_db_id: int | None = None
        self.current_shop_platform_id: str | None = None
        self.products: list[ProductKnowledge] = []
        self.filtered_products: list[ProductKnowledge] = []
        self._sync_running = False
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(14)

        layout.addWidget(SubtitleLabel("产品知识"))
        layout.addWidget(CaptionLabel("每个产品可填写常问字段，保存后直接导出给 FastGPT 或人工复核。"))

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("店铺"))
        self.shop_combo = ComboBox()
        self.shop_combo.currentIndexChanged.connect(self._on_shop_changed)
        toolbar.addWidget(self.shop_combo, 1)

        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_btn)

        self.sync_btn = PrimaryPushButton("同步产品")
        self.sync_btn.clicked.connect(self._sync_products)
        toolbar.addWidget(self.sync_btn)

        self.export_btn = PushButton("导出 FastGPT CSV")
        self.export_btn.clicked.connect(self._export_csv)
        toolbar.addWidget(self.export_btn)
        layout.addLayout(toolbar)

        dataset_row = QHBoxLayout()
        dataset_row.addWidget(QLabel("FastGPT 知识库ID"))
        self.dataset_edit = QLineEdit()
        self.dataset_edit.setPlaceholderText("每个店铺填写独立 datasetId，用于多店铺隔离")
        self.dataset_edit.setStyleSheet(FORM_INPUT_STYLE)
        dataset_row.addWidget(self.dataset_edit, 1)
        self.save_dataset_btn = PushButton("保存知识库ID")
        self.save_dataset_btn.clicked.connect(self._save_dataset_id)
        dataset_row.addWidget(self.save_dataset_btn)
        layout.addLayout(dataset_row)

        self.status_label = CaptionLabel("未加载")
        layout.addWidget(self.status_label)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("搜索产品"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入商品名、商品ID、类目、SKU/规格")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setStyleSheet(FORM_INPUT_STYLE)
        self.search_edit.textChanged.connect(self._apply_product_filter)
        search_row.addWidget(self.search_edit, 1)
        self.clear_search_btn = PushButton("清空")
        self.clear_search_btn.clicked.connect(self.search_edit.clear)
        search_row.addWidget(self.clear_search_btn)
        layout.addLayout(search_row)

        self.table = TableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["商品ID", "商品名称", "价格", "销量", "状态", "更新时间", "操作"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col in range(2, 7):
            self.table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.table, 1)

    def refresh(self):
        self._load_shops()
        self._load_products()

    def _load_shops(self):
        current_data = self.shop_combo.currentData()
        shops = self.db.get_shops("pinduoduo")
        self.shop_combo.blockSignals(True)
        self.shop_combo.clear()
        for shop in shops:
            self.shop_combo.addItem(f"{shop.get('shop_name') or '未命名店铺'} ({shop.get('shop_id')})", userData=shop)
        if shops:
            index = 0
            if current_data:
                for i, shop in enumerate(shops):
                    if shop.get("id") == current_data.get("id"):
                        index = i
                        break
            self.shop_combo.setCurrentIndex(index)
            self._set_current_shop(shops[index])
        else:
            self.current_shop_db_id = None
            self.current_shop_platform_id = None
        self.shop_combo.blockSignals(False)

    def _on_shop_changed(self, _index: int):
        self._set_current_shop(self.shop_combo.currentData())
        self._load_products()

    def _set_current_shop(self, shop):
        if not shop:
            self.current_shop_db_id = None
            self.current_shop_platform_id = None
            if hasattr(self, "dataset_edit"):
                self.dataset_edit.clear()
            return
        self.current_shop_db_id = int(shop["id"])
        self.current_shop_platform_id = str(shop["shop_id"])
        if hasattr(self, "dataset_edit"):
            self.dataset_edit.setText(str(shop.get("fastgpt_dataset_id") or ""))

    def _load_products(self):
        if not self.current_shop_db_id:
            self.products = []
            self.filtered_products = []
            self.table.setRowCount(0)
            self.status_label.setText("未找到拼多多店铺，请先在店铺管理中添加店铺。")
            return

        self.products = self.db.get_products(self.current_shop_db_id)
        self._apply_product_filter()

    def _apply_product_filter(self):
        keyword = ""
        if hasattr(self, "search_edit"):
            keyword = self.search_edit.text().strip().lower()

        if not keyword:
            self.filtered_products = list(self.products)
        else:
            self.filtered_products = [
                product for product in self.products
                if self._product_matches(product, keyword)
            ]
        self._render_product_table(self.filtered_products)

    def _product_matches(self, product: ProductKnowledge, keyword: str) -> bool:
        fields = [
            product.goods_id,
            product.goods_name,
            product.price,
            product.sold_quantity,
            product.specifications,
            product.knowledge_status,
            product.raw_detail_json,
        ]
        return keyword in "\n".join(str(value or "").lower() for value in fields)

    def _render_product_table(self, products: list[ProductKnowledge]):
        self.table.setRowCount(len(products))
        for row, product in enumerate(products):
            self.table.setItem(row, 0, QTableWidgetItem(str(product.goods_id or "")))
            self.table.setItem(row, 1, QTableWidgetItem(product.goods_name or ""))
            self.table.setItem(row, 2, QTableWidgetItem(str(product.price or "-")))
            self.table.setItem(row, 3, QTableWidgetItem(str(product.sold_quantity or "-")))
            self.table.setItem(row, 4, QTableWidgetItem(product.knowledge_status or "pending"))
            self.table.setItem(row, 5, QTableWidgetItem(self._format_time(product.updated_at)))
            edit_btn = PushButton("编辑知识")
            edit_btn.clicked.connect(lambda _checked=False, p=product: self._edit_product(p))
            self.table.setCellWidget(row, 6, edit_btn)

        if len(products) == len(self.products):
            self.status_label.setText(f"当前店铺共 {len(self.products)} 个产品。")
        else:
            self.status_label.setText(f"搜索结果 {len(products)} / {len(self.products)} 个产品")

    def _save_dataset_id(self):
        shop = self.shop_combo.currentData()
        if not shop:
            self._warning("请先选择店铺")
            return
        dataset_id = self.dataset_edit.text().strip()
        ok = self.db.update_shop_info(
            "pinduoduo",
            str(shop["shop_id"]),
            fastgpt_dataset_id=dataset_id,
        )
        if not ok:
            self._error("知识库ID保存失败")
            return
        shop["fastgpt_dataset_id"] = dataset_id
        self._success("知识库ID已保存，后续问答会按当前店铺路由到该知识库")

    def _edit_product(self, product: ProductKnowledge):
        dialog = ProductEditDialog(product, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        attrs = dialog.get_manual_attributes()
        self._save_manual_attributes(product.id, attrs)
        self._success("产品知识已保存")
        self._load_products()

    def _save_manual_attributes(self, product_id: int, attrs: dict):
        with self.db.session_scope() as session:
            product = session.query(ProductKnowledge).filter(ProductKnowledge.id == product_id).first()
            if not product:
                raise ValueError("产品不存在")
            try:
                raw = json.loads(product.raw_detail_json or "{}")
                if not isinstance(raw, dict):
                    raw = {}
            except Exception:
                raw = {}
            raw["manual_attributes"] = attrs
            raw["manual_updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            product.raw_detail_json = json.dumps(raw, ensure_ascii=False)
            product.knowledge_status = "edited"
            product.updated_at = datetime.now()

    def _sync_products(self):
        if self._sync_running:
            return
        if not self.current_shop_db_id or not self.current_shop_platform_id:
            self._warning("请先选择店铺")
            return

        self._sync_running = True
        self.sync_btn.setEnabled(False)
        self.sync_btn.setText("同步中...")
        try:
            from Knowledge.product_sync import ProductSyncService

            async def run_sync():
                service = ProductSyncService(self.db)
                return await service.sync_shop(self.current_shop_platform_id, self.current_shop_db_id, "")

            loop = asyncio.new_event_loop()
            try:
                progress = loop.run_until_complete(run_sync())
            finally:
                loop.close()

            self._success(f"同步完成：成功 {progress.success}，失败 {progress.failed}。")
            self._load_products()
        except Exception as exc:
            logger.exception(f"产品同步失败: {exc}")
            self._error(f"同步失败：{exc}")
        finally:
            self._sync_running = False
            self.sync_btn.setEnabled(True)
            self.sync_btn.setText("同步产品")

    def _export_csv(self):
        if not self.current_shop_db_id:
            self._warning("请先选择店铺")
            return
        output_path = self._select_csv_output_path()
        if not output_path:
            return
        try:
            from Knowledge.csv_exporter import export_fastgpt_csv

            path = export_fastgpt_csv(self.db, self.current_shop_db_id, output_path=output_path)
            self._save_export_dir(os.path.dirname(path))
            self._success(f"导出成功：{path}")
            self._load_products()
        except Exception as exc:
            logger.exception(f"FastGPT CSV 导出失败: {exc}")
            self._error(f"导出失败：{exc}")

    def _select_csv_output_path(self) -> str:
        default_dir = self._load_export_dir()
        filename = f"fastgpt_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        default_path = os.path.join(default_dir, filename)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 FastGPT CSV",
            default_path,
            "CSV 文件 (*.csv);;所有文件 (*.*)",
        )
        if not file_path:
            return ""
        return file_path if file_path.lower().endswith(".csv") else f"{file_path}.csv"

    def _load_export_dir(self) -> str:
        row = self.db.get_config("product_knowledge:csv_export_dir")
        if row:
            path = row.get("config_value") or ""
            if path and os.path.isdir(path):
                return path
        return os.path.abspath("./temp")

    def _save_export_dir(self, directory: str) -> None:
        if directory:
            self.db.set_config("product_knowledge:csv_export_dir", directory)

    @staticmethod
    def _format_time(value):
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value or "-"

    def _success(self, content: str):
        InfoBar.success(title="完成", content=content, parent=self, position=InfoBarPosition.TOP_RIGHT)

    def _warning(self, content: str):
        InfoBar.warning(title="提示", content=content, parent=self, position=InfoBarPosition.TOP_RIGHT)

    def _error(self, content: str):
        InfoBar.error(title="错误", content=content, parent=self, position=InfoBarPosition.TOP_RIGHT)
