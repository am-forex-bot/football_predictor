"""Bet Builder tab — shows all combo/singles markets per match with model probabilities and fair odds.

Displays goal combos (BTTS+Result, Result+O/U), additional goal lines,
team totals, correct scores, and match stats (corners, shots, cards)
calculated from the Poisson goal matrix and historical stat averages.

The user compares fair odds against their bookmaker's bet builder prices —
if the bookie offers higher odds than our fair price, that's value.
"""

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QFrame,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from core.data_manager import get_available_leagues, load_league_data
from core.poisson_model import PoissonModel, PoissonConfig
from core.stats_model import StatsModel


def _fair_odds(prob: float) -> str:
    """Format probability as fair decimal odds."""
    if prob <= 0.001:
        return "—"
    return f"{1.0 / prob:.2f}"


def _pct(prob: float) -> str:
    return f"{prob * 100:.1f}%"


class _BetBuilderWorker(QThread):
    """Run model predictions in background thread."""
    finished = pyqtSignal(list, object)  # predictions, stats_model
    error = pyqtSignal(str)

    def __init__(self, results_df, fixtures_df):
        super().__init__()
        self.results_df = results_df
        self.fixtures_df = fixtures_df

    def run(self):
        try:
            model = PoissonModel(PoissonConfig())
            model.fit(self.results_df)
            preds = model.predict_fixtures(self.results_df, self.fixtures_df)

            stats = StatsModel(min_matches=3)
            stats.fit(self.results_df)

            # Attach stat predictions to each match prediction
            for pred in preds:
                sp = stats.predict_match(pred["home_team"], pred["away_team"])
                pred["_stats"] = sp

            self.finished.emit(preds, stats)
        except Exception as e:
            self.error.emit(str(e))


class BetBuilderTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._worker = None
        self._predictions = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # Guide
        guide = QLabel(
            "<b>Bet Builder:</b> "
            "All markets below are derived from the Poisson goal matrix and historical stats. "
            "<b>Fair Odds</b> = the minimum price you should accept. "
            "If your bookmaker offers <b>higher</b> odds than the fair price, that's value. "
            "Use these to build combo bets (e.g. BTTS &amp; Over 2.5 &amp; Home Win)."
        )
        guide.setWordWrap(True)
        guide.setStyleSheet(
            "padding: 6px 10px; border-radius: 4px; "
            "background-color: rgba(59, 130, 246, 0.12); "
            "color: #93c5fd; font-size: 11px;"
        )
        layout.addWidget(guide)

        # Config bar
        config = QGroupBox("Configuration")
        config_layout = QHBoxLayout(config)

        config_layout.addWidget(QLabel("League:"))
        self.league_combo = QComboBox()
        self.league_combo.setMinimumWidth(180)
        config_layout.addWidget(self.league_combo)

        config_layout.addWidget(QLabel("  Match:"))
        self.match_combo = QComboBox()
        self.match_combo.setMinimumWidth(280)
        self.match_combo.currentIndexChanged.connect(self._on_match_changed)
        config_layout.addWidget(self.match_combo)

        config_layout.addStretch()

        self.run_btn = QPushButton("Build Markets")
        self.run_btn.setMinimumWidth(130)
        self.run_btn.clicked.connect(self._on_run)
        config_layout.addWidget(self.run_btn)

        layout.addWidget(config)

        # Splitter: match summary + market table
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Match summary
        self.summary_label = QLabel("Select a league and click Build Markets")
        self.summary_label.setStyleSheet(
            "padding: 8px; font-size: 13px; "
            "background-color: rgba(255,255,255,0.05); border-radius: 4px;"
        )
        self.summary_label.setWordWrap(True)
        splitter.addWidget(self.summary_label)

        # Market table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Category", "Selection", "Model Prob", "Fair Odds"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        splitter.addWidget(self.table)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    def refresh_leagues(self):
        current = self.league_combo.currentText()
        self.league_combo.clear()
        for code, name in get_available_leagues():
            self.league_combo.addItem(f"{name} ({code})", code)
        if current:
            idx = self.league_combo.findText(current)
            if idx >= 0:
                self.league_combo.setCurrentIndex(idx)

    def _on_run(self):
        code = self.league_combo.currentData()
        if not code:
            return

        self.run_btn.setEnabled(False)
        self.run_btn.setText("Building...")
        self.main_window.set_status("Running Poisson model + stats model...")

        try:
            results_df, fixtures_df, _ = load_league_data(code)
        except Exception as e:
            self.main_window.set_status(f"Error: {e}")
            self.run_btn.setEnabled(True)
            self.run_btn.setText("Build Markets")
            return

        self._worker = _BetBuilderWorker(results_df, fixtures_df)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_finished(self, predictions, stats_model):
        self._predictions = predictions
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Build Markets")

        # Populate match selector
        self.match_combo.blockSignals(True)
        self.match_combo.clear()
        for i, p in enumerate(predictions):
            label = f"{p['home_team']}  vs  {p['away_team']}"
            self.match_combo.addItem(label, i)
        self.match_combo.blockSignals(False)

        n = len(predictions)
        n_stats = sum(1 for p in predictions if p.get("_stats"))
        status = f"{n} fixtures predicted"
        if n_stats > 0:
            status += f" | {n_stats} with corner/shot/card stats"
        self.main_window.set_status(status)

        if predictions:
            self.match_combo.setCurrentIndex(0)
            self._on_match_changed(0)

    def _on_error(self, msg):
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Build Markets")
        self.main_window.set_status(f"Error: {msg}")

    def _on_match_changed(self, index):
        if index < 0 or index >= len(self._predictions):
            return
        pred = self._predictions[index]
        self._display_match(pred)

    def _display_match(self, pred):
        home = pred["home_team"]
        away = pred["away_team"]

        # Summary
        self.summary_label.setText(
            f"<b style='font-size:15px'>{home}  vs  {away}</b>"
            f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
            f"xG: <b>{pred['home_xg']}</b> — <b>{pred['away_xg']}</b>"
            f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
            f"1X2: {_pct(pred['p_home'])} / {_pct(pred['p_draw'])} / {_pct(pred['p_away'])}"
        )

        # Build all market rows
        rows = []

        # ── 1X2 ──
        rows.append(("1X2", "Home Win", pred["p_home"]))
        rows.append(("1X2", "Draw", pred["p_draw"]))
        rows.append(("1X2", "Away Win", pred["p_away"]))

        # ── Goal Lines ──
        for line, key_o, key_u in [
            ("1.5", "p_over_15", "p_under_15"),
            ("2.5", "p_over_25", "p_under_25"),
            ("3.5", "p_over_35", "p_under_35"),
            ("4.5", "p_over_45", "p_under_45"),
        ]:
            rows.append(("Goals", f"Over {line}", pred[key_o]))
            rows.append(("Goals", f"Under {line}", pred[key_u]))

        # ── BTTS ──
        rows.append(("BTTS", "BTTS Yes", pred["p_btts_yes"]))
        rows.append(("BTTS", "BTTS No", pred["p_btts_no"]))

        # ── Combo: BTTS + Result ──
        rows.append(("BTTS + Result", f"BTTS & {home} Win", pred["p_btts_home"]))
        rows.append(("BTTS + Result", "BTTS & Draw", pred["p_btts_draw"]))
        rows.append(("BTTS + Result", f"BTTS & {away} Win", pred["p_btts_away"]))

        # ── Combo: Result + O/U 2.5 ──
        rows.append(("Result + O/U 2.5", f"{home} Win & Over 2.5", pred["p_home_o25"]))
        rows.append(("Result + O/U 2.5", f"{home} Win & Under 2.5", pred["p_home_u25"]))
        rows.append(("Result + O/U 2.5", "Draw & Over 2.5", pred["p_draw_o25"]))
        rows.append(("Result + O/U 2.5", "Draw & Under 2.5", pred["p_draw_u25"]))
        rows.append(("Result + O/U 2.5", f"{away} Win & Over 2.5", pred["p_away_o25"]))
        rows.append(("Result + O/U 2.5", f"{away} Win & Under 2.5", pred["p_away_u25"]))

        # ── Combo: BTTS + O/U 2.5 ──
        rows.append(("BTTS + O/U 2.5", "BTTS & Over 2.5", pred["p_btts_o25"]))
        rows.append(("BTTS + O/U 2.5", "BTTS & Under 2.5", pred["p_btts_u25"]))

        # ── Team Totals ──
        for label, prefix in [(home, "home"), (away, "away")]:
            for line in ["0.5", "1.5", "2.5"]:
                key_o = f"p_{prefix}_over_{line.replace('.', '')}"
                key_u = f"p_{prefix}_under_{line.replace('.', '')}"
                rows.append(("Team Goals", f"{label} Over {line}", pred[key_o]))
                rows.append(("Team Goals", f"{label} Under {line}", pred[key_u]))

        # ── Correct Score (top 10) ──
        cs = pred.get("correct_scores", {})
        for score, pct in sorted(cs.items(), key=lambda x: x[1], reverse=True)[:10]:
            rows.append(("Correct Score", score, pct / 100.0))

        # ── Match Stats (corners, shots, cards) ──
        stats = pred.get("_stats")
        if stats:
            for key in ("corners", "shots", "sot", "yellows"):
                info = stats.get(key)
                if not info:
                    continue
                label = info["label"]
                cat = f"{label} (avg {info['total_expected']})"
                for line_key, prob in info["lines"].items():
                    # line_key like "over_8.5" or "under_9.5"
                    parts = line_key.split("_", 1)
                    ou = parts[0].title()
                    val = parts[1]
                    rows.append((cat, f"Total {label} {ou} {val}", prob))

        # Populate table
        self.table.setRowCount(len(rows))
        bold_font = QFont()
        bold_font.setBold(True)

        prev_cat = ""
        for i, (cat, selection, prob) in enumerate(rows):
            # Category — only show on first row of group
            cat_item = QTableWidgetItem(cat if cat != prev_cat else "")
            if cat != prev_cat:
                cat_item.setFont(bold_font)
            cat_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(i, 0, cat_item)
            prev_cat = cat

            # Selection
            sel_item = QTableWidgetItem(selection)
            self.table.setItem(i, 1, sel_item)

            # Model probability
            prob_item = QTableWidgetItem(_pct(prob))
            prob_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            # Color-code by probability
            if prob >= 0.6:
                prob_item.setForeground(QColor("#4ade80"))  # green
            elif prob >= 0.4:
                prob_item.setForeground(QColor("#fbbf24"))  # amber
            elif prob >= 0.2:
                prob_item.setForeground(QColor("#f97316"))  # orange
            else:
                prob_item.setForeground(QColor("#94a3b8"))  # grey
            self.table.setItem(i, 2, prob_item)

            # Fair odds
            odds_item = QTableWidgetItem(_fair_odds(prob))
            odds_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(i, 3, odds_item)

        self.table.resizeRowsToContents()
