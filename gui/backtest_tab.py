"""Backtest tab — clean, summary-first design.

Replaces the previous 6-subtab wall of numbers with a focused layout:
1. Config bar at top (league, run button)
2. Summary cards showing key findings
3. Two tabs: "Results" (actionable) and "Deep Dive" (for detail lovers)

All profit/ROI uses Bet365 odds.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QTextEdit, QTabWidget, QDoubleSpinBox, QCheckBox,
    QProgressBar, QScrollArea, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QColor, QFont

from core.data_manager import get_available_leagues, load_league_data, load_backtest_data
from core.predictor import MatchPredictor, PredictorConfig


# ── Background workers ─────────────────────────────────────────────


class _BacktestWorker(QObject):
    """Run backtesting in a background thread."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)

    def __init__(self, results_df, table_df, t_min, t_max, lb_min, lb_max,
                 min_week_games, config=None, no_bet_band=0.0,
                 run_tuner=False, n_tuner_candidates=60):
        super().__init__()
        self.results_df = results_df
        self.table_df = table_df
        self.t_min = t_min
        self.t_max = t_max
        self.lb_min = lb_min
        self.lb_max = lb_max
        self.min_week_games = min_week_games
        self.config = config or PredictorConfig()
        self.no_bet_band = no_bet_band
        self.run_tuner = run_tuner
        self.n_tuner_candidates = n_tuner_candidates

    def run(self):
        try:
            config = self.config

            # ── Optional weight tuning first ───────────────────────
            tuner_result = None
            if self.run_tuner:
                self.progress.emit("Tuning weights (this takes a while)...")
                from core.predictor import tune_weights
                tuner_result = tune_weights(
                    self.results_df, self.table_df,
                    n_candidates=self.n_tuner_candidates,
                    lookback_min=self.lb_min, lookback_max=self.lb_max,
                    threshold_min=self.t_min, threshold_max=self.t_max,
                    seed=42,
                )
                best_cfg = tuner_result.get("best_config")
                if best_cfg:
                    config = PredictorConfig(
                        win_weights=best_cfg.get("win_weights", config.win_weights),
                        draw_weights=best_cfg.get("draw_weights", config.draw_weights),
                        loss_close_weights=best_cfg.get("loss_close_weights",
                                                        config.loss_close_weights),
                        loss_heavy_penalty=best_cfg.get("loss_heavy_penalty",
                                                        config.loss_heavy_penalty),
                        heavy_loss_gd=best_cfg.get("heavy_loss_gd", config.heavy_loss_gd),
                        big_win_bonus=best_cfg.get("big_win_bonus", config.big_win_bonus),
                        big_win_gd=best_cfg.get("big_win_gd", config.big_win_gd),
                    )

            # ── Main backtest ──────────────────────────────────────
            self.progress.emit("Running backtest grid search...")
            predictor = MatchPredictor(config)

            is_multi = ("Season" in self.results_df.columns and
                        self.results_df["Season"].nunique() > 1)

            if is_multi:
                result = predictor.backtest_multi_season(
                    self.results_df,
                    self.t_min, self.t_max, self.lb_min, self.lb_max,
                    no_bet_band=self.no_bet_band,
                )
                self.progress.emit("Analyzing weekly performance...")
                weekly = predictor.weekly_performance_multi(
                    result,
                    self.t_min, self.t_max, self.lb_min, self.lb_max,
                    min_week_games=self.min_week_games,
                )
                self.progress.emit("Running walk-forward analysis...")
                try:
                    wf = predictor.walk_forward_analysis(result)
                    result["walk_forward"] = wf
                except Exception:
                    result["walk_forward"] = {"error": "Walk-forward failed"}
            else:
                result = predictor.backtest(
                    self.results_df, self.table_df,
                    self.t_min, self.t_max, self.lb_min, self.lb_max,
                    no_bet_band=self.no_bet_band,
                )
                weekly = predictor.weekly_performance(
                    self.results_df, self.table_df,
                    self.t_min, self.t_max, self.lb_min, self.lb_max,
                    min_week_games=self.min_week_games,
                    backtest_result=result,
                )

            result["weekly"] = weekly
            result["_config"] = config
            if tuner_result:
                result["_tuner"] = tuner_result
            self.finished.emit(result)
        except Exception as exc:
            import traceback
            self.error.emit(f"{exc}\n\n{traceback.format_exc()}")


class _DetailWorker(QObject):
    """Get per-week detail and betting strategy for a specific combo."""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, results_df, table_df, threshold, lookback, min_week_games,
                 backtest_result, config=None):
        super().__init__()
        self.results_df = results_df
        self.table_df = table_df
        self.threshold = threshold
        self.lookback = lookback
        self.min_week_games = min_week_games
        self.backtest_result = backtest_result
        self.config = config or PredictorConfig()

    def run(self):
        try:
            predictor = MatchPredictor(self.config)

            if self.backtest_result.get("_multi_season"):
                detail = predictor.weekly_detail_multi(
                    self.backtest_result,
                    self.threshold, self.lookback,
                    min_week_games=self.min_week_games,
                )
                strategy = predictor.betting_strategy_multi(
                    self.backtest_result,
                    self.threshold, self.lookback,
                    min_week_games=self.min_week_games,
                )
            else:
                detail = predictor.weekly_detail(
                    self.results_df, self.table_df,
                    self.threshold, self.lookback,
                    min_week_games=self.min_week_games,
                    backtest_result=self.backtest_result,
                )
                strategy = predictor.betting_strategy_analysis(
                    self.results_df, self.table_df,
                    self.threshold, self.lookback,
                    min_week_games=self.min_week_games,
                    backtest_result=self.backtest_result,
                )
            self.finished.emit({"detail": detail, "strategy": strategy})
        except Exception as exc:
            self.error.emit(str(exc))


# ── Helper: styled card widget ─────────────────────────────────────


def _card(title: str, content: str, style: str = "default") -> QFrame:
    """Create a styled info card."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.StyledPanel)

    colors = {
        "default": ("#313244", "#45475a"),
        "good":    ("#1a3a2a", "#22c55e"),
        "bad":     ("#3a1a1a", "#ef4444"),
        "warn":    ("#3a3a1a", "#f59e0b"),
        "hero":    ("#2a1a3a", "#cba6f7"),
        "info":    ("#1a2a3a", "#89b4fa"),
    }
    bg, border = colors.get(style, colors["default"])
    frame.setStyleSheet(
        f"QFrame {{ background: {bg}; border-left: 3px solid {border}; "
        f"border-radius: 6px; padding: 12px; }}"
    )

    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 8, 12, 8)
    layout.setSpacing(4)

    if title:
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(f"color: {border}; font-weight: bold; font-size: 12pt; background: transparent;")
        layout.addWidget(title_lbl)

    body = QLabel(content)
    body.setWordWrap(True)
    body.setStyleSheet("color: #cdd6f4; font-size: 10pt; background: transparent;")
    layout.addWidget(body)

    return frame


# ── Main tab ───────────────────────────────────────────────────────


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
        self._last_config = None
        self._last_league_code = None
        self._last_league_name = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ── Config bar ─────────────────────────────────────────────
        config_group = QGroupBox("Configuration")
        config_layout = QVBoxLayout(config_group)
        config_layout.setSpacing(6)

        # Row 1: League + Run button
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("League:"))
        self.league_combo = QComboBox()
        self.league_combo.setMinimumWidth(220)
        row1.addWidget(self.league_combo)

        row1.addStretch()

        self.optimize_check = QCheckBox("Optimize Weights")
        self.optimize_check.setToolTip(
            "Also run weight optimization (slower but may improve results).\n"
            "Tests 60 random weight configurations and picks the best."
        )
        row1.addWidget(self.optimize_check)

        self.current_season_check = QCheckBox("Current Season Only")
        self.current_season_check.setToolTip(
            "Only backtest on this season's matches.\n"
            "Faster, but less data to learn from."
        )
        row1.addWidget(self.current_season_check)

        self.run_btn = QPushButton("Run Analysis")
        self.run_btn.setProperty("success", True)
        self.run_btn.setMinimumWidth(140)
        self.run_btn.clicked.connect(self._on_run)
        row1.addWidget(self.run_btn)
        config_layout.addLayout(row1)

        # Row 2: Advanced settings (collapsed by default feel)
        row2 = QHBoxLayout()
        row2.setSpacing(8)

        row2.addWidget(QLabel("Threshold range:"))
        self.t_min_spin = QSpinBox()
        self.t_min_spin.setRange(1, 20)
        self.t_min_spin.setValue(1)
        self.t_min_spin.setMinimumWidth(50)
        row2.addWidget(self.t_min_spin)
        row2.addWidget(QLabel("-"))
        self.t_max_spin = QSpinBox()
        self.t_max_spin.setRange(1, 20)
        self.t_max_spin.setValue(10)
        self.t_max_spin.setMinimumWidth(50)
        row2.addWidget(self.t_max_spin)

        row2.addWidget(QLabel("  Lookback range:"))
        self.lb_min_spin = QSpinBox()
        self.lb_min_spin.setRange(3, 20)
        self.lb_min_spin.setValue(3)
        self.lb_min_spin.setMinimumWidth(50)
        row2.addWidget(self.lb_min_spin)
        row2.addWidget(QLabel("-"))
        self.lb_max_spin = QSpinBox()
        self.lb_max_spin.setRange(3, 20)
        self.lb_max_spin.setValue(14)
        self.lb_max_spin.setMinimumWidth(50)
        row2.addWidget(self.lb_max_spin)

        row2.addWidget(QLabel("  Min games/week:"))
        self.min_week_spin = QSpinBox()
        self.min_week_spin.setRange(1, 20)
        self.min_week_spin.setValue(3)
        self.min_week_spin.setMinimumWidth(50)
        row2.addWidget(self.min_week_spin)

        row2.addStretch()

        self.export_btn = QPushButton("Export Report")
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip("Export a clean HTML report you can open in your browser")
        self.export_btn.clicked.connect(self._on_export_report)
        row2.addWidget(self.export_btn)
        config_layout.addLayout(row2)

        layout.addWidget(config_group)

        # ── Progress ───────────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)  # indeterminate
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(6)
        layout.addWidget(self.progress_bar)

        # ── Results area (two tabs: Summary + Detail) ──────────────
        self.result_tabs = QTabWidget()

        # Tab 1: Summary (the main thing people see)
        summary_scroll = QScrollArea()
        summary_scroll.setWidgetResizable(True)
        summary_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.summary_container = QWidget()
        self.summary_layout = QVBoxLayout(self.summary_container)
        self.summary_layout.setSpacing(8)
        self.summary_layout.setContentsMargins(4, 4, 4, 4)
        # Placeholder
        self.summary_layout.addWidget(
            _card("", "Select a league and click 'Run Analysis' to see results.", "info")
        )
        self.summary_layout.addStretch()
        summary_scroll.setWidget(self.summary_container)
        self.result_tabs.addTab(summary_scroll, "Summary")

        # Tab 2: Accuracy heatmap
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

        # Tab 3: ROI heatmap
        roi_widget = QWidget()
        roi_layout = QVBoxLayout(roi_widget)
        self.roi_table = QTableWidget()
        self.roi_table.setAlternatingRowColors(False)
        self.roi_table.verticalHeader().setVisible(True)
        roi_layout.addWidget(self.roi_table)
        self.roi_label = QLabel("")
        self.roi_label.setProperty("heading", True)
        roi_layout.addWidget(self.roi_label)
        self.result_tabs.addTab(roi_widget, "ROI Grid")

        # Tab 4: Top combos table (replaces old weekly + detail + strategy tabs)
        combos_widget = QWidget()
        combos_layout = QVBoxLayout(combos_widget)
        combos_hint = QLabel("Double-click any row to see week-by-week breakdown and betting strategy")
        combos_hint.setStyleSheet("color: #888; font-style: italic;")
        combos_layout.addWidget(combos_hint)
        self.combos_table = QTableWidget()
        self.combos_table.setAlternatingRowColors(True)
        self.combos_table.setSortingEnabled(True)
        self.combos_table.verticalHeader().setVisible(False)
        self.combos_table.doubleClicked.connect(self._on_combo_double_click)
        combos_layout.addWidget(self.combos_table)
        self.result_tabs.addTab(combos_widget, "All Combos")

        # Tab 5: Detail view (populated on double-click)
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        self.detail_header = QLabel("Double-click a combo in 'All Combos' to load detail")
        self.detail_header.setProperty("heading", True)
        detail_layout.addWidget(self.detail_header)
        self.detail_table = QTableWidget()
        self.detail_table.setAlternatingRowColors(True)
        self.detail_table.verticalHeader().setVisible(False)
        detail_layout.addWidget(self.detail_table)
        self.detail_summary = QLabel("")
        self.detail_summary.setWordWrap(True)
        detail_layout.addWidget(self.detail_summary)
        # Betting strategy sub-section
        self.strat_table = QTableWidget()
        self.strat_table.setAlternatingRowColors(True)
        self.strat_table.verticalHeader().setVisible(False)
        self.strat_table.setMaximumHeight(250)
        detail_layout.addWidget(self.strat_table)
        self.result_tabs.addTab(detail_widget, "Week Detail")

        layout.addWidget(self.result_tabs)

    # ── Refresh ────────────────────────────────────────────────────

    def refresh_leagues(self):
        current = self.league_combo.currentText()
        self.league_combo.clear()
        for code, name in get_available_leagues():
            self.league_combo.addItem(name, code)
        idx = self.league_combo.findText(current)
        if idx >= 0:
            self.league_combo.setCurrentIndex(idx)

    # ── Run ────────────────────────────────────────────────────────

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
        if self.current_season_check.isChecked():
            bt_results = results_df
        else:
            backtest_df = load_backtest_data(code)
            if backtest_df is not None and len(backtest_df) > len(results_df):
                bt_results = backtest_df
            else:
                bt_results = results_df

        self._last_results_df = bt_results
        self._last_table_df = table_df
        self._last_league_code = code
        self._last_league_name = self.league_combo.currentText()

        t_min = self.t_min_spin.value()
        t_max = self.t_max_spin.value()
        lb_min = self.lb_min_spin.value()
        lb_max = self.lb_max_spin.value()
        min_week = self.min_week_spin.value()

        # Check for already-tuned weights
        config = PredictorConfig()
        tuned = getattr(self.main_window, "tuned_config", None)
        if tuned and not self.optimize_check.isChecked():
            config = PredictorConfig(
                win_weights=tuned.get("win_weights", config.win_weights),
                draw_weights=tuned.get("draw_weights", config.draw_weights),
                loss_close_weights=tuned.get("loss_close_weights",
                                              config.loss_close_weights),
                loss_heavy_penalty=tuned.get("loss_heavy_penalty",
                                              config.loss_heavy_penalty),
                heavy_loss_gd=tuned.get("heavy_loss_gd", config.heavy_loss_gd),
                big_win_bonus=tuned.get("big_win_bonus", config.big_win_bonus),
                big_win_gd=tuned.get("big_win_gd", config.big_win_gd),
            )

        self.run_btn.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.progress_bar.setVisible(True)

        n_matches = len(bt_results)
        n_seasons = bt_results["Season"].nunique() if "Season" in bt_results.columns else 1
        self.main_window.set_status(
            f"Analyzing {n_matches} matches across {n_seasons} season(s)..."
        )

        self._thread = QThread()
        self._worker = _BacktestWorker(
            bt_results, table_df, t_min, t_max, lb_min, lb_max, min_week,
            config=config, no_bet_band=0.0,
            run_tuner=self.optimize_check.isChecked(),
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.progress.connect(
            lambda msg: self.main_window.set_status(msg)
        )
        self._worker.finished.connect(self._thread.quit)
        self._worker.error.connect(self._thread.quit)
        self._thread.start()

    # ── Finished ───────────────────────────────────────────────────

    def _on_finished(self, result: dict):
        self.run_btn.setEnabled(True)
        self.export_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._last_result = result
        self._last_config = result.get("_config", PredictorConfig())

        accuracy = result["accuracy"]
        roi_stats = result.get("roi_stats", {})
        best = result["best"]
        best_roi = result.get("best_roi", (0, 0, -999))
        weekly = result.get("weekly", [])

        thresholds = sorted(accuracy.keys())
        lookbacks = sorted({lb for t in accuracy.values() for lb in t})

        # Store tuned config if available
        tuner_result = result.get("_tuner")
        if tuner_result and tuner_result.get("best_config"):
            self.main_window.tuned_config = tuner_result["best_config"]

        # Populate all tabs
        self._fill_summary(result, thresholds, lookbacks)
        self._fill_accuracy_grid(thresholds, lookbacks, accuracy, best)
        self._fill_roi_grid(thresholds, lookbacks, roi_stats, best_roi)
        self._fill_combos_table(weekly)

        n_matches = len(self._last_results_df) if self._last_results_df is not None else 0
        n_seasons = 1
        if self._last_results_df is not None and "Season" in self._last_results_df.columns:
            n_seasons = self._last_results_df["Season"].nunique()

        self.main_window.set_status(
            f"Analysis complete: {n_matches} matches, {n_seasons} season(s). "
            f"Best accuracy: T={best[0]} LB={best[1]} = {best[2]:.1f}%"
        )

        # Switch to summary tab
        self.result_tabs.setCurrentIndex(0)

    # ── Summary tab (the key tab — clean, actionable) ──────────────

    def _fill_summary(self, result, thresholds, lookbacks):
        # Clear previous summary
        while self.summary_layout.count():
            item = self.summary_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        best = result["best"]
        best_roi = result.get("best_roi", (0, 0, -999))
        accuracy = result["accuracy"]
        roi_stats = result.get("roi_stats", {})
        draw_stats = result.get("draw_stats", {})
        weekly = result.get("weekly", [])
        is_multi = result.get("_multi_season", False)
        n_seasons = result.get("n_seasons", 1)
        seasons = result.get("seasons", [])
        wf = result.get("walk_forward")

        # ── Card 1: Recommendation ─────────────────────────────────
        best_t, best_lb, best_acc = best
        best_roi_t, best_roi_lb, best_roi_pct = best_roi

        # Get ROI for best-accuracy combo
        acc_roi = roi_stats.get(best_t, {}).get(best_lb, {})
        acc_roi_pct = acc_roi.get("roi_pct", 0)
        acc_stakes = acc_roi.get("stakes", 0)
        acc_profit = acc_roi.get("profit", 0)

        # Walk-forward recommendation
        wf_combo = None
        if wf and "recommendations" in wf:
            rec = wf["recommendations"].get("accuracy")
            if rec:
                wf_combo = rec["combo"]

        if wf_combo:
            rec_t, rec_lb = wf_combo
            rec_acc = accuracy.get(rec_t, {}).get(rec_lb, 0)
            rec_roi_data = roi_stats.get(rec_t, {}).get(rec_lb, {})
            rec_roi = rec_roi_data.get("roi_pct", 0)
            rec_stakes = rec_roi_data.get("stakes", 0)

            self.summary_layout.addWidget(_card(
                "RECOMMENDED SETTINGS (walk-forward validated)",
                f"Threshold = {rec_t}  |  Lookback = {rec_lb}\n"
                f"Accuracy: {rec_acc:.1f}%  |  ROI: {rec_roi:+.1f}%  |  "
                f"Based on {rec_stakes} bets across {n_seasons} seasons\n\n"
                f"These settings were found by training on past seasons and testing "
                f"on seasons the model hadn't seen (walk-forward validation).",
                "hero"
            ))
        else:
            self.summary_layout.addWidget(_card(
                "BEST SETTINGS FOUND",
                f"Best Accuracy: Threshold = {best_t}  |  Lookback = {best_lb}\n"
                f"Accuracy: {best_acc:.1f}%  |  ROI: {acc_roi_pct:+.1f}%  |  "
                f"{acc_stakes} bets  |  Profit: {acc_profit:+.1f} units\n\n"
                + (f"Best ROI: Threshold = {best_roi_t}  |  Lookback = {best_roi_lb}\n"
                   f"ROI: {best_roi_pct:+.1f}%"
                   if best_roi_pct > -999 and (best_roi_t, best_roi_lb) != (best_t, best_lb)
                   else ""),
                "hero"
            ))

        # ── Card 2: Does it actually make money? ───────────────────
        if acc_roi_pct > 5:
            self.summary_layout.addWidget(_card(
                "PROFITABLE",
                f"Flat staking at Bet365 odds: {acc_roi_pct:+.1f}% ROI\n"
                f"Profit: {acc_profit:+.1f} units over {acc_stakes} bets\n"
                f"This means for every 100 pounds staked, you'd make "
                f"{acc_roi_pct:.0f} pounds profit (historically).",
                "good"
            ))
        elif acc_roi_pct > 0:
            self.summary_layout.addWidget(_card(
                "MARGINALLY PROFITABLE",
                f"Flat staking at Bet365 odds: {acc_roi_pct:+.1f}% ROI\n"
                f"Profit: {acc_profit:+.1f} units over {acc_stakes} bets\n"
                f"Small edge — could go either way. Consider using better odds "
                f"(shop around) or trying different fold sizes.",
                "warn"
            ))
        elif acc_stakes > 0:
            self.summary_layout.addWidget(_card(
                "NOT PROFITABLE AT FLAT STAKING",
                f"Flat staking at Bet365 odds: {acc_roi_pct:+.1f}% ROI\n"
                f"Loss: {acc_profit:+.1f} units over {acc_stakes} bets\n"
                f"Singles betting doesn't work at these settings. "
                f"Try 'Optimize Weights' or check if multiples (doubles/trebles) do better.",
                "bad"
            ))

        # ── Card 3: Perfect weeks / Accumulators ───────────────────
        goldmine = [w for w in weekly
                    if w["perfect_weeks"] > 0 and w.get("acca_profit", 0) > 0]

        if goldmine:
            g = max(goldmine, key=lambda w: w["acca_profit"])
            self.summary_layout.addWidget(_card(
                "ACCUMULATOR OPPORTUNITY",
                f"T={g['threshold']} LB={g['lookback']} had "
                f"{g['perfect_weeks']} perfect weeks (100% correct)\n"
                f"Acca P&L at 5/wk: {g['acca_profit']:+.0f}\n"
                f"Best single payout: {g.get('acca_best_payout', 0):.0f}\n\n"
                f"Double-click this combo in 'All Combos' to see the full breakdown.",
                "good"
            ))
        else:
            perfect_any = [w for w in weekly if w["perfect_weeks"] > 0]
            if perfect_any:
                p = max(perfect_any, key=lambda w: w["perfect_weeks"])
                self.summary_layout.addWidget(_card(
                    "PERFECT WEEKS FOUND",
                    f"T={p['threshold']} LB={p['lookback']} had "
                    f"{p['perfect_weeks']} perfect week(s) where every prediction was correct.\n"
                    f"Acca P&L: {p.get('acca_profit', 0):+.0f} (not profitable overall, "
                    f"but shows the model can get them all right sometimes).",
                    "info"
                ))

        # ── Card 4: Season consistency (multi-season only) ─────────
        per_season = result.get("_per_season")
        if per_season and len(seasons) > 1:
            from core.leagues import season_display
            profitable_seasons = 0
            season_details = []
            for season in seasons:
                bt = per_season[season]["bt"]
                # Use the recommended or best combo
                use_t = wf_combo[0] if wf_combo else best_t
                use_lb = wf_combo[1] if wf_combo else best_lb
                sr = bt["roi_stats"].get(use_t, {}).get(use_lb, {})
                roi = sr.get("roi_pct", 0)
                stakes = sr.get("stakes", 0)
                if roi > 0 and stakes >= 5:
                    profitable_seasons += 1
                season_details.append(f"{season_display(season)}: {roi:+.1f}%")

            consistency = profitable_seasons / len(seasons) * 100
            style = "good" if consistency >= 60 else "warn" if consistency >= 40 else "bad"

            self.summary_layout.addWidget(_card(
                f"CONSISTENCY: {profitable_seasons}/{len(seasons)} seasons profitable "
                f"({consistency:.0f}%)",
                "  |  ".join(season_details) + "\n\n"
                + ("Good consistency across seasons." if consistency >= 60
                   else "Mixed results — some seasons work, some don't. "
                        "Be cautious." if consistency >= 40
                   else "Poor consistency. The model doesn't reliably predict "
                        "across different seasons."),
                style
            ))

        # ── Card 5: Walk-forward summary ───────────────────────────
        if wf and "summary" in wf:
            best_ws = wf.get("best_ws_acc", 1)
            ws_data = wf["summary"].get(best_ws, {})
            if ws_data:
                self.summary_layout.addWidget(_card(
                    f"WALK-FORWARD: Best training window = {best_ws} season(s)",
                    f"Average out-of-sample accuracy: {ws_data['avg_test_acc']:.1f}%\n"
                    f"Average out-of-sample ROI: {ws_data['avg_test_roi']:+.1f}%\n"
                    f"Tested on {ws_data['n_tests']} seasons\n\n"
                    f"This tells you how well past patterns predict future results. "
                    f"{'Positive ROI = the model has genuine predictive power.'  if ws_data['avg_test_roi'] > 0 else 'Negative ROI = past patterns may not reliably predict the future.'}",
                    "good" if ws_data['avg_test_roi'] > 0 else "warn"
                ))

        # ── Card 6: How to read these numbers ──────────────────────
        self.summary_layout.addWidget(_card(
            "WHAT DO THESE NUMBERS MEAN?",
            "Threshold = how big the score gap needs to be to predict a win "
            "(instead of a draw). Lower = more decisive, higher = more draws.\n\n"
            "Lookback = how many recent matches to consider for each team's form.\n\n"
            "Accuracy = % of predictions that were correct. "
            "Random guessing on 3 outcomes (H/D/A) = ~33%. Anything above 40% is meaningful.\n\n"
            "ROI = return on investment from flat 1-unit staking at Bet365 odds. "
            "Positive = profit, negative = loss.\n\n"
            "Click 'Export Report' for a clean printable version of these results.",
            "info"
        ))

        # ── Card 7: Weight tuning results ──────────────────────────
        tuner = result.get("_tuner")
        if tuner and tuner.get("best_config"):
            lb_df = tuner.get("leaderboard")
            if lb_df is not None and not lb_df.empty:
                top = lb_df.iloc[0]
                self.summary_layout.addWidget(_card(
                    "WEIGHT OPTIMIZATION RESULTS",
                    f"Tested {len(lb_df)} random weight configurations.\n"
                    f"Best: T={int(top['threshold'])} LB={int(top['lookback'])}\n"
                    f"  Train accuracy: {top['train_acc']:.1f}% | "
                    f"Validation accuracy: {top['valid_acc']:.1f}%\n"
                    f"  Blended score: {top['blended_acc']:.1f}%\n\n"
                    f"These optimized weights are already applied to all results above.",
                    "info"
                ))

        self.summary_layout.addStretch()

    # ── Accuracy Grid ──────────────────────────────────────────────

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

    # ── ROI Grid ───────────────────────────────────────────────────

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

                text = f"{roi_pct:+.1f}%" if stakes > 0 else "-"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(
                    f"ROI: {roi_pct:+.1f}%\n"
                    f"Profit: {profit:+.1f} units\n"
                    f"Bets: {stakes}"
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
                f"ROI={best_roi[2]:+.1f}% (flat staking, Bet365 odds)"
            )
        else:
            self.roi_label.setText("No combos with enough bets to calculate ROI")

    # ── All Combos table ───────────────────────────────────────────

    def _fill_combos_table(self, weekly):
        cols = [
            "T", "LB", "Acc%", "Games", "100%", "90%+", "80%+",
            "Weeks", "Flat P&L", "Flat ROI%",
            "Acca P&L", "Best Acca",
        ]
        self.combos_table.setSortingEnabled(False)
        self.combos_table.setColumnCount(len(cols))
        self.combos_table.setHorizontalHeaderLabels(cols)
        self.combos_table.setRowCount(len(weekly))

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
                f"{acca_best:.0f}" if acca_best > 0 else "-",
            ]

            for c, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if c == 4 and w["perfect_weeks"] > 0:
                    item.setForeground(QColor("#fbbf24"))
                if c == 8:
                    item.setForeground(QColor("#22c55e") if flat_pnl > 0
                                       else QColor("#ef4444") if flat_pnl < 0
                                       else QColor("#888"))
                if c == 10:
                    item.setForeground(QColor("#22c55e") if acca_pnl > 0
                                       else QColor("#ef4444") if acca_pnl < 0
                                       else QColor("#888"))
                if c == 11 and acca_best > 0:
                    item.setForeground(QColor("#fbbf24"))

                if w["perfect_weeks"] > 0 and acca_pnl > 0:
                    item.setBackground(QColor("#2a2a10"))
                elif flat_pnl > 0:
                    item.setBackground(QColor("#1a2a1a"))

                self.combos_table.setItem(r, c, item)

        self.combos_table.setSortingEnabled(True)
        self.combos_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

    # ── Double-click: load detail ──────────────────────────────────

    def _on_combo_double_click(self, index):
        row = index.row()
        t_item = self.combos_table.item(row, 0)
        lb_item = self.combos_table.item(row, 1)
        if not t_item or not lb_item:
            return

        threshold = int(t_item.text())
        lookback = int(lb_item.text())

        if self._last_results_df is None or self._last_result is None:
            return

        self.main_window.set_status(f"Loading detail for T={threshold} LB={lookback}...")

        self._detail_thread = QThread()
        self._detail_worker = _DetailWorker(
            self._last_results_df, self._last_table_df,
            threshold, lookback, self.min_week_spin.value(),
            self._last_result,
            config=self._last_result.get("_config", PredictorConfig()),
        )
        self._detail_worker.moveToThread(self._detail_thread)
        self._detail_thread.started.connect(self._detail_worker.run)
        self._detail_worker.finished.connect(
            lambda d: self._on_detail_finished(d, threshold, lookback)
        )
        self._detail_worker.error.connect(self._on_error)
        self._detail_worker.finished.connect(self._detail_thread.quit)
        self._detail_worker.error.connect(self._detail_thread.quit)
        self._detail_thread.start()

    def _on_detail_finished(self, result: dict, threshold: int, lookback: int):
        detail = result.get("detail", [])
        strategy = result.get("strategy", {})

        is_multi = detail and "season" in detail[0]
        n_seasons_txt = ""
        if is_multi:
            seasons_in_detail = sorted(set(w["season"] for w in detail))
            n_seasons_txt = f" across {len(seasons_in_detail)} seasons"

        self.detail_header.setText(
            f"T={threshold}, LB={lookback}{n_seasons_txt}"
        )

        # Week detail table
        if is_multi:
            cols = ["Season", "Wk", "Games", "Correct", "Acc%",
                    "Flat P&L", "Acca Odds", "Won?", "Payout",
                    "Cum Flat", "Cum Acca"]
        else:
            cols = ["Wk", "Games", "Correct", "Acc%",
                    "Flat P&L", "Acca Odds", "Won?", "Payout",
                    "Cum Flat", "Cum Acca"]

        self.detail_table.setColumnCount(len(cols))
        self.detail_table.setHorizontalHeaderLabels(cols)
        self.detail_table.setRowCount(len(detail))

        for r, w in enumerate(detail):
            items = []
            if is_multi:
                items.append(w["season"])
            items += [
                str(w["week"]),
                str(w["games"]),
                str(w["correct"]),
                f"{w['accuracy']:.0f}%",
                f"{w['flat_profit']:+.1f}",
                f"{w['acca_odds']:.1f}" if w["acca_odds"] < 100000 else f"{w['acca_odds']:.0f}",
                "YES" if w["acca_won"] else "",
                f"{w['acca_payout']:.0f}" if w["acca_won"] else "-5",
                f"{w['cumulative_flat']:+.1f}",
                f"{w['cumulative_acca']:+.1f}",
            ]

            off = 1 if is_multi else 0
            for c, text in enumerate(items):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if w["accuracy"] >= 100:
                    item.setBackground(QColor("#3a3a10"))
                    if c == 6 + off:
                        item.setForeground(QColor("#fbbf24"))
                    elif c == 7 + off:
                        item.setForeground(QColor("#22c55e"))
                elif w["accuracy"] >= 90:
                    item.setBackground(QColor("#1a3a2a"))
                elif w["accuracy"] < 50:
                    item.setBackground(QColor("#2a1a1a"))

                if c in (4 + off, 8 + off):
                    val = w["flat_profit"] if c == 4 + off else w["cumulative_flat"]
                    item.setForeground(QColor("#22c55e") if val > 0
                                       else QColor("#ef4444") if val < 0
                                       else QColor("#888"))
                if c == 9 + off:
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
                f"{total_weeks} weeks | {perfect} perfect | "
                f"Flat P&L: {final_flat:+.1f}u | "
                f"Acca P&L: {final_acca:+.1f} | "
                f"Acca wins: {len(acca_wins)} | "
                f"Best payout: {biggest:.0f}"
            )
        else:
            self.detail_summary.setText("No data")

        # Betting strategy table
        fold_summary = strategy.get("fold_summary", {})
        if fold_summary:
            strat_cols = [
                "Fold", "Lines/Wk", "Total", "Staked",
                "Winners", "Returned", "Profit", "ROI%", "Best Hit",
            ]
            self.strat_table.setColumnCount(len(strat_cols))
            self.strat_table.setHorizontalHeaderLabels(strat_cols)
            self.strat_table.setRowCount(len(fold_summary))

            for r, (k, fs) in enumerate(sorted(fold_summary.items())):
                data = [
                    fs["name"],
                    str(fs["lines_per_week"]),
                    str(fs["total_lines"]),
                    f"{fs['staked']:,.0f}",
                    str(fs["winners"]),
                    f"{fs['returned']:,.2f}",
                    f"{fs['profit']:+,.2f}",
                    f"{fs['roi_pct']:+.1f}%",
                    f"{fs['best_payout']:,.2f}" if fs["best_payout"] > 0 else "-",
                ]
                for c, text in enumerate(data):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if c == 6:
                        item.setForeground(
                            QColor("#22c55e") if fs["profit"] > 0
                            else QColor("#ef4444") if fs["profit"] < 0
                            else QColor("#888")
                        )
                    if c == 7:
                        item.setForeground(
                            QColor("#22c55e") if fs["roi_pct"] > 0
                            else QColor("#ef4444") if fs["roi_pct"] < 0
                            else QColor("#888")
                        )
                    if fs["profit"] > 0:
                        item.setBackground(QColor("#1a2a1a"))
                    self.strat_table.setItem(r, c, item)

            self.strat_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Stretch
            )

        # Switch to detail tab
        self.result_tabs.setCurrentIndex(4)

        self.main_window.set_status(
            f"Detail loaded for T={threshold} LB={lookback}"
        )

    # ── Error handling ─────────────────────────────────────────────

    def _on_error(self, msg: str):
        self.run_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.main_window.set_status(f"Error: {msg.split(chr(10))[0]}")

        # Show error in summary
        while self.summary_layout.count():
            item = self.summary_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.summary_layout.addWidget(_card(
            "ERROR",
            f"The backtest failed with this error:\n\n{msg}\n\n"
            "Try downloading fresh data or using different settings.",
            "bad"
        ))
        self.summary_layout.addStretch()

    # ── Export report ──────────────────────────────────────────────

    def _on_export_report(self):
        if self._last_result is None:
            self.main_window.set_status("Run analysis first")
            return

        from PyQt6.QtWidgets import QFileDialog
        from core.report import generate_report

        config = self._last_config or PredictorConfig()
        predictor = MatchPredictor(config)

        results_df = fixtures_df = table_df = None
        if self._last_league_code:
            data = load_league_data(self._last_league_code)
            if data:
                results_df, fixtures_df, table_df = data

        try:
            html = generate_report(
                self._last_result,
                predictor,
                league_name=self._last_league_name or "Unknown League",
                results_df=results_df,
                fixtures_df=fixtures_df,
                table_df=table_df,
            )
        except Exception as exc:
            self.main_window.set_status(f"Report error: {exc}")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Save Report",
            f"{self._last_league_name or 'backtest'}_report.html",
            "HTML Files (*.html);;All Files (*)",
        )
        if not path:
            return

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            self.main_window.set_status(f"Report saved: {path}")
            import webbrowser
            webbrowser.open(f"file://{path}")
        except Exception as exc:
            self.main_window.set_status(f"Save error: {exc}")
