"""Weight tuner tab — random search for optimal weight configurations
with train/validation split to prevent overfitting."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QProgressBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QColor

from core.data_manager import get_available_leagues, load_league_data
from core.predictor import tune_weights


class _TunerWorker(QObject):
    """Run weight tuning in a background thread."""
    progress = pyqtSignal(int, int)  # current, total
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, results_df, table_df, n_candidates,
                 lb_min, lb_max, t_min, t_max, seed):
        super().__init__()
        self.results_df = results_df
        self.table_df = table_df
        self.n_candidates = n_candidates
        self.lb_min = lb_min
        self.lb_max = lb_max
        self.t_min = t_min
        self.t_max = t_max
        self.seed = seed

    def run(self):
        try:
            result = tune_weights(
                self.results_df, self.table_df,
                n_candidates=self.n_candidates,
                lookback_min=self.lb_min, lookback_max=self.lb_max,
                threshold_min=self.t_min, threshold_max=self.t_max,
                seed=self.seed,
                progress_callback=lambda c, t: self.progress.emit(c, t),
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class TunerTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._thread = None
        self._worker = None
        self._best_config = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- Configuration ---
        config_group = QGroupBox("Tuner Configuration")
        config_layout = QHBoxLayout(config_group)

        config_layout.addWidget(QLabel("League:"))
        self.league_combo = QComboBox()
        self.league_combo.setMinimumWidth(220)
        config_layout.addWidget(self.league_combo)

        config_layout.addWidget(QLabel("Candidates:"))
        self.candidates_spin = QSpinBox()
        self.candidates_spin.setRange(10, 500)
        self.candidates_spin.setValue(80)
        config_layout.addWidget(self.candidates_spin)

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

        self.run_btn = QPushButton("Tune Weights")
        self.run_btn.setProperty("success", True)
        self.run_btn.clicked.connect(self._on_run)
        config_layout.addWidget(self.run_btn)

        config_layout.addStretch()
        layout.addWidget(config_group)

        # --- Progress ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # --- Info label ---
        info_group = QGroupBox("Overfitting Protection")
        info_layout = QVBoxLayout(info_group)
        info_label = QLabel(
            "Multi-season walk-forward validation: trains on earlier seasons, "
            "validates on the most recent 2 seasons. Single-season falls back "
            "to 70/30 split. Ranked by blended accuracy (40% train + 60% validation)."
        )
        info_label.setWordWrap(True)
        info_layout.addWidget(info_label)
        layout.addWidget(info_group)

        # --- Leaderboard table ---
        results_group = QGroupBox("Candidate Leaderboard")
        results_layout = QVBoxLayout(results_group)

        self.results_table = QTableWidget()
        cols = [
            "Rank", "ID", "Lookback", "Threshold",
            "Train Acc%", "Train Games", "Valid Acc%", "Valid Games",
            "Blended Acc%",
        ]
        self.results_table.setColumnCount(len(cols))
        self.results_table.setHorizontalHeaderLabels(cols)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSortingEnabled(True)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        results_layout.addWidget(self.results_table)

        self.best_label = QLabel("")
        self.best_label.setProperty("heading", True)
        results_layout.addWidget(self.best_label)

        layout.addWidget(results_group)

        # --- Best config details ---
        detail_group = QGroupBox("Best Configuration Weights")
        detail_layout = QVBoxLayout(detail_group)
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMaximumHeight(200)
        detail_layout.addWidget(self.detail_text)
        layout.addWidget(detail_group)

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

        # Try multi-season backtest data first, fall back to single season
        from core.data_manager import load_backtest_data, load_league_data
        results_df = load_backtest_data(code)
        table_df = None

        if results_df is None or results_df.empty:
            data = load_league_data(code)
            if data is None:
                self.main_window.set_status("No data available for this league")
                return
            results_df, _, table_df = data

        n_candidates = self.candidates_spin.value()

        self.run_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, n_candidates)
        self.progress_bar.setValue(0)

        n_seasons = results_df["Season"].nunique() if "Season" in results_df.columns else 1
        self.main_window.set_status(
            f"Tuning weights across {n_seasons} season(s) (0/{n_candidates})..."
        )

        self._thread = QThread()
        self._worker = _TunerWorker(
            results_df, table_df, n_candidates,
            self.lb_min_spin.value(), self.lb_max_spin.value(),
            self.t_min_spin.value(), self.t_max_spin.value(),
            seed=42,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    def _on_progress(self, current: int, total: int):
        self.progress_bar.setValue(current)
        self.main_window.set_status(f"Tuning weights ({current}/{total})...")

    def _on_finished(self, result: dict):
        self.run_btn.setEnabled(True)
        self.progress_bar.setVisible(False)

        lb_df = result["leaderboard"]
        best_config = result["best_config"]
        self._best_config = best_config

        if lb_df.empty:
            self.main_window.set_status("No candidates produced results")
            return

        # Fill leaderboard table
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(len(lb_df))

        for r, (_, row) in enumerate(lb_df.iterrows()):
            items = [
                str(r + 1),
                str(int(row["candidate_id"])),
                str(int(row["lookback"])),
                str(int(row["threshold"])),
                f"{row['train_acc']:.1f}",
                str(int(row["train_games"])),
                f"{row['valid_acc']:.1f}",
                str(int(row["valid_games"])),
                f"{row['blended_acc']:.1f}",
            ]
            for c, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # Highlight top 3
                if r == 0:
                    item.setBackground(QColor("#2a1a3a"))
                    item.setForeground(QColor("#cba6f7"))
                elif r <= 2:
                    item.setBackground(QColor("#1a2a3a"))

                # Color validation accuracy
                if c == 6:  # valid_acc column
                    val = row["valid_acc"]
                    if val >= 55:
                        item.setForeground(QColor("#22c55e"))
                    elif val >= 50:
                        item.setForeground(QColor("#f59e0b"))
                    else:
                        item.setForeground(QColor("#ef4444"))

                self.results_table.setItem(r, c, item)

        self.results_table.setSortingEnabled(True)

        top = lb_df.iloc[0]
        self.best_label.setText(
            f"Best: Candidate #{int(top['candidate_id'])} — "
            f"T={int(top['threshold'])} LB={int(top['lookback'])} — "
            f"Train: {top['train_acc']:.1f}% | Valid: {top['valid_acc']:.1f}% | "
            f"Blended: {top['blended_acc']:.1f}%"
        )

        # Show best config weights
        if best_config:
            lines = [f"Lookback: {best_config['lookback']}",
                     f"Threshold: {best_config['threshold']}",
                     f"Heavy loss penalty: {best_config['loss_heavy_penalty']}",
                     f"Heavy loss GD threshold: {best_config['heavy_loss_gd']}",
                     f"Big win GD threshold: {best_config.get('big_win_gd', 3)}",
                     "",
                     "Win Weights:"]
            for venue in ["Home", "Away"]:
                w = best_config["win_weights"][venue]
                lines.append(f"  {venue}: " + "  ".join(
                    f"{t}={v:.1f}" for t, v in w.items()
                ))
            lines.append("\nBig Win Bonus:")
            for venue in ["Home", "Away"]:
                w = best_config.get("big_win_bonus", {}).get(venue, {})
                if w:
                    lines.append(f"  {venue}: " + "  ".join(
                        f"{t}={v:.1f}" for t, v in w.items()
                    ))
            lines.append("\nDraw Weights:")
            for venue in ["Home", "Away"]:
                w = best_config["draw_weights"][venue]
                lines.append(f"  {venue}: " + "  ".join(
                    f"{t}={v:.1f}" for t, v in w.items()
                ))
            lines.append("\nLoss (Close) Weights:")
            for venue in ["Home", "Away"]:
                w = best_config["loss_close_weights"][venue]
                lines.append(f"  {venue}: " + "  ".join(
                    f"{t}={v:.1f}" for t, v in w.items()
                ))
            self.detail_text.setPlainText("\n".join(lines))

        self.main_window.set_status(
            f"Tuning complete. Best blended accuracy: {top['blended_acc']:.1f}%"
        )

        # Store on main_window so backtest tab can use it
        if best_config:
            self.main_window.tuned_config = best_config
            self.main_window.set_status(
                f"Tuning complete — blended {top['blended_acc']:.1f}%. "
                f"Tick 'Use Tuned Weights' in Backtest tab to apply."
            )

    def _on_error(self, msg: str):
        self.run_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.main_window.set_status(f"Tuning error: {msg}")
        self.detail_text.setPlainText(f"Error: {msg}")
