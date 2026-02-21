"""Main application window with tab navigation."""

from PyQt6.QtWidgets import QMainWindow, QTabWidget, QStatusBar
from PyQt6.QtCore import Qt

from gui.download_tab import DownloadTab
from gui.prediction_tab import PredictionTab
from gui.backtest_tab import BacktestTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Football Predictor")
        self.setMinimumSize(1050, 720)
        self.resize(1100, 780)

        # Central tab widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

        # Create tabs
        self.download_tab = DownloadTab(self)
        self.prediction_tab = PredictionTab(self)
        self.backtest_tab = BacktestTab(self)

        self.tabs.addTab(self.download_tab, "  Download  ")
        self.tabs.addTab(self.prediction_tab, "  Predict  ")
        self.tabs.addTab(self.backtest_tab, "  Backtest  ")

        # Refresh prediction/backtest league lists when switching tabs
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def set_status(self, message: str):
        self.status.showMessage(message)

    def _on_tab_changed(self, index: int):
        if index == 1:
            self.prediction_tab.refresh_leagues()
        elif index == 2:
            self.backtest_tab.refresh_leagues()
