"""Backtest tab — historical accuracy testing with weekly performance tracking.

Grids across threshold/lookback, shows accuracy heatmap, and tracks
perfect gameweeks (100%, 90%, 80%, 70%).
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QTabWidget, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QColor

from core.data_manager import get_available_leagues, load_league_data
from core.predictor import MatchPredictor, PredictorConfig


class _BacktestWorker(QObject):
    """Run backtesting + weekly performance in a background thread."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, results_df, table_df, t_min, t_max, lb_min, lb_max, min_week_games):
        super().__init__()
        self.results_df = results_df
        self.table_df = table_df
        self.t_min = t_min
        self.t_max = t_max
        self.lb_min = lb_min
        self.lb_max = lb_max
        self.min_week_games = min_week_games

    def run(self):
        try:
            predictor = MatchPredictor(PredictorConfig())

            # Main backtest
            result = predictor.backtest(
                self.results_df, self.table_df,
                self.t_min, self.t_max, self.lb_min, self.lb_max,
            )

            # Weekly performance analysis
            weekly = predictor.weekly_performance(
                self.results_df, self.table_df,
                self.t_min, self.t_max, self.lb_min, self.lb_max,
                min_week_games=self.min_week_games,
            )

            result["weekly"] = weekly
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class BacktestTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._thread = None
        self._worker = None
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
        self.t_min_spin = QSpinBox()
        self.t_min_spin.setRange(1, 20)
        self.t_min_spin.setValue(1)
        config_layout.addWidget(self.t_min_spin)
        config_layout.addWidget(QLabel("to"))
        self.t_max_spin = QSpinBox()
        self.t_max_spin.setRange(1, 20)
        self.t_max_spin.setValue(10)
        config_layout.addWidget(self.t_max_spin)

        config_layout.addWidget(QLabel("Lookback:"))
        self.lb_min_spin = QSpinBox()
        self.lb_min_spin.setRange(3, 20)
        self.lb_min_spin.setValue(3)
        config_layout.addWidget(self.lb_min_spin)
        config_layout.addWidget(QLabel("to"))
        self.lb_max_spin = QSpinBox()
        self.lb_max_spin.setRange(3, 20)
        self.lb_max_spin.setValue(14)
        config_layout.addWidget(self.lb_max_spin)

        config_layout.addWidget(QLabel("Min week games:"))
        self.min_week_spin = QSpinBox()
        self.min_week_spin.setRange(1, 20)
        self.min_week_spin.setValue(3)
        config_layout.addWidget(self.min_week_spin)

        self.run_btn = QPushButton("Run Backtest")
        self.run_btn.setProperty("success", True)
        self.run_btn.clicked.connect(self._on_run)
        config_layout.addWidget(self.run_btn)

        config_layout.addStretch()
        layout.addWidget(config_group)

        # --- Sub-tabs for results ---
        self.result_tabs = QTabWidget()

        # Accuracy grid tab
        grid_widget = QWidget()
        grid_layout = QVBoxLayout(grid_widget)
        self.grid_table = QTableWidget()
        self.grid_table.setAlternatingRowColors(False)
        self.grid_table.verticalHeader().setVisible(True)
        grid_layout.addWidget(self.grid_table)
        self.best_label = QLabel("")
        self.best_label.setProperty("heading", True)
        grid_layout.addWidget(self.best_label)
        self.result_tabs.addTab(grid_widget, "Accuracy Grid")

        # Weekly performance tab
        weekly_widget = QWidget()
        weekly_layout = QVBoxLayout(weekly_widget)
        self.weekly_table = QTableWidget()
        self.weekly_table.setAlternatingRowColors(True)
        self.weekly_table.setSortingEnabled(True)
        self.weekly_table.verticalHeader().setVisible(False)
        weekly_layout.addWidget(self.weekly_table)
        self.weekly_label = QLabel("")
        self.weekly_label.setProperty("heading", True)
        weekly_layout.addWidget(self.weekly_label)
        self.result_tabs.addTab(weekly_widget, "Weekly Performance")

        layout.addWidget(self.result_tabs)

        # --- Stats ---
        stats_group = QGroupBox("Detailed Statistics")
        stats_layout = QVBoxLayout(stats_group)
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setMaximumHeight(180)
        stats_layout.addWidget(self.stats_text)
        layout.addWidget(stats_group)

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

        results_df, _, table_df = data
        t_min = self.t_min_spin.value()
        t_max = self.t_max_spin.value()
        lb_min = self.lb_min_spin.value()
        lb_max = self.lb_max_spin.value()
        min_week = self.min_week_spin.value()

        self.run_btn.setEnabled(False)
        self.main_window.set_status("Running backtest...")

        self._thread = QThread()
        self._worker = _BacktestWorker(results_df, table_df, t_min, t_max,
                                       lb_min, lb_max, min_week)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_finished(self, result: dict):
        self.run_btn.setEnabled(True)
        accuracy = result["accuracy"]
        draw_stats = result["draw_stats"]
        odds_stats = result["odds_stats"]
        best = result["best"]
        weekly = result.get("weekly", [])

        thresholds = sorted(accuracy.keys())
        lookbacks = sorted({lb for t in accuracy.values() for lb in t})

        # --- Fill accuracy grid ---
        self.grid_table.setRowCount(len(thresholds))
        self.grid_table.setColumnCount(len(lookbacks))
        self.grid_table.setHorizontalHeaderLabels([f"LB {lb}" for lb in lookbacks])
        self.grid_table.setVerticalHeaderLabels([f"T={t}" for t in thresholds])

        all_acc = [accuracy[t][lb] for t in thresholds for lb in lookbacks
                   if lb in accuracy.get(t, {})]
        min_acc = min(all_acc) if all_acc else 0
        max_acc = max(all_acc) if all_acc else 100

        for r, t in enumerate(thresholds):
            for c, lb in enumerate(lookbacks):
                acc = accuracy.get(t, {}).get(lb, 0)
                item = QTableWidgetItem(f"{acc:.1f}%")
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if max_acc > min_acc:
                    ratio = (acc - min_acc) / (max_acc - min_acc)
                else:
                    ratio = 0.5
                if ratio < 0.5:
                    r_val = 200
                    g_val = int(100 + ratio * 2 * 155)
                else:
                    r_val = int(200 - (ratio - 0.5) * 2 * 160)
                    g_val = 200
                item.setBackground(QColor(r_val, g_val, 60, 80))

                if t == best[0] and lb == best[1]:
                    item.setBackground(QColor("#7c3aed"))
                    item.setForeground(QColor("#ffffff"))

                self.grid_table.setItem(r, c, item)

        self.grid_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        self.best_label.setText(
            f"Best: Threshold={best[0]}, Lookback={best[1]}, Accuracy={best[2]:.1f}%"
        )

        # --- Fill weekly performance table ---
        weekly_cols = [
            "Threshold", "Lookback", "Accuracy%", "Games",
            "Perfect Weeks", "90%+ Weeks", "80%+ Weeks", "70%+ Weeks",
            "Weeks Tested",
        ]
        self.weekly_table.setSortingEnabled(False)
        self.weekly_table.setColumnCount(len(weekly_cols))
        self.weekly_table.setHorizontalHeaderLabels(weekly_cols)
        self.weekly_table.setRowCount(len(weekly))

        for r, w in enumerate(weekly):
            items = [
                (str(w["threshold"]), None),
                (str(w["lookback"]), None),
                (f"{w['accuracy']:.1f}%", None),
                (str(w["total_games"]), None),
                (str(w["perfect_weeks"]), QColor("#22c55e") if w["perfect_weeks"] > 0 else None),
                (str(w["weeks_ge90"]), QColor("#16a34a") if w["weeks_ge90"] > 0 else None),
                (str(w["weeks_ge80"]), None),
                (str(w["weeks_ge70"]), None),
                (str(w["weeks_tested"]), None),
            ]
            for c, (text, highlight) in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if highlight:
                    item.setForeground(highlight)
                # Highlight rows with perfect weeks
                if w["perfect_weeks"] > 0:
                    item.setBackground(QColor("#1a3a2a"))
                self.weekly_table.setItem(r, c, item)

        self.weekly_table.setSortingEnabled(True)
        self.weekly_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        # Weekly summary
        if weekly:
            top = weekly[0]
            self.weekly_label.setText(
                f"Top combo: T={top['threshold']} LB={top['lookback']} — "
                f"{top['perfect_weeks']} perfect weeks, "
                f"{top['weeks_ge90']} at 90%+, "
                f"{top['accuracy']:.1f}% overall"
            )
        else:
            self.weekly_label.setText("No weekly data generated")

        # --- Detailed stats ---
        lines = []
        for t in thresholds:
            for lb in lookbacks:
                ds = draw_stats.get(t, {}).get(lb, {"correct": 0, "predicted": 0})
                os_data = odds_stats.get(t, {}).get(lb, {"combined": 0, "total": 0, "avg": 0})
                acc = accuracy.get(t, {}).get(lb, 0)
                draw_acc = (ds["correct"] / ds["predicted"] * 100) if ds["predicted"] > 0 else 0
                # Find matching weekly row
                w_match = next((w for w in weekly
                                if w["threshold"] == t and w["lookback"] == lb), None)
                perfect_str = ""
                if w_match and w_match["perfect_weeks"] > 0:
                    perfect_str = f" | PERFECT WEEKS: {w_match['perfect_weeks']}"
                lines.append(
                    f"T={t:2d} LB={lb:2d} | Acc: {acc:5.1f}% | "
                    f"Draws: {ds['correct']}/{ds['predicted']} ({draw_acc:.0f}%) | "
                    f"Avg odds: {os_data.get('avg', 0):.2f}{perfect_str}"
                )

        self.stats_text.setPlainText("\n".join(lines))
        self.main_window.set_status(
            f"Backtest complete. Best: T={best[0]} LB={best[1]} -> {best[2]:.1f}%"
        )

    def _on_error(self, msg: str):
        self.run_btn.setEnabled(True)
        self.main_window.set_status(f"Backtest error: {msg}")
        self.stats_text.setPlainText(f"Error: {msg}")
