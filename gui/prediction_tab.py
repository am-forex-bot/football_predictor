"""Prediction tab — select league, configure params, run predictions.

Shows predictions with odds comparison, implied probability, and potential returns.
"""

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QSpinBox, QDoubleSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from core.data_manager import get_available_leagues, load_league_data
from core.predictor import MatchPredictor, PredictorConfig


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
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.5, 20.0)
        self.threshold_spin.setSingleStep(0.5)
        self.threshold_spin.setValue(3.0)
        self.threshold_spin.setDecimals(1)
        config_layout.addWidget(self.threshold_spin)

        config_layout.addWidget(QLabel("Lookback:"))
        self.lookback_spin = QSpinBox()
        self.lookback_spin.setRange(3, 20)
        self.lookback_spin.setValue(6)
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
        cols = [
            "Home Team", "Cat", "Away Team", "Cat", "Prediction", "Score Diff",
            "B365 Odds", "Implied %", "Potential (£10)", "Acca Leg",
        ]
        self.results_table.setColumnCount(len(cols))
        self.results_table.setHorizontalHeaderLabels(cols)
        self.results_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.verticalHeader().setVisible(False)
        results_layout.addWidget(self.results_table)

        layout.addWidget(results_group)

        # --- Summary ---
        summary_group = QGroupBox("Summary")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_label = QLabel("Run predictions to see results.")
        self.summary_label.setWordWrap(True)
        summary_layout.addWidget(self.summary_label)
        layout.addWidget(summary_group)

    def refresh_leagues(self):
        current = self.league_combo.currentText()
        self.league_combo.clear()
        for code, name in get_available_leagues():
            self.league_combo.addItem(name, code)
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

        if fixtures_df.empty:
            self.main_window.set_status(
                "No fixtures found! Re-download the league to fetch fixtures.csv"
            )
            self.summary_label.setText(
                "No fixtures available. The season CSV may not contain upcoming matches. "
                "Try re-downloading — the app now also fetches the dedicated fixtures.csv."
            )
            return

        cfg = PredictorConfig(lookback=lookback, threshold=threshold)
        predictor = MatchPredictor(cfg)
        predictions = predictor.predict_fixtures(results_df, table_df, fixtures_df)

        if not predictions:
            self.main_window.set_status(
                f"0 predictions — teams may not have {lookback} matches yet. Try lowering lookback."
            )
            self.summary_label.setText(
                f"No predictions generated. Teams need at least {lookback} "
                f"home/away matches each. Try a lower lookback value."
            )
            return

        self._display_predictions(predictions)
        self.main_window.set_status(
            f"Predicted {len(predictions)} fixtures (threshold={threshold}, lookback={lookback})"
        )

    def _display_predictions(self, predictions: list[dict]):
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(len(predictions))

        home_wins = away_wins = draws = no_bets = 0
        acca_odds = 1.0
        acca_legs = 0

        for row, p in enumerate(predictions):
            self.results_table.setItem(row, 0, QTableWidgetItem(p["home_team"]))
            self.results_table.setItem(row, 1, QTableWidgetItem(p.get("home_cat", "")))
            self.results_table.setItem(row, 2, QTableWidgetItem(p["away_team"]))
            self.results_table.setItem(row, 3, QTableWidgetItem(p.get("away_cat", "")))
            self.results_table.setItem(row, 4, QTableWidgetItem(p["prediction"]))

            diff_item = QTableWidgetItem()
            diff_item.setData(Qt.ItemDataRole.DisplayRole, p["score_diff"])
            self.results_table.setItem(row, 5, diff_item)

            pred_odds = p.get("pred_odds")
            implied = p.get("implied_prob")
            pred_text = p["prediction"]

            # B365 odds for our prediction
            if pred_odds:
                odds_item = QTableWidgetItem(f"{pred_odds:.2f}")
                odds_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                odds_item = QTableWidgetItem("-")
            self.results_table.setItem(row, 6, odds_item)

            # Implied probability from B365 odds
            if implied:
                imp_item = QTableWidgetItem(f"{implied:.1f}%")
                imp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if implied > 60:
                    imp_item.setForeground(QColor("#22c55e"))
                elif implied < 35:
                    imp_item.setForeground(QColor("#f59e0b"))
            else:
                imp_item = QTableWidgetItem("-")
            self.results_table.setItem(row, 7, imp_item)

            # Track wins/draws/no bets
            if "Win" in pred_text and pred_text.startswith(p["home_team"]):
                home_wins += 1
            elif "Win" in pred_text:
                away_wins += 1
            elif pred_text == "No Bet":
                no_bets += 1
            else:
                draws += 1

            # Potential return on £10 bet
            if pred_odds and pred_text != "No Bet":
                potential = pred_odds * 10
                pot_item = QTableWidgetItem(f"£{potential:.2f}")
                pot_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                acca_odds *= pred_odds
                acca_legs += 1
            else:
                pot_item = QTableWidgetItem("-")
            self.results_table.setItem(row, 8, pot_item)

            # Acca running odds
            if pred_odds and pred_text != "No Bet":
                acca_item = QTableWidgetItem(f"{pred_odds:.2f}")
                acca_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                acca_item.setForeground(QColor("#fbbf24"))
            else:
                acca_item = QTableWidgetItem("-")
            self.results_table.setItem(row, 9, acca_item)

            # Color code rows
            if "Win" in pred_text and pred_text.startswith(p["home_team"]):
                color = QColor("#1a3a2a")
            elif "Win" in pred_text:
                color = QColor("#1a2a3a")
            elif pred_text == "No Bet":
                color = QColor("#3a2a1a")
            else:
                color = QColor("#2a2a2a")

            for col in range(self.results_table.columnCount()):
                item = self.results_table.item(row, col)
                if item:
                    item.setBackground(color)

        self.results_table.setSortingEnabled(True)

        actual_preds = home_wins + away_wins + draws
        acca_return = acca_odds * 5 if acca_legs > 0 else 0

        self.summary_label.setText(
            f"Total: {len(predictions)} fixtures  |  "
            f"Home: {home_wins}  |  Away: {away_wins}  |  "
            f"Draws: {draws}  |  No bets: {no_bets}\n"
            f"Accumulator ({acca_legs} legs): odds = {acca_odds:.1f}  |  "
            f"£5 acca returns £{acca_return:,.2f} if all correct"
        )
