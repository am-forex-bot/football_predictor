"""Value Betting tab — Poisson model, value detection, Kelly staking, bankroll management.

Shows value bets with edge %, Kelly stake, EV, and bankroll tracking.
Integrates Poisson model probabilities with bookmaker odds to find +EV opportunities.
"""

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QSpinBox, QDoubleSpinBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QTabWidget, QFrame,
    QSplitter, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from core.data_manager import get_available_leagues, load_league_data
from core.poisson_model import PoissonModel, PoissonConfig
from core.value_engine import (
    ValueEngine, BankrollConfig, odds_to_prob, calculate_edge,
    kelly_stake, expected_value,
)


class _ValueWorker(QThread):
    """Run value bet analysis in background thread."""
    finished = pyqtSignal(list, dict, list)  # value_bets, backtest_results, ratings
    error = pyqtSignal(str)

    def __init__(self, results_df, fixtures_df, bankroll_cfg, poisson_cfg, run_backtest=False):
        super().__init__()
        self.results_df = results_df
        self.fixtures_df = fixtures_df
        self.bankroll_cfg = bankroll_cfg
        self.poisson_cfg = poisson_cfg
        self.run_backtest = run_backtest

    def run(self):
        try:
            engine = ValueEngine(self.bankroll_cfg, self.poisson_cfg)

            # Find value bets
            if self.fixtures_df is not None and not self.fixtures_df.empty:
                value_bets = engine.find_value_bets(self.results_df, self.fixtures_df)
            else:
                value_bets = []
                # Still fit the model for ratings
                engine.poisson.fit(self.results_df)

            # Backtest if requested
            bt = {}
            if self.run_backtest:
                bt = engine.backtest_value(self.results_df)

            # Team ratings
            ratings = engine.poisson.get_team_ratings()

            self.finished.emit(value_bets, bt, ratings)
        except Exception as e:
            self.error.emit(str(e))


class ValueTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self._worker = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ── Configuration ─────────────────────────────────────────────
        config_group = QGroupBox("Value Betting Configuration")
        config_layout = QHBoxLayout(config_group)
        config_layout.setSpacing(6)

        config_layout.addWidget(QLabel("League:"))
        self.league_combo = QComboBox()
        self.league_combo.setMinimumWidth(180)
        config_layout.addWidget(self.league_combo)

        config_layout.addWidget(QLabel("  Min Edge %:"))
        self.min_edge_spin = QDoubleSpinBox()
        self.min_edge_spin.setRange(1.0, 20.0)
        self.min_edge_spin.setSingleStep(0.5)
        self.min_edge_spin.setValue(3.0)
        self.min_edge_spin.setDecimals(1)
        self.min_edge_spin.setToolTip(
            "Minimum edge required to flag a value bet.\n"
            "3% is aggressive, 5% is conservative."
        )
        config_layout.addWidget(self.min_edge_spin)

        config_layout.addWidget(QLabel("  Kelly %:"))
        self.kelly_spin = QDoubleSpinBox()
        self.kelly_spin.setRange(5.0, 100.0)
        self.kelly_spin.setSingleStep(5.0)
        self.kelly_spin.setValue(25.0)
        self.kelly_spin.setDecimals(0)
        self.kelly_spin.setToolTip(
            "Fraction of full Kelly criterion to use.\n"
            "25% (quarter Kelly) is standard. Higher = more variance."
        )
        config_layout.addWidget(self.kelly_spin)

        config_layout.addWidget(QLabel("  Bankroll:"))
        self.bankroll_spin = QDoubleSpinBox()
        self.bankroll_spin.setRange(10.0, 100000.0)
        self.bankroll_spin.setSingleStep(100.0)
        self.bankroll_spin.setValue(1000.0)
        self.bankroll_spin.setDecimals(0)
        self.bankroll_spin.setPrefix("£")
        config_layout.addWidget(self.bankroll_spin)

        config_layout.addStretch()

        self.run_btn = QPushButton("Find Value Bets")
        self.run_btn.setProperty("success", True)
        self.run_btn.clicked.connect(self._on_run)
        config_layout.addWidget(self.run_btn)

        self.backtest_btn = QPushButton("Backtest Strategy")
        self.backtest_btn.clicked.connect(self._on_backtest)
        config_layout.addWidget(self.backtest_btn)

        layout.addWidget(config_group)

        # ── Sub-tabs ──────────────────────────────────────────────────
        self.sub_tabs = QTabWidget()
        self.sub_tabs.setDocumentMode(True)

        # Tab 1: Value Bets
        self._init_value_bets_tab()
        self.sub_tabs.addTab(self.value_bets_widget, "Value Bets")

        # Tab 2: Match Probabilities
        self._init_probabilities_tab()
        self.sub_tabs.addTab(self.prob_widget, "Match Probabilities")

        # Tab 3: Team Ratings
        self._init_ratings_tab()
        self.sub_tabs.addTab(self.ratings_widget, "Team Ratings")

        # Tab 4: Bankroll Tracker
        self._init_bankroll_tab()
        self.sub_tabs.addTab(self.bankroll_widget, "Bankroll")

        # Tab 5: Backtest Results
        self._init_backtest_tab()
        self.sub_tabs.addTab(self.bt_widget, "Backtest")

        layout.addWidget(self.sub_tabs)

    # ── Value Bets sub-tab ────────────────────────────────────────────

    def _init_value_bets_tab(self):
        self.value_bets_widget = QWidget()
        layout = QVBoxLayout(self.value_bets_widget)

        # Summary cards
        self.vb_summary = QLabel("Run analysis to find value betting opportunities.")
        self.vb_summary.setWordWrap(True)
        self.vb_summary.setProperty("heading", True)
        layout.addWidget(self.vb_summary)

        # Value bets table
        self.vb_table = QTableWidget()
        cols = [
            "Match", "Market", "Selection", "Model %", "Implied %",
            "Edge %", "Best Odds", "Kelly Stake", "EV (£)", "xG",
        ]
        self.vb_table.setColumnCount(len(cols))
        self.vb_table.setHorizontalHeaderLabels(cols)
        self.vb_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.vb_table.setAlternatingRowColors(True)
        self.vb_table.setSortingEnabled(True)
        self.vb_table.verticalHeader().setVisible(False)
        layout.addWidget(self.vb_table)

    # ── Match Probabilities sub-tab ───────────────────────────────────

    def _init_probabilities_tab(self):
        self.prob_widget = QWidget()
        layout = QVBoxLayout(self.prob_widget)

        self.prob_summary = QLabel("Poisson model match probabilities will appear here.")
        self.prob_summary.setWordWrap(True)
        layout.addWidget(self.prob_summary)

        self.prob_table = QTableWidget()
        cols = [
            "Match", "Home xG", "Away xG", "P(Home)", "P(Draw)", "P(Away)",
            "P(O2.5)", "P(BTTS)", "Top Score",
        ]
        self.prob_table.setColumnCount(len(cols))
        self.prob_table.setHorizontalHeaderLabels(cols)
        self.prob_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.prob_table.setAlternatingRowColors(True)
        self.prob_table.setSortingEnabled(True)
        self.prob_table.verticalHeader().setVisible(False)
        layout.addWidget(self.prob_table)

    # ── Team Ratings sub-tab ──────────────────────────────────────────

    def _init_ratings_tab(self):
        self.ratings_widget = QWidget()
        layout = QVBoxLayout(self.ratings_widget)

        self.ratings_summary = QLabel("Team attack/defense ratings from Poisson model.")
        self.ratings_summary.setWordWrap(True)
        layout.addWidget(self.ratings_summary)

        self.ratings_table = QTableWidget()
        cols = [
            "Team", "Rating", "Home Atk", "Home Def", "Away Atk", "Away Def",
            "Overall Atk", "Overall Def", "Home GP", "Away GP",
        ]
        self.ratings_table.setColumnCount(len(cols))
        self.ratings_table.setHorizontalHeaderLabels(cols)
        self.ratings_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.ratings_table.setAlternatingRowColors(True)
        self.ratings_table.setSortingEnabled(True)
        self.ratings_table.verticalHeader().setVisible(False)
        layout.addWidget(self.ratings_table)

    # ── Bankroll sub-tab ──────────────────────────────────────────────

    def _init_bankroll_tab(self):
        self.bankroll_widget = QWidget()
        layout = QVBoxLayout(self.bankroll_widget)

        # Bankroll stats cards
        cards_layout = QHBoxLayout()

        self.br_balance_label = self._make_stat_card("Balance", "£1,000.00")
        self.br_profit_label = self._make_stat_card("Profit", "£0.00")
        self.br_roi_label = self._make_stat_card("ROI", "0.0%")
        self.br_winrate_label = self._make_stat_card("Win Rate", "0.0%")
        self.br_drawdown_label = self._make_stat_card("Max DD", "0.0%")
        self.br_bets_label = self._make_stat_card("Total Bets", "0")

        cards_layout.addWidget(self.br_balance_label)
        cards_layout.addWidget(self.br_profit_label)
        cards_layout.addWidget(self.br_roi_label)
        cards_layout.addWidget(self.br_winrate_label)
        cards_layout.addWidget(self.br_drawdown_label)
        cards_layout.addWidget(self.br_bets_label)

        layout.addLayout(cards_layout)

        # Reset button
        reset_layout = QHBoxLayout()
        reset_layout.addStretch()
        self.reset_btn = QPushButton("Reset Bankroll")
        self.reset_btn.setProperty("danger", True)
        self.reset_btn.clicked.connect(self._on_reset_bankroll)
        reset_layout.addWidget(self.reset_btn)
        layout.addLayout(reset_layout)

        # Bet history table
        hist_group = QGroupBox("Bet History")
        hist_layout = QVBoxLayout(hist_group)
        self.history_table = QTableWidget()
        cols = [
            "Date", "Match", "Market", "Selection", "Odds",
            "Stake", "Edge %", "Won", "Profit", "Balance",
        ]
        self.history_table.setColumnCount(len(cols))
        self.history_table.setHorizontalHeaderLabels(cols)
        self.history_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setSortingEnabled(True)
        self.history_table.verticalHeader().setVisible(False)
        hist_layout.addWidget(self.history_table)
        layout.addWidget(hist_group)

    # ── Backtest sub-tab ──────────────────────────────────────────────

    def _init_backtest_tab(self):
        self.bt_widget = QWidget()
        layout = QVBoxLayout(self.bt_widget)

        self.bt_summary = QLabel("Run a backtest to see how the value strategy performs on historical data.")
        self.bt_summary.setWordWrap(True)
        self.bt_summary.setProperty("heading", True)
        layout.addWidget(self.bt_summary)

        # Backtest stats cards
        cards_layout = QHBoxLayout()
        self.bt_profit_label = self._make_stat_card("Profit", "-")
        self.bt_roi_label = self._make_stat_card("ROI", "-")
        self.bt_winrate_label = self._make_stat_card("Win Rate", "-")
        self.bt_bets_label = self._make_stat_card("Bets", "-")
        self.bt_dd_label = self._make_stat_card("Max DD", "-")
        self.bt_final_label = self._make_stat_card("Final", "-")

        cards_layout.addWidget(self.bt_profit_label)
        cards_layout.addWidget(self.bt_roi_label)
        cards_layout.addWidget(self.bt_winrate_label)
        cards_layout.addWidget(self.bt_bets_label)
        cards_layout.addWidget(self.bt_dd_label)
        cards_layout.addWidget(self.bt_final_label)
        layout.addLayout(cards_layout)

        # Backtest log table
        self.bt_table = QTableWidget()
        cols = [
            "Match", "Selection", "Odds", "Stake", "Edge %",
            "Model %", "Won", "Profit", "Balance",
        ]
        self.bt_table.setColumnCount(len(cols))
        self.bt_table.setHorizontalHeaderLabels(cols)
        self.bt_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.bt_table.setAlternatingRowColors(True)
        self.bt_table.setSortingEnabled(True)
        self.bt_table.verticalHeader().setVisible(False)
        layout.addWidget(self.bt_table)

    # ── Helpers ────────────────────────────────────────────────────────

    def _make_stat_card(self, title: str, value: str) -> QGroupBox:
        """Create a small stat card widget."""
        card = QGroupBox(title)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 4, 8, 4)
        label = QLabel(value)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = label.font()
        font.setPointSize(14)
        font.setBold(True)
        label.setFont(font)
        label.setObjectName("stat_value")
        card_layout.addWidget(label)
        return card

    def _update_stat_card(self, card: QGroupBox, value: str, color: str = ""):
        """Update a stat card's value."""
        label = card.findChild(QLabel, "stat_value")
        if label:
            label.setText(value)
            if color:
                label.setStyleSheet(f"color: {color}; background-color: transparent;")
            else:
                label.setStyleSheet("background-color: transparent;")

    def refresh_leagues(self):
        current = self.league_combo.currentText()
        self.league_combo.clear()
        for code, name in get_available_leagues():
            self.league_combo.addItem(name, code)
        idx = self.league_combo.findText(current)
        if idx >= 0:
            self.league_combo.setCurrentIndex(idx)

    # ── Actions ────────────────────────────────────────────────────────

    def _get_config(self) -> tuple:
        """Build bankroll and Poisson configs from UI."""
        bankroll_cfg = BankrollConfig(
            starting_balance=self.bankroll_spin.value(),
            current_balance=self.bankroll_spin.value(),
            min_edge=self.min_edge_spin.value() / 100.0,
            kelly_fraction=self.kelly_spin.value() / 100.0,
        )
        poisson_cfg = PoissonConfig()
        return bankroll_cfg, poisson_cfg

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
        bankroll_cfg, poisson_cfg = self._get_config()

        self.run_btn.setEnabled(False)
        self.backtest_btn.setEnabled(False)
        self.main_window.set_status("Running Poisson model analysis...")

        self._worker = _ValueWorker(
            results_df, fixtures_df, bankroll_cfg, poisson_cfg, run_backtest=False
        )
        self._worker.finished.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_backtest(self):
        code = self.league_combo.currentData()
        if not code:
            self.main_window.set_status("No league selected")
            return

        data = load_league_data(code)
        if data is None:
            self.main_window.set_status("No data available")
            return

        results_df, fixtures_df, table_df = data
        bankroll_cfg, poisson_cfg = self._get_config()

        self.run_btn.setEnabled(False)
        self.backtest_btn.setEnabled(False)
        self.main_window.set_status("Running value backtest...")

        self._worker = _ValueWorker(
            results_df, fixtures_df, bankroll_cfg, poisson_cfg, run_backtest=True
        )
        self._worker.finished.connect(self._on_results)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_error(self, msg: str):
        self.run_btn.setEnabled(True)
        self.backtest_btn.setEnabled(True)
        self.main_window.set_status(f"Error: {msg}")

    def _on_results(self, value_bets: list, backtest: dict, ratings: list):
        self.run_btn.setEnabled(True)
        self.backtest_btn.setEnabled(True)

        # Display value bets
        self._display_value_bets(value_bets)

        # Display team ratings
        self._display_ratings(ratings)

        # Display backtest if present
        if backtest:
            self._display_backtest(backtest)
            self.sub_tabs.setCurrentIndex(4)  # Switch to backtest tab
        elif value_bets:
            self.sub_tabs.setCurrentIndex(0)  # Switch to value bets tab
        else:
            self.sub_tabs.setCurrentIndex(1)  # Show probabilities

        # Update bankroll display
        self._refresh_bankroll()

        n_bets = len(value_bets)
        total_ev = sum(b["expected_value"] for b in value_bets)
        self.main_window.set_status(
            f"Found {n_bets} value bets  |  Total EV: £{total_ev:.2f}"
        )

    def _display_value_bets(self, bets: list):
        """Populate the value bets table."""
        self.vb_table.setSortingEnabled(False)
        self.vb_table.setRowCount(len(bets))

        total_stake = 0
        total_ev = 0

        for row, b in enumerate(bets):
            match_text = f"{b['home_team']} vs {b['away_team']}"
            self.vb_table.setItem(row, 0, QTableWidgetItem(match_text))
            self.vb_table.setItem(row, 1, QTableWidgetItem(b["market"]))
            self.vb_table.setItem(row, 2, QTableWidgetItem(b["selection"]))

            # Model probability
            mp_item = QTableWidgetItem(f"{b['model_prob']:.1f}%")
            mp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vb_table.setItem(row, 3, mp_item)

            # Implied probability
            ip_item = QTableWidgetItem(f"{b['implied_prob']:.1f}%")
            ip_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vb_table.setItem(row, 4, ip_item)

            # Edge — color code
            edge_item = QTableWidgetItem(f"{b['edge']:.1f}%")
            edge_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if b["edge"] >= 10:
                edge_item.setForeground(QColor("#22c55e"))  # Green for strong edge
            elif b["edge"] >= 5:
                edge_item.setForeground(QColor("#fbbf24"))  # Gold for decent edge
            else:
                edge_item.setForeground(QColor("#a6adc8"))
            self.vb_table.setItem(row, 5, edge_item)

            # Best odds
            odds_item = QTableWidgetItem(f"{b['best_odds']:.2f}")
            odds_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vb_table.setItem(row, 6, odds_item)

            # Kelly stake
            stake_item = QTableWidgetItem(f"£{b['kelly_stake']:.2f}")
            stake_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vb_table.setItem(row, 7, stake_item)
            total_stake += b["kelly_stake"]

            # Expected value
            ev_item = QTableWidgetItem(f"£{b['expected_value']:.2f}")
            ev_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if b["expected_value"] > 0:
                ev_item.setForeground(QColor("#22c55e"))
            self.vb_table.setItem(row, 8, ev_item)
            total_ev += b["expected_value"]

            # xG
            xg_text = f"{b['home_xg']:.1f} - {b['away_xg']:.1f}"
            xg_item = QTableWidgetItem(xg_text)
            xg_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.vb_table.setItem(row, 9, xg_item)

            # Row color based on market
            if b["selection"] == "Home Win":
                bg = QColor("#1a3a2a")
            elif b["selection"] == "Away Win":
                bg = QColor("#1a2a3a")
            elif b["selection"] == "Draw":
                bg = QColor("#3a3a1a")
            else:
                bg = QColor("#2a2a2a")

            for col in range(self.vb_table.columnCount()):
                item = self.vb_table.item(row, col)
                if item:
                    item.setBackground(bg)

        self.vb_table.setSortingEnabled(True)

        if bets:
            avg_edge = sum(b["edge"] for b in bets) / len(bets)
            self.vb_summary.setText(
                f"Found {len(bets)} value bets  |  "
                f"Avg edge: {avg_edge:.1f}%  |  "
                f"Total stake: £{total_stake:.2f}  |  "
                f"Total EV: £{total_ev:.2f}"
            )
        else:
            self.vb_summary.setText(
                "No value bets found. This can mean:\n"
                "- No fixtures with odds available\n"
                "- No edge over bookmaker prices (try lowering min edge %)\n"
                "- Not enough match data for Poisson model"
            )

        # Also populate the probabilities tab from the same run
        self._display_probabilities_from_bets(bets)

    def _display_probabilities_from_bets(self, bets: list):
        """Populate match probabilities from value bet analysis."""
        # Deduplicate by match
        seen = set()
        matches = []
        for b in bets:
            key = f"{b['home_team']}_{b['away_team']}"
            if key not in seen:
                seen.add(key)
                matches.append(b)

        # If we have predictions from the model, also show non-value matches
        # For now, show what we have from value analysis
        self.prob_table.setSortingEnabled(False)
        self.prob_table.setRowCount(len(matches))

        for row, m in enumerate(matches):
            match_text = f"{m['home_team']} vs {m['away_team']}"
            self.prob_table.setItem(row, 0, QTableWidgetItem(match_text))

            items = [
                (1, f"{m['home_xg']:.2f}"),
                (2, f"{m['away_xg']:.2f}"),
            ]
            for col, text in items:
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.prob_table.setItem(row, col, item)

        self.prob_table.setSortingEnabled(True)

        if matches:
            self.prob_summary.setText(
                f"Poisson model probabilities for {len(matches)} matches"
            )

    def _display_ratings(self, ratings: list):
        """Populate team ratings table."""
        self.ratings_table.setSortingEnabled(False)
        self.ratings_table.setRowCount(len(ratings))

        for row, r in enumerate(ratings):
            self.ratings_table.setItem(row, 0, QTableWidgetItem(r["team"]))

            # Rating — color code
            rating_item = QTableWidgetItem(f"{r['rating']:.2f}")
            rating_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if r["rating"] >= 1.5:
                rating_item.setForeground(QColor("#22c55e"))
            elif r["rating"] >= 1.0:
                rating_item.setForeground(QColor("#fbbf24"))
            else:
                rating_item.setForeground(QColor("#ef4444"))
            self.ratings_table.setItem(row, 1, rating_item)

            stats = [
                (2, r["home_attack"]),
                (3, r["home_defense"]),
                (4, r["away_attack"]),
                (5, r["away_defense"]),
                (6, r["overall_attack"]),
                (7, r["overall_defense"]),
                (8, r["home_matches"]),
                (9, r["away_matches"]),
            ]
            for col, val in stats:
                item = QTableWidgetItem(f"{val:.3f}" if isinstance(val, float) else str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                # Color code attack (green = high) and defense (red = high = bad)
                if col in (2, 4, 6) and isinstance(val, float):
                    if val >= 1.3:
                        item.setForeground(QColor("#22c55e"))
                    elif val <= 0.7:
                        item.setForeground(QColor("#ef4444"))
                elif col in (3, 5, 7) and isinstance(val, float):
                    if val <= 0.8:
                        item.setForeground(QColor("#22c55e"))  # Low defense = good
                    elif val >= 1.3:
                        item.setForeground(QColor("#ef4444"))  # High defense = bad

                self.ratings_table.setItem(row, col, item)

        self.ratings_table.setSortingEnabled(True)
        self.ratings_summary.setText(
            f"Team ratings for {len(ratings)} teams  |  "
            f"Rating = Attack / Defense (higher = better)  |  "
            f"Values > 1.0 = above league average"
        )

    def _display_backtest(self, bt: dict):
        """Display backtest results."""
        # Update summary cards
        profit = bt.get("total_profit", 0)
        profit_color = "#22c55e" if profit >= 0 else "#ef4444"
        self._update_stat_card(self.bt_profit_label, f"£{profit:.2f}", profit_color)

        roi = bt.get("roi", 0)
        roi_color = "#22c55e" if roi >= 0 else "#ef4444"
        self._update_stat_card(self.bt_roi_label, f"{roi:.1f}%", roi_color)

        self._update_stat_card(
            self.bt_winrate_label,
            f"{bt.get('win_rate', 0):.1f}%",
        )
        self._update_stat_card(self.bt_bets_label, str(bt.get("total_bets", 0)))
        self._update_stat_card(
            self.bt_dd_label,
            f"{bt.get('max_drawdown', 0):.1f}%",
            "#ef4444" if bt.get("max_drawdown", 0) > 20 else "",
        )
        self._update_stat_card(
            self.bt_final_label,
            f"£{bt.get('final_balance', 0):.2f}",
            profit_color,
        )

        self.bt_summary.setText(
            f"Backtest: {bt.get('train_matches', 0)} training matches, "
            f"{bt.get('test_matches', 0)} test matches  |  "
            f"{bt.get('total_bets', 0)} bets placed  |  "
            f"ROI: {roi:.1f}%"
        )

        # Populate log table
        log = bt.get("bets_log", [])
        self.bt_table.setSortingEnabled(False)
        self.bt_table.setRowCount(len(log))

        for row, entry in enumerate(log):
            self.bt_table.setItem(row, 0, QTableWidgetItem(entry["match"]))
            self.bt_table.setItem(row, 1, QTableWidgetItem(entry["selection"]))

            items_data = [
                (2, f"{entry['odds']:.2f}"),
                (3, f"£{entry['stake']:.2f}"),
                (4, f"{entry['edge']:.1f}%"),
                (5, f"{entry['model_prob']:.1f}%"),
                (6, "YES" if entry["won"] else "NO"),
                (7, f"£{entry['profit']:.2f}"),
                (8, f"£{entry['balance']:.2f}"),
            ]

            for col, text in items_data:
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

                if col == 6:
                    item.setForeground(
                        QColor("#22c55e") if entry["won"] else QColor("#ef4444")
                    )
                elif col == 7:
                    item.setForeground(
                        QColor("#22c55e") if entry["profit"] > 0 else QColor("#ef4444")
                    )

                self.bt_table.setItem(row, col, item)

            # Row background
            bg = QColor("#1a3a2a") if entry["won"] else QColor("#3a1a1a")
            for col in range(self.bt_table.columnCount()):
                item = self.bt_table.item(row, col)
                if item:
                    item.setBackground(bg)

        self.bt_table.setSortingEnabled(True)

    def _refresh_bankroll(self):
        """Update bankroll display from saved state."""
        engine = ValueEngine()
        summary = engine.get_bankroll_summary()

        balance = summary["current_balance"]
        profit = summary["total_profit"]
        profit_color = "#22c55e" if profit >= 0 else "#ef4444"

        self._update_stat_card(self.br_balance_label, f"£{balance:.2f}")
        self._update_stat_card(self.br_profit_label, f"£{profit:.2f}", profit_color)
        self._update_stat_card(
            self.br_roi_label,
            f"{summary['roi']:.1f}%",
            "#22c55e" if summary["roi"] >= 0 else "#ef4444",
        )
        self._update_stat_card(self.br_winrate_label, f"{summary['win_rate']:.1f}%")
        self._update_stat_card(
            self.br_drawdown_label,
            f"{summary['max_drawdown']:.1f}%",
            "#ef4444" if summary["max_drawdown"] > 20 else "",
        )
        self._update_stat_card(self.br_bets_label, str(summary["total_bets"]))

        # Populate history
        history = engine.get_bet_history()
        self.history_table.setSortingEnabled(False)
        self.history_table.setRowCount(len(history))

        for row, b in enumerate(history):
            self.history_table.setItem(row, 0, QTableWidgetItem(b.get("date", "")))
            self.history_table.setItem(row, 1, QTableWidgetItem(b.get("match", "")))
            self.history_table.setItem(row, 2, QTableWidgetItem(b.get("market", "")))
            self.history_table.setItem(row, 3, QTableWidgetItem(b.get("selection", "")))

            items_data = [
                (4, f"{b.get('odds', 0):.2f}"),
                (5, f"£{b.get('stake', 0):.2f}"),
                (6, f"{b.get('edge', 0):.1f}%"),
                (7, "YES" if b.get("won") else "NO"),
                (8, f"£{b.get('profit', 0):.2f}"),
                (9, f"£{b.get('balance', 0):.2f}"),
            ]

            for col, text in items_data:
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 7:
                    item.setForeground(
                        QColor("#22c55e") if b.get("won") else QColor("#ef4444")
                    )
                elif col == 8:
                    item.setForeground(
                        QColor("#22c55e") if b.get("profit", 0) > 0 else QColor("#ef4444")
                    )
                self.history_table.setItem(row, col, item)

        self.history_table.setSortingEnabled(True)

    def _on_reset_bankroll(self):
        """Reset bankroll to starting balance."""
        engine = ValueEngine()
        engine.reset_bankroll(self.bankroll_spin.value())
        self._refresh_bankroll()
        self.main_window.set_status("Bankroll reset")
