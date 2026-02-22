"""Backtest tab — historical accuracy, ROI, and accumulator analysis.

All profit/ROI uses Bet365 odds. Tracks:
- Accuracy grid across threshold/lookback
- ROI grid (flat £1 staking at B365)
- Weekly performance with accumulator tracking
- Per-week detail view for any combo (double-click a row)
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QTabWidget, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QColor

from core.data_manager import get_available_leagues, load_league_data, load_backtest_data
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

            result = predictor.backtest(
                self.results_df, self.table_df,
                self.t_min, self.t_max, self.lb_min, self.lb_max,
            )

            weekly = predictor.weekly_performance(
                self.results_df, self.table_df,
                self.t_min, self.t_max, self.lb_min, self.lb_max,
                min_week_games=self.min_week_games,
                backtest_result=result,
            )

            result["weekly"] = weekly
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class _DetailWorker(QObject):
    """Get per-week detail for a specific combo."""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def __init__(self, results_df, table_df, threshold, lookback, min_week_games,
                 backtest_result):
        super().__init__()
        self.results_df = results_df
        self.table_df = table_df
        self.threshold = threshold
        self.lookback = lookback
        self.min_week_games = min_week_games
        self.backtest_result = backtest_result

    def run(self):
        try:
            predictor = MatchPredictor(PredictorConfig())
            detail = predictor.weekly_detail(
                self.results_df, self.table_df,
                self.threshold, self.lookback,
                min_week_games=self.min_week_games,
                backtest_result=self.backtest_result,
            )
            self.finished.emit(detail)
        except Exception as exc:
            self.error.emit(str(exc))


class BacktestTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._thread = None
        self._worker = None
        self._detail_thread = None
        self._detail_worker = None
        self._last_result = None
        self._last_results_df = None
        self._last_table_df = None
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

        # 1. Accuracy grid
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

        # 2. ROI grid (B365, flat staking)
        roi_widget = QWidget()
        roi_layout = QVBoxLayout(roi_widget)
        self.roi_table = QTableWidget()
        self.roi_table.setAlternatingRowColors(False)
        self.roi_table.verticalHeader().setVisible(True)
        roi_layout.addWidget(self.roi_table)
        self.roi_label = QLabel("")
        self.roi_label.setProperty("heading", True)
        roi_layout.addWidget(self.roi_label)
        self.result_tabs.addTab(roi_widget, "B365 ROI Grid")

        # 3. Weekly performance + acca tracking
        weekly_widget = QWidget()
        weekly_layout = QVBoxLayout(weekly_widget)
        weekly_hint = QLabel("Double-click any row to see week-by-week breakdown")
        weekly_hint.setStyleSheet("color: #888; font-style: italic;")
        weekly_layout.addWidget(weekly_hint)
        self.weekly_table = QTableWidget()
        self.weekly_table.setAlternatingRowColors(True)
        self.weekly_table.setSortingEnabled(True)
        self.weekly_table.verticalHeader().setVisible(False)
        self.weekly_table.doubleClicked.connect(self._on_weekly_double_click)
        weekly_layout.addWidget(self.weekly_table)
        self.weekly_label = QLabel("")
        self.weekly_label.setProperty("heading", True)
        weekly_layout.addWidget(self.weekly_label)
        self.result_tabs.addTab(weekly_widget, "Weekly + Accas")

        # 4. Week-by-week detail (populated on double-click)
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        self.detail_header = QLabel("Double-click a row in Weekly tab to load detail")
        self.detail_header.setProperty("heading", True)
        detail_layout.addWidget(self.detail_header)
        self.detail_table = QTableWidget()
        self.detail_table.setAlternatingRowColors(True)
        self.detail_table.setSortingEnabled(False)
        self.detail_table.verticalHeader().setVisible(False)
        detail_layout.addWidget(self.detail_table)
        self.detail_summary = QLabel("")
        self.detail_summary.setWordWrap(True)
        detail_layout.addWidget(self.detail_summary)
        self.result_tabs.addTab(detail_widget, "Week Detail")

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

        # Use multi-season data for backtesting if available
        backtest_df = load_backtest_data(code)
        if backtest_df is not None and len(backtest_df) > len(results_df):
            bt_results = backtest_df
            n_seasons = backtest_df["Season"].nunique() if "Season" in backtest_df.columns else 1
            self.main_window.set_status(
                f"Running backtest on {len(bt_results)} matches across {n_seasons} seasons..."
            )
        else:
            bt_results = results_df
            self.main_window.set_status("Running backtest (single season)...")

        self._last_results_df = bt_results
        self._last_table_df = table_df

        t_min = self.t_min_spin.value()
        t_max = self.t_max_spin.value()
        lb_min = self.lb_min_spin.value()
        lb_max = self.lb_max_spin.value()
        min_week = self.min_week_spin.value()

        self.run_btn.setEnabled(False)

        self._thread = QThread()
        self._worker = _BacktestWorker(bt_results, table_df, t_min, t_max,
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
        self._last_result = result
        accuracy = result["accuracy"]
        draw_stats = result["draw_stats"]
        odds_stats = result["odds_stats"]
        roi_stats = result.get("roi_stats", {})
        best = result["best"]
        best_roi = result.get("best_roi", (0, 0, -999))
        weekly = result.get("weekly", [])

        thresholds = sorted(accuracy.keys())
        lookbacks = sorted({lb for t in accuracy.values() for lb in t})

        self._fill_accuracy_grid(thresholds, lookbacks, accuracy, best)
        self._fill_roi_grid(thresholds, lookbacks, roi_stats, best_roi)
        self._fill_weekly_table(weekly)
        self._fill_stats(thresholds, lookbacks, accuracy, draw_stats, odds_stats,
                         roi_stats, weekly)

        # Count matches and seasons
        n_matches = 0
        if self._last_results_df is not None:
            n_matches = len(self._last_results_df)
        n_seasons = 1
        if self._last_results_df is not None and "Season" in self._last_results_df.columns:
            n_seasons = self._last_results_df["Season"].nunique()

        self.main_window.set_status(
            f"Backtest complete ({n_matches} matches, {n_seasons} seasons). "
            f"Best accuracy: T={best[0]} LB={best[1]} -> {best[2]:.1f}% | "
            f"Best ROI (B365): T={best_roi[0]} LB={best_roi[1]} -> {best_roi[2]:+.1f}%"
        )

    # ── Accuracy Grid ─────────────────────────────────────────────────

    def _fill_accuracy_grid(self, thresholds, lookbacks, accuracy, best):
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

    # ── ROI Grid (B365) ──────────────────────────────────────────────

    def _fill_roi_grid(self, thresholds, lookbacks, roi_stats, best_roi):
        self.roi_table.setRowCount(len(thresholds))
        self.roi_table.setColumnCount(len(lookbacks))
        self.roi_table.setHorizontalHeaderLabels([f"LB {lb}" for lb in lookbacks])
        self.roi_table.setVerticalHeaderLabels([f"T={t}" for t in thresholds])

        for r, t in enumerate(thresholds):
            for c, lb in enumerate(lookbacks):
                rs = roi_stats.get(t, {}).get(lb, {})
                roi_pct = rs.get("roi_pct", 0.0)
                profit = rs.get("profit", 0.0)
                stakes = rs.get("stakes", 0)

                if stakes > 0:
                    text = f"{roi_pct:+.1f}%"
                else:
                    text = "-"

                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(
                    f"B365 ROI: {roi_pct:+.1f}%\n"
                    f"Profit: {profit:+.1f} units\n"
                    f"Bets placed: {stakes}\n"
                    f"Returns: £{rs.get('returns', 0):.2f}"
                )

                if roi_pct > 0:
                    intensity = min(roi_pct / 30.0, 1.0)
                    item.setBackground(QColor(40, int(80 + 120 * intensity), 40, 120))
                    item.setForeground(QColor("#22c55e"))
                elif roi_pct < 0:
                    intensity = min(abs(roi_pct) / 30.0, 1.0)
                    item.setBackground(QColor(int(80 + 120 * intensity), 40, 40, 120))
                    item.setForeground(QColor("#ef4444"))

                if t == best_roi[0] and lb == best_roi[1]:
                    item.setBackground(QColor("#7c3aed"))
                    item.setForeground(QColor("#ffffff"))

                self.roi_table.setItem(r, c, item)

        self.roi_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        if best_roi[2] > -999:
            self.roi_label.setText(
                f"Best ROI: T={best_roi[0]}, LB={best_roi[1]}, "
                f"ROI={best_roi[2]:+.1f}% (flat £1 staking, Bet365 odds)"
            )
        else:
            self.roi_label.setText("No combos with 20+ bets to calculate ROI")

    # ── Weekly + Acca Table ───────────────────────────────────────────

    def _fill_weekly_table(self, weekly):
        cols = [
            "T", "LB", "Acc%", "Games", "100%", "90%+", "80%+",
            "Weeks", "Flat P&L", "Flat ROI%",
            "Acca P&L (£5)", "Best Acca",
            "Profit Wks",
        ]
        self.weekly_table.setSortingEnabled(False)
        self.weekly_table.setColumnCount(len(cols))
        self.weekly_table.setHorizontalHeaderLabels(cols)
        self.weekly_table.setRowCount(len(weekly))

        for r, w in enumerate(weekly):
            flat_pnl = w.get("flat_profit", 0.0)
            flat_roi = w.get("flat_roi_pct", 0.0)
            acca_pnl = w.get("acca_profit", 0.0)
            acca_best = w.get("acca_best_payout", 0.0)

            items = [
                str(w["threshold"]),
                str(w["lookback"]),
                f"{w['accuracy']:.1f}",
                str(w["total_games"]),
                str(w["perfect_weeks"]),
                str(w["weeks_ge90"]),
                str(w["weeks_ge80"]),
                str(w["weeks_tested"]),
                f"{flat_pnl:+.1f}",
                f"{flat_roi:+.1f}",
                f"{acca_pnl:+.1f}",
                f"£{acca_best:.0f}" if acca_best > 0 else "-",
                str(w.get("profitable_weeks", 0)),
            ]

            for c, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # Color specific columns
                if c == 4 and w["perfect_weeks"] > 0:  # 100% weeks
                    item.setForeground(QColor("#fbbf24"))  # gold
                if c == 8:  # Flat P&L
                    item.setForeground(QColor("#22c55e") if flat_pnl > 0
                                       else QColor("#ef4444") if flat_pnl < 0
                                       else QColor("#888"))
                if c == 10:  # Acca P&L
                    item.setForeground(QColor("#22c55e") if acca_pnl > 0
                                       else QColor("#ef4444") if acca_pnl < 0
                                       else QColor("#888"))
                if c == 11 and acca_best > 0:  # Best acca payout
                    item.setForeground(QColor("#fbbf24"))

                # Row background
                if w["perfect_weeks"] > 0 and acca_pnl > 0:
                    item.setBackground(QColor("#2a2a10"))  # gold tint — the goldmine
                elif w["perfect_weeks"] > 0:
                    item.setBackground(QColor("#1a3a2a"))
                elif flat_pnl > 0:
                    item.setBackground(QColor("#1a2a1a"))

                self.weekly_table.setItem(r, c, item)

        self.weekly_table.setSortingEnabled(True)
        self.weekly_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        if weekly:
            # Find combos with perfect weeks AND positive acca P&L
            goldmine = [w for w in weekly if w["perfect_weeks"] > 0 and w.get("acca_profit", 0) > 0]
            top = weekly[0]
            if goldmine:
                g = max(goldmine, key=lambda w: w["acca_profit"])
                self.weekly_label.setText(
                    f"GOLDMINE: T={g['threshold']} LB={g['lookback']} — "
                    f"{g['perfect_weeks']} perfect weeks, "
                    f"acca P&L £{g['acca_profit']:+.0f} (best payout £{g.get('acca_best_payout', 0):.0f}) | "
                    f"Flat: {g.get('flat_profit', 0):+.1f}u, {g['accuracy']:.1f}% acc"
                )
            elif top["perfect_weeks"] > 0:
                self.weekly_label.setText(
                    f"Top: T={top['threshold']} LB={top['lookback']} — "
                    f"{top['perfect_weeks']} perfect weeks, {top['accuracy']:.1f}% overall"
                )
            else:
                self.weekly_label.setText(
                    f"No perfect weeks found. Top accuracy: T={top['threshold']} "
                    f"LB={top['lookback']} -> {top['accuracy']:.1f}%"
                )
        else:
            self.weekly_label.setText("No weekly data generated")

    # ── Double-click: Week-by-week Detail ─────────────────────────────

    def _on_weekly_double_click(self, index):
        row = index.row()
        t_item = self.weekly_table.item(row, 0)
        lb_item = self.weekly_table.item(row, 1)
        if not t_item or not lb_item:
            return

        threshold = int(t_item.text())
        lookback = int(lb_item.text())

        if self._last_results_df is None or self._last_result is None:
            return

        self.main_window.set_status(f"Loading week detail for T={threshold} LB={lookback}...")

        self._detail_thread = QThread()
        self._detail_worker = _DetailWorker(
            self._last_results_df, self._last_table_df,
            threshold, lookback, self.min_week_spin.value(),
            self._last_result,
        )
        self._detail_worker.moveToThread(self._detail_thread)
        self._detail_thread.started.connect(self._detail_worker.run)
        self._detail_worker.finished.connect(
            lambda detail: self._on_detail_finished(detail, threshold, lookback)
        )
        self._detail_worker.error.connect(self._on_error)
        self._detail_worker.finished.connect(self._detail_thread.quit)
        self._detail_worker.error.connect(self._detail_thread.quit)
        self._detail_thread.start()

    def _on_detail_finished(self, detail: list, threshold: int, lookback: int):
        self.detail_header.setText(
            f"Week-by-Week Detail — Threshold={threshold}, Lookback={lookback} "
            f"(Bet365 odds, £5 weekly acca)"
        )

        cols = [
            "Week", "Games", "Correct", "Acc%",
            "Flat P&L", "Acca Odds", "Acca Won?", "Acca Payout",
            "Cum. Flat", "Cum. Acca",
        ]
        self.detail_table.setColumnCount(len(cols))
        self.detail_table.setHorizontalHeaderLabels(cols)
        self.detail_table.setRowCount(len(detail))

        for r, w in enumerate(detail):
            items = [
                str(w["week"]),
                str(w["games"]),
                str(w["correct"]),
                f"{w['accuracy']:.0f}%",
                f"{w['flat_profit']:+.1f}",
                f"{w['acca_odds']:.1f}" if w["acca_odds"] < 100000 else f"{w['acca_odds']:.0f}",
                "YES" if w["acca_won"] else "",
                f"£{w['acca_payout']:.0f}" if w["acca_won"] else "-£5",
                f"{w['cumulative_flat']:+.1f}",
                f"{w['cumulative_acca']:+.1f}",
            ]

            for c, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # 100% week — the goldmine
                if w["accuracy"] >= 100:
                    item.setBackground(QColor("#3a3a10"))
                    if c == 6:  # Acca Won
                        item.setForeground(QColor("#fbbf24"))
                    elif c == 7:  # Payout
                        item.setForeground(QColor("#22c55e"))
                elif w["accuracy"] >= 90:
                    item.setBackground(QColor("#1a3a2a"))
                elif w["accuracy"] < 50:
                    item.setBackground(QColor("#2a1a1a"))

                # Color P&L columns
                if c in (4, 8):  # flat P&L, cumulative flat
                    val = w["flat_profit"] if c == 4 else w["cumulative_flat"]
                    item.setForeground(QColor("#22c55e") if val > 0
                                       else QColor("#ef4444") if val < 0
                                       else QColor("#888"))
                if c == 9:  # cumulative acca
                    val = w["cumulative_acca"]
                    item.setForeground(QColor("#22c55e") if val > 0
                                       else QColor("#ef4444") if val < 0
                                       else QColor("#888"))

                self.detail_table.setItem(r, c, item)

        self.detail_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        # Summary
        if detail:
            total_weeks = len(detail)
            perfect = sum(1 for w in detail if w["accuracy"] >= 100)
            final_flat = detail[-1]["cumulative_flat"]
            final_acca = detail[-1]["cumulative_acca"]
            acca_wins = [w for w in detail if w["acca_won"]]
            biggest = max((w["acca_payout"] for w in acca_wins), default=0)

            self.detail_summary.setText(
                f"Season summary: {total_weeks} weeks | "
                f"{perfect} perfect (100%) weeks | "
                f"Flat staking P&L: {final_flat:+.1f} units | "
                f"Acca P&L (£5/wk): £{final_acca:+.1f} | "
                f"Acca wins: {len(acca_wins)} | "
                f"Biggest payout: £{biggest:.0f}"
            )
        else:
            self.detail_summary.setText("No week data available")

        # Switch to detail tab
        self.result_tabs.setCurrentIndex(3)
        self.main_window.set_status(
            f"Week detail loaded for T={threshold} LB={lookback}"
        )

    # ── Stats ─────────────────────────────────────────────────────────

    def _fill_stats(self, thresholds, lookbacks, accuracy, draw_stats,
                    odds_stats, roi_stats, weekly):
        lines = []
        lines.append("=" * 95)
        lines.append(f"{'T':>3} {'LB':>3} | {'Acc%':>6} | {'Draws':>12} | "
                     f"{'Avg Odds':>8} | {'B365 ROI':>8} | {'Profit':>8} | {'Bets':>5}")
        lines.append("=" * 95)

        for t in thresholds:
            for lb in lookbacks:
                ds = draw_stats.get(t, {}).get(lb, {"correct": 0, "predicted": 0})
                os_data = odds_stats.get(t, {}).get(lb, {"combined": 0, "total": 0, "avg": 0})
                rs = roi_stats.get(t, {}).get(lb, {})
                acc = accuracy.get(t, {}).get(lb, 0)
                draw_acc = (ds["correct"] / ds["predicted"] * 100) if ds["predicted"] > 0 else 0
                roi = rs.get("roi_pct", 0.0)
                profit = rs.get("profit", 0.0)
                stakes = rs.get("stakes", 0)

                marker = "+++" if roi > 10 else "++" if roi > 5 else "+" if roi > 0 else ""

                lines.append(
                    f"T={t:2d} LB={lb:2d} | {acc:5.1f}% | "
                    f"{ds['correct']:3d}/{ds['predicted']:3d} ({draw_acc:4.0f}%) | "
                    f"{os_data.get('avg', 0):7.2f} | "
                    f"{roi:+7.1f}% | {profit:+7.1f}u | {stakes:4d} {marker}"
                )

        lines.append("=" * 95)

        # Profitable combos
        profitable = []
        for t in thresholds:
            for lb in lookbacks:
                rs = roi_stats.get(t, {}).get(lb, {})
                if rs.get("roi_pct", 0) > 0 and rs.get("stakes", 0) >= 20:
                    profitable.append((t, lb, rs["roi_pct"], rs["profit"], rs["stakes"]))
        profitable.sort(key=lambda x: x[2], reverse=True)

        if profitable:
            lines.append(f"\nPROFITABLE AT BET365 (min 20 bets, flat £1 staking):")
            for t, lb, roi, profit, stakes in profitable[:10]:
                acc = accuracy.get(t, {}).get(lb, 0)
                lines.append(
                    f"  T={t:2d} LB={lb:2d} | Acc: {acc:.1f}% | "
                    f"ROI: {roi:+.1f}% | Profit: £{profit:+.1f} over {stakes} bets"
                )

        # Goldmine combos (perfect weeks with acca profit)
        goldmine = [w for w in weekly if w["perfect_weeks"] > 0 and w.get("acca_profit", 0) > 0]
        if goldmine:
            goldmine.sort(key=lambda w: w["acca_profit"], reverse=True)
            lines.append(f"\nGOLDMINE COMBOS (perfect weeks + acca profit at £5/wk):")
            for g in goldmine[:5]:
                lines.append(
                    f"  T={g['threshold']:2d} LB={g['lookback']:2d} | "
                    f"{g['perfect_weeks']} perfect weeks | "
                    f"Acca P&L: £{g['acca_profit']:+.0f} | "
                    f"Best payout: £{g.get('acca_best_payout', 0):.0f} | "
                    f"Flat: {g.get('flat_profit', 0):+.1f}u | "
                    f"Acc: {g['accuracy']:.1f}%"
                )

        if not profitable and not goldmine:
            lines.append("\nNo profitable combos found. Try different ranges or more data.")

        self.stats_text.setPlainText("\n".join(lines))

    def _on_error(self, msg: str):
        self.run_btn.setEnabled(True)
        self.main_window.set_status(f"Backtest error: {msg}")
        self.stats_text.setPlainText(f"Error: {msg}")
