"""High-contrast light theme for the desktop assistant."""
from __future__ import annotations


BG = "#F3F4F6"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#E5E7EB"
BORDER = "#6B7280"
BORDER_SOFT = "#9CA3AF"
TEXT = "#111827"
TEXT_MUTED = "#374151"
PRIMARY = "#1D4ED8"
PRIMARY_HOVER = "#1E40AF"
SUCCESS = "#047857"
WARNING = "#B45309"
DANGER = "#B91C1C"
SELECTION = "#1D4ED8"


FORM_INPUT_STYLE = f"""
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px;
    selection-background-color: {SELECTION};
    selection-color: #ffffff;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 2px solid {PRIMARY};
}}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
    background-color: {SURFACE_ALT};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER_SOFT};
}}
"""


def app_stylesheet() -> str:
    return f"""
QWidget {{
    color: {TEXT};
}}
QFrame {{
    background-color: {BG};
}}
CardWidget {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_SOFT};
    border-radius: 8px;
}}
QLabel {{
    color: {TEXT};
}}
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px;
    selection-background-color: {SELECTION};
    selection-color: #ffffff;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 2px solid {PRIMARY};
}}
QTableView, QTableWidget {{
    background-color: {SURFACE};
    alternate-background-color: #EEF2FF;
    color: {TEXT};
    gridline-color: {BORDER_SOFT};
    selection-background-color: {SELECTION};
    selection-color: #ffffff;
    border: 1px solid {BORDER_SOFT};
}}
QHeaderView::section {{
    background-color: {PRIMARY};
    color: #ffffff;
    border: 1px solid {PRIMARY_HOVER};
    padding: 6px;
    font-weight: 700;
}}
QPushButton {{
    color: {TEXT};
}}
QToolTip {{
    background-color: {TEXT};
    color: #ffffff;
    border: 1px solid {BORDER};
    padding: 4px;
}}
"""


def apply_high_contrast_theme(app) -> None:
    app.setStyleSheet(app_stylesheet())
