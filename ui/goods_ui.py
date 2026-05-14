"""商品管理页面 — 商品同步 + CSV 导出"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt, QTimer
from qfluentwidgets import PushButton, ComboBox, StrongBodyLabel, InfoBar, InfoBarPosition
from database.db_manager import get_db_manager
from utils.logger_loguru import get_logger

logger = get_logger("GoodsUI")


class GoodsWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("goods")
        self.db = get_db_manager()
        self._current_shop_id = None
        self._sync_running = False
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 店铺选择
        shop_row = QHBoxLayout()
        shop_row.addWidget(StrongBodyLabel("店铺:"))
        self._shop_combo = ComboBox()
        shop_row.addWidget(self._shop_combo)
        shop_row.addStretch()
        layout.addLayout(shop_row)

        # 操作按钮
        btn_row = QHBoxLayout()
        self._sync_btn = PushButton("同步商品")
        self._sync_btn.clicked.connect(self._on_sync)
        self._export_btn = PushButton("导出 CSV")
        self._export_btn.clicked.connect(self._on_export)
        btn_row.addWidget(self._sync_btn)
        btn_row.addWidget(self._export_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 商品表格
        self._table = QTableWidget()
        self._table.setColumnCount(4)
        self._table.setHorizontalHeaderLabels(["商品ID", "名称", "价格", "同步状态"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table)

    def refresh(self):
        self._load_shops()

    def _load_shops(self):
        shops = self.db.get_shops()
        self._shop_combo.clear()
        for s in shops:
            self._shop_combo.addItem(f"{s.shop_name} ({s.shop_id})", userData=s.id)
        if shops:
            self._shop_combo.setCurrentIndex(0)
            self._load_products()

    def _load_products(self):
        shop_id = self._shop_combo.currentData()
        if not shop_id:
            return
        self._current_shop_id = shop_id
        products = self.db.get_products(shop_id)
        self._table.setRowCount(len(products))
        for i, p in enumerate(products):
            self._table.setItem(i, 0, QTableWidgetItem(p.goods_id))
            self._table.setItem(i, 1, QTableWidgetItem(p.goods_name))
            self._table.setItem(i, 2, QTableWidgetItem(p.price or "-"))
            self._table.setItem(i, 3, QTableWidgetItem(p.knowledge_status))

    def _on_sync(self):
        if self._sync_running:
            return
        shop_id = self._shop_combo.currentData()
        if not shop_id:
            InfoBar.warning(title="提示", content="请先选择店铺", parent=self)
            return
        self._sync_running = True
        self._sync_btn.setEnabled(False)
        self._sync_btn.setText("同步中...")

        # 简单同步：使用 ProductSyncService
        try:
            from Knowledge.product_sync import ProductSyncService
            import asyncio

            shop = self.db.get_shop_by_id(shop_id)
            if not shop:
                InfoBar.error(title="错误", content="店铺未找到", parent=self)
                return

            async def run_sync():
                svc = ProductSyncService(self.db)
                progress = await svc.sync_shop(shop.shop_id, shop.id, "")
                return progress

            loop = asyncio.new_event_loop()
            progress = loop.run_until_complete(run_sync())
            loop.close()

            InfoBar.success(title="同步完成", content=f"成功:{progress.success} 失败:{progress.failed}", parent=self)
            self._load_products()
        except Exception as e:
            logger.error(f"同步失败: {e}")
            InfoBar.error(title="同步失败", content=str(e), parent=self)
        finally:
            self._sync_running = False
            self._sync_btn.setEnabled(True)
            self._sync_btn.setText("同步商品")

    def _on_export(self):
        shop_id = self._shop_combo.currentData()
        if not shop_id:
            InfoBar.warning(title="提示", content="请先选择店铺", parent=self)
            return
        try:
            from Knowledge.csv_exporter import export_fastgpt_csv
            path = export_fastgpt_csv(self.db, shop_id)
            InfoBar.success(title="导出成功", content=f"已导出至: {path}", parent=self)
        except Exception as e:
            logger.error(f"导出失败: {e}")
            InfoBar.error(title="导出失败", content=str(e), parent=self)
