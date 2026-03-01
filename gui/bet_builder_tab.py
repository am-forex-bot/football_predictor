"""Bet Builder tab — model probabilities, real Bet365 odds, edge, and auto combo suggestions.

Displays all markets from the Poisson goal matrix + historical stats.
Where Bet365 odds are available (1X2, O/U 2.5, BTTS), shows real odds and edge.
Auto Builder scans all markets meeting a minimum probability threshold and
suggests ready-made bet builder combos with combined odds.
"""

import pandas as pd
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QSpinBox, QScrollArea, QFrame,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from core.data_manager import get_available_leagues, load_league_data
from core.poisson_model import PoissonModel, PoissonConfig
from core.stats_model import StatsModel


# ── Mapping: probability key → Bet365 odds key in prediction dict ──
_B365_MAP = {
    "p_home": "b365_home",
    "p_draw": "b365_draw",
    "p_away": "b365_away",
    "p_over_25": "over_25_odds",
    "p_under_25": "under_25_odds",
    "p_btts_yes": "btts_yes_odds",
    "p_btts_no": "btts_no_odds",
}

# ── Market definitions for auto builder ──
# (display_name_template, prob_key, conflict_group, category)
_MARKET_DEFS = [
    ("Home Win", "p_home", "result", "1X2"),
    ("Draw", "p_draw", "result", "1X2"),
    ("Away Win", "p_away", "result", "1X2"),
    ("Over 1.5 Goals", "p_over_15", "goals_15", "Goals"),
    ("Under 1.5 Goals", "p_under_15", "goals_15", "Goals"),
    ("Over 2.5 Goals", "p_over_25", "goals_25", "Goals"),
    ("Under 2.5 Goals", "p_under_25", "goals_25", "Goals"),
    ("Over 3.5 Goals", "p_over_35", "goals_35", "Goals"),
    ("Under 3.5 Goals", "p_under_35", "goals_35", "Goals"),
    ("Over 4.5 Goals", "p_over_45", "goals_45", "Goals"),
    ("Under 4.5 Goals", "p_under_45", "goals_45", "Goals"),
    ("BTTS Yes", "p_btts_yes", "btts", "BTTS"),
    ("BTTS No", "p_btts_no", "btts", "BTTS"),
    ("BTTS + {home} Win", "p_btts_home", "btts_result", "Combo"),
    ("BTTS + Draw", "p_btts_draw", "btts_result", "Combo"),
    ("BTTS + {away} Win", "p_btts_away", "btts_result", "Combo"),
    ("{home} Win + Over 2.5", "p_home_o25", "result_ou", "Combo"),
    ("{away} Win + Over 2.5", "p_away_o25", "result_ou", "Combo"),
    ("{home} Win + Under 2.5", "p_home_u25", "result_ou2", "Combo"),
    ("BTTS + Over 2.5", "p_btts_o25", "btts_ou", "Combo"),
    ("BTTS + Under 2.5", "p_btts_u25", "btts_ou", "Combo"),
    ("{home} Over 0.5 Goals", "p_home_over_05", "home_05", "Team Goals"),
    ("{home} Over 1.5 Goals", "p_home_over_15", "home_15", "Team Goals"),
    ("{away} Over 0.5 Goals", "p_away_over_05", "away_05", "Team Goals"),
    ("{away} Over 1.5 Goals", "p_away_over_15", "away_15", "Team Goals"),
    ("{home} Under 2.5 Goals", "p_home_under_25", "home_25", "Team Goals"),
    ("{away} Under 2.5 Goals", "p_away_under_25", "away_25", "Team Goals"),
]


def _fair_odds(prob: float) -> str:
    if prob <= 0.001:
        return "—"
    return f"{1.0 / prob:.2f}"


def _fair_odds_num(prob: float) -> float:
    if prob <= 0.001:
        return 999.0
    return 1.0 / prob


def _pct(prob: float) -> str:
    return f"{prob * 100:.1f}%"


def _edge(prob: float, odds: float) -> float:
    """Calculate EV edge: (prob * odds - 1) * 100."""
    return (prob * odds - 1.0) * 100.0


def _build_picks(pred: dict, min_prob: float) -> list[dict]:
    """Build list of all selections meeting min_prob threshold."""
    home = pred["home_team"]
    away = pred["away_team"]
    picks = []

    for name_tpl, prob_key, conflict, category in _MARKET_DEFS:
        prob = pred.get(prob_key, 0)
        if prob < min_prob:
            continue

        name = name_tpl.format(home=home, away=away)
        fair = _fair_odds_num(prob)
        b365_key = _B365_MAP.get(prob_key)
        b365 = pred.get(b365_key) if b365_key else None
        ev = _edge(prob, b365) if b365 else None

        # Score: strongly prefer verified value (real odds with +edge)
        if ev is not None and ev > 0:
            score = prob * ev
        elif ev is not None:
            score = prob * 0.3  # has odds but negative edge
        else:
            score = prob * 0.5  # no real odds to verify

        picks.append({
            "name": name,
            "prob": prob,
            "fair_odds": fair,
            "b365": b365,
            "edge": ev,
            "conflict": conflict,
            "category": category,
            "score": score,
        })

    # Stats markets (corners, shots, etc.)
    stats = pred.get("_stats")
    if stats:
        for key in ("corners", "shots", "sot", "yellows"):
            info = stats.get(key)
            if not info:
                continue
            label = info["label"]
            for line_key, prob in info["lines"].items():
                if prob < min_prob:
                    continue
                direction, val = line_key.split("_", 1)
                picks.append({
                    "name": f"{label} {direction.title()} {val}",
                    "prob": prob,
                    "fair_odds": _fair_odds_num(prob),
                    "b365": None,
                    "edge": None,
                    "conflict": f"stat_{key}_{val}",
                    "category": "Stats",
                    "score": prob * 0.5,
                })

    return picks


def _generate_combos(picks: list[dict], n_legs: int,
                     n_combos: int = 3) -> list[list[dict]]:
    """Generate combo suggestions avoiding conflicting selections.

    Prefers diverse categories and verified value picks.
    """
    if len(picks) < n_legs:
        return []

    scored = sorted(picks, key=lambda p: p["score"], reverse=True)
    combos = []
    used_keys: set[frozenset[str]] = set()

    for start_idx in range(len(scored)):
        anchor = scored[start_idx]
        combo = [anchor]
        used_conflicts = {anchor["conflict"]}
        used_cats = {anchor["category"]}

        # Sort remaining: prefer different category, then by score
        remaining = [p for p in scored if p is not anchor]
        remaining.sort(
            key=lambda p: (10 if p["category"] not in used_cats else 0)
                          + p["score"],
            reverse=True,
        )

        for pick in remaining:
            if pick["conflict"] in used_conflicts:
                continue
            combo.append(pick)
            used_conflicts.add(pick["conflict"])
            used_cats.add(pick["category"])
            if len(combo) >= n_legs:
                break

        if len(combo) >= n_legs:
            key = frozenset(p["name"] for p in combo)
            if key not in used_keys:
                used_keys.add(key)
                combos.append(combo)
                if len(combos) >= n_combos:
                    break

    return combos


def _combo_html(combos: list[list[dict]], match_label: str) -> str:
    """Build HTML for the suggested combos panel."""
    if not combos:
        return (
            "<p style='color: #94a3b8; font-size: 12px; padding: 6px;'>"
            "No combos found at this threshold. Try lowering Min Prob %.</p>"
        )

    parts = []
    for i, combo in enumerate(combos, 1):
        combined_prob = 1.0
        combined_b365 = 1.0
        all_have_odds = True
        for pick in combo:
            combined_prob *= pick["prob"]
            if pick["b365"]:
                combined_b365 *= pick["b365"]
            else:
                all_have_odds = False
                combined_b365 *= pick["fair_odds"]

        combined_fair = _fair_odds_num(combined_prob)

        # Header
        hdr = (f"<b style='color: #fbbf24; font-size: 13px;'>"
               f"COMBO {i}</b>"
               f"&nbsp;&nbsp;Prob: <b>{combined_prob * 100:.1f}%</b>"
               f"&nbsp;&nbsp;Fair Odds: <b>{combined_fair:.2f}</b>")
        if all_have_odds:
            comb_ev = _edge(combined_prob, combined_b365)
            ev_color = "#4ade80" if comb_ev > 0 else "#f87171"
            hdr += (f"&nbsp;&nbsp;B365 Combined: <b>{combined_b365:.2f}</b>"
                    f"&nbsp;&nbsp;<span style='color:{ev_color}'>"
                    f"Edge: {'+' if comb_ev > 0 else ''}{comb_ev:.1f}%</span>")

        # Legs
        rows = []
        for pick in combo:
            prob_str = f"{pick['prob'] * 100:.1f}%"
            fair_str = f"Fair: {pick['fair_odds']:.2f}"

            if pick["b365"]:
                ev = pick["edge"]
                ev_sign = "+" if ev > 0 else ""
                ev_color = "#4ade80" if ev > 0 else "#f87171"
                odds_str = (
                    f"<span style='color: #60a5fa;'>"
                    f"B365: <b>{pick['b365']:.2f}</b></span>"
                    f"&nbsp;&nbsp;"
                    f"<span style='color: {ev_color};'>"
                    f"{ev_sign}{ev:.1f}%</span>"
                )
            else:
                odds_str = "<span style='color: #64748b;'>check B365</span>"

            rows.append(
                f"<tr>"
                f"<td style='padding: 1px 6px; color: #4ade80;'>&#9679;</td>"
                f"<td style='padding: 1px 6px; min-width: 180px;'>"
                f"<b>{pick['name']}</b></td>"
                f"<td style='padding: 1px 8px;'>{prob_str}</td>"
                f"<td style='padding: 1px 8px; color: #94a3b8;'>{fair_str}</td>"
                f"<td style='padding: 1px 8px;'>{odds_str}</td>"
                f"</tr>"
            )

        parts.append(
            f"<div style='margin-bottom: 8px; padding: 6px 8px; "
            f"border-left: 3px solid #fbbf24; "
            f"background: rgba(251, 191, 36, 0.06);'>"
            f"<p style='margin: 0 0 4px 0;'>{hdr}</p>"
            f"<table style='font-size: 11px;'>{''.join(rows)}</table>"
            f"</div>"
        )

    return "".join(parts)


class _BetBuilderWorker(QThread):
    """Run model predictions in background thread."""
    finished = pyqtSignal(list, object)
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
            "Model probabilities + fair odds for every market.  "
            "Where B365 odds are available, <b>Edge %</b> is shown "
            "(<span style='color:#4ade80'>green = value</span>).  "
            "Auto Builder suggests high-confidence combos you can place directly."
        )
        guide.setWordWrap(True)
        guide.setStyleSheet(
            "padding: 6px 10px; border-radius: 4px; "
            "background-color: rgba(59, 130, 246, 0.12); "
            "color: #93c5fd; font-size: 11px;"
        )
        layout.addWidget(guide)

        # Config bar — row 1: league + match + build
        config = QGroupBox("Configuration")
        config_outer = QVBoxLayout(config)
        config_outer.setSpacing(4)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("League:"))
        self.league_combo = QComboBox()
        self.league_combo.setMinimumWidth(180)
        row1.addWidget(self.league_combo)

        row1.addWidget(QLabel("  Match:"))
        self.match_combo = QComboBox()
        self.match_combo.setMinimumWidth(280)
        self.match_combo.currentIndexChanged.connect(self._on_match_changed)
        row1.addWidget(self.match_combo)

        row1.addStretch()

        self.run_btn = QPushButton("Build Markets")
        self.run_btn.setMinimumWidth(130)
        self.run_btn.clicked.connect(self._on_run)
        row1.addWidget(self.run_btn)
        config_outer.addLayout(row1)

        # Config bar — row 2: auto builder settings
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Auto Builder:"))

        row2.addWidget(QLabel("  Min Prob %:"))
        self.min_prob_spin = QSpinBox()
        self.min_prob_spin.setRange(50, 90)
        self.min_prob_spin.setValue(65)
        self.min_prob_spin.setSuffix("%")
        self.min_prob_spin.setToolTip(
            "Each leg must have at least this model probability"
        )
        self.min_prob_spin.valueChanged.connect(self._refresh_display)
        row2.addWidget(self.min_prob_spin)

        row2.addWidget(QLabel("  Legs:"))
        self.legs_spin = QSpinBox()
        self.legs_spin.setRange(2, 6)
        self.legs_spin.setValue(3)
        self.legs_spin.setToolTip("Number of selections per combo")
        self.legs_spin.valueChanged.connect(self._refresh_display)
        row2.addWidget(self.legs_spin)

        row2.addStretch()
        config_outer.addLayout(row2)

        layout.addWidget(config)

        # Main splitter: suggestions + (summary + table)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Suggestions panel (scrollable)
        self.suggestions_label = QLabel(
            "<p style='color: #94a3b8; font-size: 12px; padding: 6px;'>"
            "Select a league and click Build Markets to see auto combos.</p>"
        )
        self.suggestions_label.setWordWrap(True)
        self.suggestions_label.setTextFormat(Qt.TextFormat.RichText)
        self.suggestions_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.suggestions_label.setStyleSheet(
            "background-color: rgba(255,255,255,0.03); "
            "border-radius: 4px; padding: 4px;"
        )

        scroll = QScrollArea()
        scroll.setWidget(self.suggestions_label)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(220)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        splitter.addWidget(scroll)

        # Match summary
        self.summary_label = QLabel("Select a league and click Build Markets")
        self.summary_label.setStyleSheet(
            "padding: 8px; font-size: 13px; "
            "background-color: rgba(255,255,255,0.05); border-radius: 4px;"
        )
        self.summary_label.setWordWrap(True)
        splitter.addWidget(self.summary_label)

        # Market table — 6 columns for compact horizontal layout
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Category", "Selection", "", "", "", "",
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        for c in range(2, 6):
            self.table.horizontalHeader().setSectionResizeMode(
                c, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        splitter.addWidget(self.table)

        splitter.setStretchFactor(0, 0)  # suggestions — compact
        splitter.setStretchFactor(1, 0)  # summary — compact
        splitter.setStretchFactor(2, 1)  # table — fill
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

        if fixtures_df is None or fixtures_df.empty:
            teams = sorted(
                set(results_df["Team"].unique())
                | set(results_df["Opponent"].unique())
            )
            if len(teams) >= 2:
                rows = []
                for i, home in enumerate(teams):
                    away = teams[(i + 1) % len(teams)]
                    rows.append({"Team": home, "Opponent": away})
                fixtures_df = pd.DataFrame(rows)
                self.main_window.set_status(
                    f"No fixtures in workbook — generated {len(rows)} "
                    f"matchups from {len(teams)} teams"
                )
            else:
                self.main_window.set_status(
                    "No fixtures found. Download a league first."
                )
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

        self.match_combo.blockSignals(True)
        self.match_combo.clear()
        for i, p in enumerate(predictions):
            label = f"{p['home_team']}  vs  {p['away_team']}"
            self.match_combo.addItem(label, i)
        self.match_combo.blockSignals(False)

        n = len(predictions)
        n_odds = sum(
            1 for p in predictions if p.get("b365_home")
        )
        status = f"{n} fixtures predicted"
        if n_odds > 0:
            status += f" | {n_odds} with Bet365 odds"
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

    def _refresh_display(self):
        """Re-render current match when spinner values change."""
        idx = self.match_combo.currentIndex()
        if 0 <= idx < len(self._predictions):
            self._display_match(self._predictions[idx])

    # ── Cell formatting helper ──

    def _cell_text(self, label: str, prob: float, pred: dict,
                   prob_key: str | None = None) -> str:
        """Build cell text, appending B365 odds + edge when available."""
        base = f"{label}:  {_pct(prob)}  ({_fair_odds(prob)})" if label else \
               f"{_pct(prob)}  ({_fair_odds(prob)})"

        if prob_key and prob_key in _B365_MAP:
            b365 = pred.get(_B365_MAP[prob_key])
            if b365 and b365 > 0:
                ev = _edge(prob, b365)
                sign = "+" if ev > 0 else ""
                base += f"  B365:{b365:.2f} {sign}{ev:.1f}%"

        return base

    def _cell_color(self, prob: float, pred: dict,
                    prob_key: str | None = None) -> QColor:
        """Color: use edge color if B365 odds exist, else probability color."""
        if prob_key and prob_key in _B365_MAP:
            b365 = pred.get(_B365_MAP[prob_key])
            if b365 and b365 > 0:
                ev = _edge(prob, b365)
                if ev > 5:
                    return QColor("#4ade80")  # strong value
                elif ev > 0:
                    return QColor("#86efac")  # mild value
                else:
                    return QColor("#f87171")  # negative edge

        # Fallback: color by probability
        if prob >= 0.6:
            return QColor("#4ade80")
        if prob >= 0.4:
            return QColor("#fbbf24")
        if prob >= 0.2:
            return QColor("#f97316")
        return QColor("#94a3b8")

    # ── Main display ──

    def _display_match(self, pred):
        home = pred["home_team"]
        away = pred["away_team"]

        # ── Auto Builder suggestions ──
        min_prob = self.min_prob_spin.value() / 100.0
        n_legs = self.legs_spin.value()
        picks = _build_picks(pred, min_prob)
        combos = _generate_combos(picks, n_legs, n_combos=3)
        label = f"{home} vs {away}"
        self.suggestions_label.setText(_combo_html(combos, label))

        # ── Summary line ──
        summary = (
            f"<b style='font-size:15px'>{home}  vs  {away}</b>"
            f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
            f"xG: <b>{pred['home_xg']}</b> — <b>{pred['away_xg']}</b>"
            f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
            f"1X2: {_pct(pred['p_home'])} / {_pct(pred['p_draw'])} "
            f"/ {_pct(pred['p_away'])}"
        )
        # Show B365 1X2 if available
        b365h = pred.get("b365_home")
        b365d = pred.get("b365_draw")
        b365a = pred.get("b365_away")
        if b365h:
            summary += (
                f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
                f"B365: {b365h:.2f} / {b365d:.2f} / {b365a:.2f}"
            )
        self.summary_label.setText(summary)

        # ── Build compact row data ──
        # Each entry: (category, selection, [(label, prob, prob_key), ...])
        groups: list[tuple[str, str, list[tuple[str, float, str | None]]]] = []

        # 1X2
        groups.append(("1X2", "Home Win",
                       [("", pred["p_home"], "p_home")]))
        groups.append(("1X2", "Draw",
                       [("", pred["p_draw"], "p_draw")]))
        groups.append(("1X2", "Away Win",
                       [("", pred["p_away"], "p_away")]))

        # Goal Lines
        groups.append(("Goals", "Over", [
            ("1.5", pred["p_over_15"], "p_over_15"),
            ("2.5", pred["p_over_25"], "p_over_25"),
            ("3.5", pred["p_over_35"], "p_over_35"),
            ("4.5", pred["p_over_45"], "p_over_45"),
        ]))
        groups.append(("Goals", "Under", [
            ("1.5", pred["p_under_15"], "p_under_15"),
            ("2.5", pred["p_under_25"], "p_under_25"),
            ("3.5", pred["p_under_35"], "p_under_35"),
            ("4.5", pred["p_under_45"], "p_under_45"),
        ]))

        # BTTS
        groups.append(("BTTS", "", [
            ("Yes", pred["p_btts_yes"], "p_btts_yes"),
            ("No", pred["p_btts_no"], "p_btts_no"),
        ]))

        # BTTS + Result
        groups.append(("BTTS + Result", "", [
            (f"{home}", pred["p_btts_home"], None),
            ("Draw", pred["p_btts_draw"], None),
            (f"{away}", pred["p_btts_away"], None),
        ]))

        # Result + O/U 2.5
        groups.append(("Result + O/U", "Over 2.5", [
            (f"{home}", pred["p_home_o25"], None),
            ("Draw", pred["p_draw_o25"], None),
            (f"{away}", pred["p_away_o25"], None),
        ]))
        groups.append(("Result + O/U", "Under 2.5", [
            (f"{home}", pred["p_home_u25"], None),
            ("Draw", pred["p_draw_u25"], None),
            (f"{away}", pred["p_away_u25"], None),
        ]))

        # BTTS + O/U 2.5
        groups.append(("BTTS + O/U", "", [
            ("BTTS & O2.5", pred["p_btts_o25"], None),
            ("BTTS & U2.5", pred["p_btts_u25"], None),
        ]))

        # Team Goals
        for label, prefix in [(home, "home"), (away, "away")]:
            groups.append((f"{label} Goals", "Over", [
                ("0.5", pred[f"p_{prefix}_over_05"], None),
                ("1.5", pred[f"p_{prefix}_over_15"], None),
                ("2.5", pred[f"p_{prefix}_over_25"], None),
            ]))
            groups.append((f"{label} Goals", "Under", [
                ("0.5", pred[f"p_{prefix}_under_05"], None),
                ("1.5", pred[f"p_{prefix}_under_15"], None),
                ("2.5", pred[f"p_{prefix}_under_25"], None),
            ]))

        # Correct Score
        cs = pred.get("correct_scores", {})
        cs_sorted = sorted(cs.items(), key=lambda x: x[1], reverse=True)[:12]
        for chunk_start in range(0, len(cs_sorted), 4):
            chunk = cs_sorted[chunk_start:chunk_start + 4]
            groups.append(("Correct Score", "", [
                (score, pct / 100.0, None) for score, pct in chunk
            ]))

        # Match Stats
        stats = pred.get("_stats")
        if stats:
            for key in ("corners", "shots", "sot", "yellows"):
                info = stats.get(key)
                if not info:
                    continue
                stat_label = info["label"]
                cat = f"{stat_label} ({info['total_expected']})"
                lines = info["lines"]
                overs = sorted(
                    [(k, v) for k, v in lines.items() if k.startswith("over_")],
                    key=lambda x: float(x[0].split("_")[1]),
                )
                unders = sorted(
                    [(k, v) for k, v in lines.items()
                     if k.startswith("under_")],
                    key=lambda x: float(x[0].split("_")[1]),
                )
                if overs:
                    groups.append((cat, "Over", [
                        (k.split("_")[1], v, None) for k, v in overs
                    ]))
                if unders:
                    groups.append((cat, "Under", [
                        (k.split("_")[1], v, None) for k, v in unders
                    ]))

        # ── Populate table ──
        self.table.setRowCount(len(groups))
        bold_font = QFont()
        bold_font.setBold(True)

        prev_cat = ""
        for row_idx, (cat, selection, values) in enumerate(groups):
            cat_item = QTableWidgetItem(cat if cat != prev_cat else "")
            if cat != prev_cat:
                cat_item.setFont(bold_font)
            cat_item.setTextAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row_idx, 0, cat_item)
            prev_cat = cat

            sel_item = QTableWidgetItem(selection)
            sel_item.setFont(bold_font)
            self.table.setItem(row_idx, 1, sel_item)

            for col_offset, (lbl, prob, pkey) in enumerate(values[:4]):
                text = self._cell_text(lbl, prob, pred, pkey)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setForeground(self._cell_color(prob, pred, pkey))
                self.table.setItem(row_idx, 2 + col_offset, item)

            for col_offset in range(len(values), 4):
                self.table.setItem(
                    row_idx, 2 + col_offset, QTableWidgetItem(""))

        self.table.resizeRowsToContents()
