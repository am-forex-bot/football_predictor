"""Prediction tab — select league, configure params, run predictions."""

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from core.data_manager import get_available_leagues, load_league_data
from core.predictor import predict_fixtures


class PredictionTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Configuration ---
        config_group = QGroupBox("Configuration")
        config_layout = QHBoxLayout(config_group)

        config_layout.addWidget(QLabel("League:"))
        self.league_combo = QComboBox()
        self.league_combo.setMinimumWidth(220)
        config_layout.addWidget(self.league_combo)

        config_layout.addWidget(QLabel("Threshold:"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 10)
        self.threshold_spin.setValue(3)
        config_layout.addWidget(self.threshold_spin)

        config_layout.addWidget(QLabel("Lookback:"))
        self.lookback_spin = QSpinBox()
        self.lookback_spin.setRange(3, 14)
        self.lookback_spin.setValue(5)
        config_layout.addWidget(self.lookback_spin)

        self.run_btn = QPushButton("Run Predictions")
        self.run_btn.setProperty("success", True)
        self.run_btn.clicked.connect(self._on_run)
        config_layout.addWidget(self.run_btn)

        config_layout.addStretch()
        layout.addWidget(config_group)

        # --- Results table ---
        results_group = QGroupBox("Predictions")
        results_layout = QVBoxLayout(results_group)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(8)
        self.results_table.setHorizontalHeaderLabels([
            "Home Team", "Away Team", "Prediction", "Score Diff",
            "Home Odds", "Draw Odds", "Away Odds", "Predicted Odds",
        ])
        self.results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.verticalHeader().setVisible(False)
        results_layout.addWidget(self.results_table)

        layout.addWidget(results_group)

        # --- Summary ---
        summary_group = QGroupBox("Summary")
        summary_layout = QHBoxLayout(summary_group)
        self.summary_label = QLabel("Run predictions to see results.")
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        layout.addWidget(summary_group)

    def refresh_leagues(self):
        current = self.league_combo.currentText()
        self.league_combo.clear()
        for code, name in get_available_leagues():
            self.league_combo.addItem(name, code)
        # Restore selection if possible
        idx = self.league_combo.findText(current)
        if idx >= 0:
            self.league_combo.setCurrentIndex(idx)

    def _on_run(self):
        code = self.league_combo.currentData()
        if not code:
            self.main_window.set_status("No league selected")
            return

        data = load_league_data(code)
        if data is None:
            self.main_window.set_status("No data available for this league")
            return

        results_df, fixtures_df, table_df = data
        threshold = self.threshold_spin.value()
        lookback = self.lookback_spin.value()

        predictions = predict_fixtures(results_df, table_df, fixtures_df,
                                       threshold, lookback)

        self._display_predictions(predictions)
        self.main_window.set_status(
            f"Predicted {len(predictions)} fixtures (threshold={threshold}, lookback={lookback})"
        )

    def _display_predictions(self, predictions: list[dict]):
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(len(predictions))

        home_wins = away_wins = draws = 0
        combined_odds = 0.0

        for row, p in enumerate(predictions):
            self.results_table.setItem(row, 0, QTableWidgetItem(p["home_team"]))
            self.results_table.setItem(row, 1, QTableWidgetItem(p["away_team"]))
            self.results_table.setItem(row, 2, QTableWidgetItem(p["prediction"]))

            diff_item = QTableWidgetItem()
            diff_item.setData(Qt.ItemDataRole.DisplayRole, p["score_diff"])
            self.results_table.setItem(row, 3, diff_item)

            for col, key in [(4, "home_odds"), (5, "draw_odds"), (6, "away_odds")]:
                val = p[key]
                item = QTableWidgetItem(f"{val:.2f}" if val else "-")
                self.results_table.setItem(row, col, item)

            # Determine the odds for the predicted outcome
            pred_text = p["prediction"]
            if "Win" in pred_text and pred_text.startswith(p["home_team"]):
                pred_odds = p["home_odds"]
                home_wins += 1
            elif "Win" in pred_text:
                pred_odds = p["away_odds"]
                away_wins += 1
            else:
                pred_odds = p["draw_odds"]
                draws += 1

            odds_str = f"{pred_odds:.2f}" if pred_odds else "-"
            self.results_table.setItem(row, 7, QTableWidgetItem(odds_str))
            if pred_odds:
                combined_odds += pred_odds

            # Color code rows
            if "Win" in pred_text and pred_text.startswith(p["home_team"]):
                color = QColor("#1a3a2a")  # dark green
            elif "Win" in pred_text:
                color = QColor("#1a2a3a")  # dark blue
            else:
                color = QColor("#2a2a2a")  # dark grey

            for col in range(8):
                item = self.results_table.item(row, col)
                if item:
                    item.setBackground(color)

        self.results_table.setSortingEnabled(True)

        total = len(predictions)
        avg_odds = combined_odds / total if total > 0 else 0
        self.summary_label.setText(
            f"Total: {total} predictions  |  "
            f"Home wins: {home_wins}  |  Away wins: {away_wins}  |  Draws: {draws}  |  "
            f"Combined odds: {combined_odds:.2f}  |  Avg odds: {avg_odds:.2f}"
        )
