"""Value betting engine — finds profitable bets using Poisson probabilities.

Core concepts:
- Edge = model probability - implied probability (from odds)
- Value bet = edge > minimum threshold (typically 3-5%)
- Kelly criterion = optimal stake sizing based on edge
- CLV (Closing Line Value) = comparing your bet odds to Pinnacle closing line
- Bankroll management = tracking balance, max stake, drawdown limits

This module brings together the Poisson model output with bookmaker odds
to identify +EV (positive expected value) betting opportunities.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.poisson_model import PoissonModel, PoissonConfig


# ───────────────────────────────────────────────────────────────────────
# Configuration
# ───────────────────────────────────────────────────────────────────────

@dataclass
class BankrollConfig:
    """Bankroll and staking configuration."""
    starting_balance: float = 1000.0    # Starting bankroll
    current_balance: float = 1000.0     # Current balance (updated as bets resolve)
    min_edge: float = 0.03             # Minimum edge to place bet (3%)
    kelly_fraction: float = 0.25       # Fraction of full Kelly (0.25 = quarter Kelly)
    max_stake_pct: float = 0.05        # Max stake as % of bankroll (5%)
    min_stake: float = 1.0             # Minimum bet size
    max_stake: float = 50.0            # Absolute maximum bet size
    min_odds: float = 1.20             # Minimum odds to consider
    max_odds: float = 15.0             # Maximum odds to consider
    drawdown_limit: float = 0.30       # Stop betting if drawdown exceeds 30%


BANKROLL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "bankroll.json"
)


def _load_bankroll() -> dict:
    """Load bankroll state from disk."""
    if os.path.exists(BANKROLL_FILE):
        with open(BANKROLL_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_bankroll(data: dict):
    """Save bankroll state to disk."""
    os.makedirs(os.path.dirname(BANKROLL_FILE), exist_ok=True)
    with open(BANKROLL_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ───────────────────────────────────────────────────────────────────────
# Odds utilities
# ───────────────────────────────────────────────────────────────────────

def odds_to_prob(odds: float) -> float:
    """Convert decimal odds to implied probability."""
    if odds <= 1.0:
        return 1.0
    return 1.0 / odds


def remove_overround(probs: List[float]) -> List[float]:
    """Remove bookmaker margin to get fair probabilities.

    Uses the multiplicative method: divide each prob by the sum.
    """
    total = sum(probs)
    if total <= 0:
        return probs
    return [p / total for p in probs]


def calculate_edge(model_prob: float, odds: float) -> float:
    """Calculate edge: model_prob - fair_implied_prob.

    Positive edge = model thinks outcome is more likely than odds imply.
    """
    implied = odds_to_prob(odds)
    return model_prob - implied


def kelly_stake(model_prob: float, odds: float,
                bankroll: float, fraction: float = 0.25,
                max_pct: float = 0.05) -> float:
    """Calculate Kelly criterion stake.

    f* = (bp - q) / b
    where b = decimal_odds - 1, p = model_prob, q = 1 - p

    Uses fractional Kelly to reduce variance.
    """
    b = odds - 1.0
    if b <= 0:
        return 0.0

    p = model_prob
    q = 1.0 - p

    full_kelly = (b * p - q) / b

    if full_kelly <= 0:
        return 0.0  # No edge, don't bet

    # Apply fraction and bankroll cap
    stake = full_kelly * fraction * bankroll
    max_stake = bankroll * max_pct
    return min(stake, max_stake)


def expected_value(model_prob: float, odds: float, stake: float = 1.0) -> float:
    """Calculate expected value of a bet.

    EV = (prob * profit) - ((1-prob) * stake)
    """
    profit = (odds - 1.0) * stake
    loss = stake
    return model_prob * profit - (1.0 - model_prob) * loss


# ───────────────────────────────────────────────────────────────────────
# CLV (Closing Line Value) tracking
# ───────────────────────────────────────────────────────────────────────

def closing_line_value(bet_odds: float, closing_odds: float) -> float:
    """Calculate CLV as percentage.

    CLV = (closing_implied - bet_implied) / bet_implied * 100

    Positive CLV means you got a better price than the closing line.
    Pinnacle closing odds are the gold standard for fair price.
    """
    bet_prob = odds_to_prob(bet_odds)
    close_prob = odds_to_prob(closing_odds)

    if bet_prob <= 0:
        return 0.0

    return (close_prob - bet_prob) / bet_prob * 100


# ───────────────────────────────────────────────────────────────────────
# Overround & fair odds utilities
# ───────────────────────────────────────────────────────────────────────

def calculate_overround(home_odds: float, draw_odds: float, away_odds: float) -> float:
    """Calculate the bookmaker's overround (margin) as a percentage.

    A perfectly fair market has overround = 0%.
    Typical bookmaker overround is 5-12%.
    Pinnacle is usually 2-3%.
    """
    return (odds_to_prob(home_odds) + odds_to_prob(draw_odds) + odds_to_prob(away_odds) - 1.0) * 100


def fair_odds(odds: float, overround: float) -> float:
    """Convert bookmaker odds to fair odds by removing overround.

    fair_odds are always >= bookmaker odds (better for the punter).
    """
    if odds <= 1.0 or overround <= 0:
        return odds
    implied = odds_to_prob(odds)
    fair_prob = implied / (1.0 + overround / 100.0)
    if fair_prob <= 0:
        return odds
    return 1.0 / fair_prob


def value_summary(value_bets: List[dict]) -> dict:
    """Summarise a list of value bets into an actionable overview.

    Returns a dict with:
    - total_bets: number of value bets found
    - total_stake: sum of Kelly stakes
    - total_ev: sum of expected values
    - avg_edge: average edge percentage
    - by_confidence: {HIGH: n, MEDIUM: n, LOW: n}
    - by_market: {1X2: n, O/U 2.5: n, BTTS: n}
    - best_bet: the single highest-EV bet (or None)
    """
    if not value_bets:
        return {
            "total_bets": 0, "total_stake": 0, "total_ev": 0,
            "avg_edge": 0, "by_confidence": {}, "by_market": {},
            "best_bet": None,
        }

    total_stake = sum(b["kelly_stake"] for b in value_bets)
    total_ev = sum(b["expected_value"] for b in value_bets)
    avg_edge = sum(b["edge"] for b in value_bets) / len(value_bets)

    by_conf: Dict[str, int] = {}
    by_market: Dict[str, int] = {}
    for b in value_bets:
        c = b.get("confidence", "LOW")
        by_conf[c] = by_conf.get(c, 0) + 1
        m = b["market"]
        by_market[m] = by_market.get(m, 0) + 1

    best = max(value_bets, key=lambda x: x["expected_value"])

    return {
        "total_bets": len(value_bets),
        "total_stake": round(total_stake, 2),
        "total_ev": round(total_ev, 2),
        "avg_edge": round(avg_edge, 1),
        "by_confidence": by_conf,
        "by_market": by_market,
        "best_bet": best,
    }


# ───────────────────────────────────────────────────────────────────────
# Value betting engine
# ───────────────────────────────────────────────────────────────────────

class ValueEngine:
    """Finds and ranks value betting opportunities."""

    def __init__(self, bankroll_config: Optional[BankrollConfig] = None,
                 poisson_config: Optional[PoissonConfig] = None):
        self.bankroll = bankroll_config or BankrollConfig()
        self.poisson = PoissonModel(poisson_config)
        self._bet_history: List[dict] = []

        # Load saved bankroll state
        saved = _load_bankroll()
        if saved.get("current_balance"):
            self.bankroll.current_balance = saved["current_balance"]
        if saved.get("starting_balance"):
            self.bankroll.starting_balance = saved["starting_balance"]
        if saved.get("bet_history"):
            self._bet_history = saved["bet_history"]

    def save_state(self):
        """Persist bankroll state to disk."""
        _save_bankroll({
            "current_balance": self.bankroll.current_balance,
            "starting_balance": self.bankroll.starting_balance,
            "bet_history": self._bet_history[-500:],  # Keep last 500 bets
            "last_updated": datetime.now().isoformat(),
        })

    def reset_bankroll(self, starting_balance: float = 1000.0):
        """Reset bankroll to starting state."""
        self.bankroll.starting_balance = starting_balance
        self.bankroll.current_balance = starting_balance
        self._bet_history = []
        self.save_state()

    def find_value_bets(self, results_df: pd.DataFrame,
                        fixtures_df: pd.DataFrame) -> list[dict]:
        """Find all value bets for upcoming fixtures.

        Returns list of value bet opportunities sorted by expected value (best first).
        Each entry includes all markets (1X2, O/U 2.5, BTTS).

        Also stores all predictions (with or without odds) in self.last_predictions
        so the GUI can display model probabilities for every fixture.
        """
        # Fit the Poisson model
        self.poisson.fit(results_df)
        predictions = self.poisson.predict_fixtures(results_df, fixtures_df)
        self.last_predictions = predictions

        cfg = self.bankroll
        value_bets = []

        for pred in predictions:
            match_bets = self._evaluate_match(pred, cfg)
            value_bets.extend(match_bets)

        # Sort by expected value descending (EV is what matters, not just edge)
        value_bets.sort(key=lambda x: x["expected_value"], reverse=True)
        return value_bets

    def _evaluate_match(self, pred: dict, cfg: BankrollConfig) -> list[dict]:
        """Evaluate all markets for a single match.

        Returns value bets with confidence ratings:
        - HIGH: edge >= 10% and model prob > 50%
        - MEDIUM: edge >= 5% or model prob > 40%
        - LOW: everything else that meets minimum edge
        """
        bets = []

        home = pred["home_team"]
        away = pred["away_team"]
        date = pred.get("date")

        def _rate_confidence(edge: float, model_prob: float) -> str:
            """Rate confidence in a value bet."""
            if edge >= 0.10 and model_prob > 0.50:
                return "HIGH"
            elif edge >= 0.05 or model_prob > 0.40:
                return "MEDIUM"
            return "LOW"

        # ── 1X2 Market ────────────────────────────────────────────────
        markets_1x2 = [
            ("Home Win", pred["p_home"], pred.get("b365_home"), pred.get("max_home")),
            ("Draw", pred["p_draw"], pred.get("b365_draw"), pred.get("max_draw")),
            ("Away Win", pred["p_away"], pred.get("b365_away"), pred.get("max_away")),
        ]

        for market_name, model_prob, b365_odds, max_odds in markets_1x2:
            # Use max odds for value calculation (best available price)
            best_odds = max_odds or b365_odds
            if best_odds is None or best_odds < cfg.min_odds or best_odds > cfg.max_odds:
                continue

            edge = calculate_edge(model_prob, best_odds)
            if edge < cfg.min_edge:
                continue

            stake = kelly_stake(
                model_prob, best_odds, cfg.current_balance,
                cfg.kelly_fraction, cfg.max_stake_pct,
            )
            stake = max(cfg.min_stake, min(stake, cfg.max_stake))

            ev = expected_value(model_prob, best_odds, stake)

            bets.append({
                "date": date,
                "home_team": home,
                "away_team": away,
                "market": "1X2",
                "selection": market_name,
                "model_prob": round(model_prob * 100, 1),
                "b365_odds": b365_odds,
                "best_odds": best_odds,
                "implied_prob": round(odds_to_prob(best_odds) * 100, 1),
                "edge": round(edge * 100, 1),
                "kelly_stake": round(stake, 2),
                "expected_value": round(ev, 2),
                "home_xg": pred["home_xg"],
                "away_xg": pred["away_xg"],
                "confidence": _rate_confidence(edge, model_prob),
            })

        # ── Over/Under 2.5 Market ────────────────────────────────────
        ou_markets = [
            ("Over 2.5", pred["p_over_25"], pred.get("over_25_odds")),
            ("Under 2.5", pred["p_under_25"], pred.get("under_25_odds")),
        ]

        for market_name, model_prob, odds in ou_markets:
            if odds is None:
                continue
            edge = calculate_edge(model_prob, odds)
            if edge < cfg.min_edge:
                continue

            stake = kelly_stake(
                model_prob, odds, cfg.current_balance,
                cfg.kelly_fraction, cfg.max_stake_pct,
            )
            stake = max(cfg.min_stake, min(stake, cfg.max_stake))
            ev = expected_value(model_prob, odds, stake)

            bets.append({
                "date": date,
                "home_team": home,
                "away_team": away,
                "market": "O/U 2.5",
                "selection": market_name,
                "model_prob": round(model_prob * 100, 1),
                "b365_odds": odds,
                "best_odds": odds,
                "implied_prob": round(odds_to_prob(odds) * 100, 1),
                "edge": round(edge * 100, 1),
                "kelly_stake": round(stake, 2),
                "expected_value": round(ev, 2),
                "home_xg": pred["home_xg"],
                "away_xg": pred["away_xg"],
                "confidence": _rate_confidence(edge, model_prob),
            })

        # ── BTTS Market ──────────────────────────────────────────────
        btts_markets = [
            ("BTTS Yes", pred["p_btts_yes"], None),
            ("BTTS No", pred["p_btts_no"], None),
        ]

        for market_name, model_prob, odds in btts_markets:
            if odds is None:
                continue
            edge = calculate_edge(model_prob, odds)
            if edge < cfg.min_edge:
                continue

            stake = kelly_stake(
                model_prob, odds, cfg.current_balance,
                cfg.kelly_fraction, cfg.max_stake_pct,
            )
            stake = max(cfg.min_stake, min(stake, cfg.max_stake))
            ev = expected_value(model_prob, odds, stake)

            bets.append({
                "date": date,
                "home_team": home,
                "away_team": away,
                "market": "BTTS",
                "selection": market_name,
                "model_prob": round(model_prob * 100, 1),
                "b365_odds": odds,
                "best_odds": odds,
                "implied_prob": round(odds_to_prob(odds) * 100, 1),
                "edge": round(edge * 100, 1),
                "kelly_stake": round(stake, 2),
                "expected_value": round(ev, 2),
                "home_xg": pred["home_xg"],
                "away_xg": pred["away_xg"],
                "confidence": _rate_confidence(edge, model_prob),
            })

        return bets

    def record_bet_result(self, bet: dict, won: bool, actual_odds: float = 0):
        """Record a bet result and update bankroll."""
        stake = bet["kelly_stake"]
        odds = actual_odds if actual_odds > 0 else bet["best_odds"]

        if won:
            profit = (odds - 1.0) * stake
        else:
            profit = -stake

        self.bankroll.current_balance += profit

        self._bet_history.append({
            "date": str(bet.get("date", "")),
            "match": f"{bet['home_team']} vs {bet['away_team']}",
            "market": bet["market"],
            "selection": bet["selection"],
            "odds": odds,
            "stake": stake,
            "won": won,
            "profit": round(profit, 2),
            "balance": round(self.bankroll.current_balance, 2),
            "edge": bet["edge"],
            "model_prob": bet["model_prob"],
            "recorded_at": datetime.now().isoformat(),
        })

        self.save_state()

    def get_bankroll_summary(self) -> dict:
        """Get current bankroll status and statistics."""
        cfg = self.bankroll
        history = self._bet_history

        if not history:
            return {
                "starting_balance": cfg.starting_balance,
                "current_balance": cfg.current_balance,
                "total_bets": 0,
                "won": 0,
                "lost": 0,
                "win_rate": 0.0,
                "total_staked": 0.0,
                "total_profit": 0.0,
                "roi": 0.0,
                "peak_balance": cfg.starting_balance,
                "max_drawdown": 0.0,
                "current_drawdown": 0.0,
                "is_stopped": False,
            }

        total_bets = len(history)
        won = sum(1 for b in history if b["won"])
        lost = total_bets - won
        total_staked = sum(b["stake"] for b in history)
        total_profit = cfg.current_balance - cfg.starting_balance

        # Calculate peak and drawdown
        running_balance = cfg.starting_balance
        peak = cfg.starting_balance
        max_dd = 0.0
        for b in history:
            running_balance += b["profit"]
            peak = max(peak, running_balance)
            dd = (peak - running_balance) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        current_dd = (peak - cfg.current_balance) / peak if peak > 0 else 0

        return {
            "starting_balance": cfg.starting_balance,
            "current_balance": round(cfg.current_balance, 2),
            "total_bets": total_bets,
            "won": won,
            "lost": lost,
            "win_rate": round(won / total_bets * 100, 1) if total_bets > 0 else 0.0,
            "total_staked": round(total_staked, 2),
            "total_profit": round(total_profit, 2),
            "roi": round(total_profit / total_staked * 100, 1) if total_staked > 0 else 0.0,
            "peak_balance": round(peak, 2),
            "max_drawdown": round(max_dd * 100, 1),
            "current_drawdown": round(current_dd * 100, 1),
            "is_stopped": current_dd >= cfg.drawdown_limit,
        }

    def get_bet_history(self) -> list[dict]:
        """Return bet history, most recent first."""
        return list(reversed(self._bet_history))

    def backtest_value(self, results_df: pd.DataFrame,
                       train_frac: float = 0.6) -> dict:
        """Backtest value betting strategy on historical data.

        Splits data into train/test, fits Poisson on train,
        then simulates betting on test matches using value criteria.
        """
        df = results_df.copy()
        if "Date" in df.columns:
            df = df.sort_values("Date", na_position="first")

        n = len(df)
        split = int(n * train_frac)
        train = df.iloc[:split]
        test = df.iloc[split:]

        # Fit on training data
        self.poisson.fit(train)

        cfg = self.bankroll
        balance = cfg.starting_balance
        peak = balance
        max_dd = 0.0

        total_bets = 0
        won = 0
        total_staked = 0.0
        total_returned = 0.0
        bets_log = []

        for _, row in test.iterrows():
            home = row["Team"]
            away = row["Opponent"]
            actual = row["Result"]  # W, D, L

            pred = self.poisson.predict_match(home, away)
            if pred is None:
                continue

            # Check 1X2 markets
            markets = [
                ("Home Win", pred["p_home"], "Home_Odds", "W"),
                ("Draw", pred["p_draw"], "Draw_Odds", "D"),
                ("Away Win", pred["p_away"], "Away_Odds", "L"),
            ]

            for sel, model_prob, odds_col, winning_result in markets:
                odds_val = row.get(odds_col, float("nan"))
                if pd.isna(odds_val) or odds_val < cfg.min_odds or odds_val > cfg.max_odds:
                    continue

                odds = float(odds_val)
                edge = calculate_edge(model_prob, odds)

                if edge < cfg.min_edge:
                    continue

                # Calculate stake
                stake = kelly_stake(
                    model_prob, odds, balance,
                    cfg.kelly_fraction, cfg.max_stake_pct,
                )
                stake = max(cfg.min_stake, min(stake, cfg.max_stake))

                # Check if won
                is_won = actual == winning_result

                if is_won:
                    profit = (odds - 1.0) * stake
                    total_returned += odds * stake
                else:
                    profit = -stake

                balance += profit
                total_staked += stake
                total_bets += 1
                if is_won:
                    won += 1

                peak = max(peak, balance)
                dd = (peak - balance) / peak if peak > 0 else 0
                max_dd = max(max_dd, dd)

                bets_log.append({
                    "match": f"{home} vs {away}",
                    "selection": sel,
                    "odds": odds,
                    "stake": round(stake, 2),
                    "edge": round(edge * 100, 1),
                    "model_prob": round(model_prob * 100, 1),
                    "won": is_won,
                    "profit": round(profit, 2),
                    "balance": round(balance, 2),
                })

        total_profit = balance - cfg.starting_balance

        return {
            "starting_balance": cfg.starting_balance,
            "final_balance": round(balance, 2),
            "total_bets": total_bets,
            "won": won,
            "lost": total_bets - won,
            "win_rate": round(won / total_bets * 100, 1) if total_bets > 0 else 0.0,
            "total_staked": round(total_staked, 2),
            "total_returned": round(total_returned, 2),
            "total_profit": round(total_profit, 2),
            "roi": round(total_profit / total_staked * 100, 1) if total_staked > 0 else 0.0,
            "peak_balance": round(peak, 2),
            "max_drawdown": round(max_dd * 100, 1),
            "train_matches": len(train),
            "test_matches": len(test),
            "bets_log": bets_log,
        }
