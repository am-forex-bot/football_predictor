"""Dark modern theme stylesheet for the application."""

DARK_THEME = """
/* ===== Global ===== */
QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
    font-size: 11pt;
}

/* ===== Tab Widget ===== */
QTabWidget::pane {
    border: 1px solid #313244;
    border-radius: 6px;
    background-color: #1e1e2e;
}

QTabBar::tab {
    background-color: #313244;
    color: #a6adc8;
    padding: 10px 24px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 600;
}

QTabBar::tab:selected {
    background-color: #7c3aed;
    color: #ffffff;
}

QTabBar::tab:hover:!selected {
    background-color: #45475a;
}

/* ===== Group Boxes ===== */
QGroupBox {
    background-color: #2a2a3a;
    border: 1px solid #313244;
    border-radius: 8px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    font-size: 12pt;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #cba6f7;
}

/* ===== Buttons ===== */
QPushButton {
    background-color: #7c3aed;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    font-weight: 600;
    min-height: 32px;
}

QPushButton:hover {
    background-color: #6d28d9;
}

QPushButton:pressed {
    background-color: #5b21b6;
}

QPushButton:disabled {
    background-color: #45475a;
    color: #6c7086;
}

QPushButton[danger="true"] {
    background-color: #ef4444;
}

QPushButton[danger="true"]:hover {
    background-color: #dc2626;
}

QPushButton[success="true"] {
    background-color: #22c55e;
}

QPushButton[success="true"]:hover {
    background-color: #16a34a;
}

/* ===== Combo Boxes ===== */
QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 28px;
    color: #cdd6f4;
}

QComboBox:hover {
    border-color: #7c3aed;
}

QComboBox::drop-down {
    border: none;
    width: 30px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #cdd6f4;
    margin-right: 8px;
}

QComboBox QAbstractItemView {
    background-color: #313244;
    border: 1px solid #45475a;
    selection-background-color: #7c3aed;
    selection-color: #ffffff;
    outline: none;
}

/* ===== Spin Boxes ===== */
QSpinBox, QDoubleSpinBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 28px;
    color: #cdd6f4;
}

QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: #7c3aed;
}

/* ===== Tables ===== */
QTableWidget, QTableView {
    background-color: #1e1e2e;
    alternate-background-color: #252536;
    border: 1px solid #313244;
    border-radius: 6px;
    gridline-color: #313244;
    selection-background-color: #7c3aed;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #313244;
    color: #cba6f7;
    padding: 8px;
    border: none;
    border-right: 1px solid #45475a;
    font-weight: 600;
}

/* ===== Text Areas / Log ===== */
QTextEdit, QPlainTextEdit {
    background-color: #181825;
    border: 1px solid #313244;
    border-radius: 6px;
    padding: 8px;
    color: #cdd6f4;
    font-family: "Fira Code", "Consolas", "Courier New", monospace;
    font-size: 10pt;
}

/* ===== Progress Bar ===== */
QProgressBar {
    background-color: #313244;
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    background-color: #7c3aed;
    border-radius: 4px;
}

/* ===== Labels ===== */
QLabel {
    color: #cdd6f4;
    background-color: transparent;
}

QLabel[heading="true"] {
    font-size: 14pt;
    font-weight: 700;
    color: #cba6f7;
}

/* ===== Scrollbars ===== */
QScrollBar:vertical {
    background-color: #1e1e2e;
    width: 10px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #45475a;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background-color: #585b70;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background-color: #1e1e2e;
    height: 10px;
    border: none;
}

QScrollBar::handle:horizontal {
    background-color: #45475a;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #585b70;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ===== Status Bar ===== */
QStatusBar {
    background-color: #181825;
    color: #a6adc8;
    border-top: 1px solid #313244;
    font-size: 10pt;
}
"""
