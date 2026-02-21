#!/usr/bin/env python3
"""Football Predictor — entry point."""

import sys
import os

# Ensure the project root is on the path so imports work when running
# from any directory.
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication
from gui.main_window import MainWindow
from gui.styles import DARK_THEME


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Football Predictor")
    app.setStyleSheet(DARK_THEME)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
