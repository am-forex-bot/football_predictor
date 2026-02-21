"""Prediction engine — category-weighted form scoring with configurable weights,
backtesting grid search, weekly performance tracking, and weight tuning.

Key fixes from audit of ChatGPT version:
- Uses MEAN not SUM so teams with fewer matches aren't penalised
- Minimum history check enforced in live predictions
- Validates no_bet_band < threshold
- Win weights clamped so wins never score negative
- Weight tuner uses train/validation split to prevent overfitting
- No chimera config bug — consistent config tracking
- Heavy loss threshold configurable
"""

from __future__ import annotations

import itertools
import random
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, Optional

import pandas as pd

# ───────────────────────────────────────────────────────────────────────
# Constants
# ───────────────────────────────────────────────────────────────────────

TIERS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7"]
CATEGORY_TO_TIER = {"A": "T1", "B": "T2", "C": "T3", "D": "T4",
                    "E": "T5", "F": "T6", "G": "T7"}


# ───────────────────────────────────────────────────────────────────────
# Config
# ───────────────────────────────────────────────────────────────────────

@dataclass
class PredictorConfig:
    lookback: int = 6
    threshold: float = 3.0
    no_bet_band: float = 0.0
    heavy_loss_gd: int = -2

    win_weights: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "Home": {"T1": 7, "T2": 6, "T3": 5, "T4": 4, "T5": 3, "T6": 2, "T7": 1},
        "Away": {"T1": 8, "T2": 7, "T3": 6, "T4": 5, "T5": 4, "T6": 3, "T7": 2},
    })
    draw_weights: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "Home": {"T1": 5, "T2": 4, "T3": 3, "T4": 2, "T5": 1, "T6": 0, "T7": -1},
        "Away": {"T1": 6, "T2": 5, "T3": 4, "T4": 3, "T5": 2, "T6": 1, "T7": 0},
    })
    loss_close_weights: Dict[str, Dict[str, float]] = field(default_factory=lambda: {
        "Home": {"T1": 1, "T2": 0, "T3": -1, "T4": -2, "T5": -3, "T6": -4, "T7": -5},
        "Away": {"T1": 2, "T2": 1, "T3": 0, "T4": -1, "T5": -2, "T6": -3, "T7": -4},
    })
    loss_heavy_penalty: float = -1.0


# ───────────────────────────────────────────────────────────────────────
# Category inference from league table
# ───────────────────────────────────────────────────────────────────────

def infer_categories(table: pd.DataFrame) -> Dict[str, str]:
    """Assign A-G category based on league position."""
    if table.empty:
        return {}
    n = len(table)
    pos_col = "Position" if "Position" in table.columns else "Pos"
    mapping = {}
    for _, row in table.iterrows():
        p = int(row[pos_col])
        if n >= 18:
            if p <= 2:      c = "A"
            elif p <= 5:    c = "B"
            elif p <= 8:    c = "C"
            elif p <= 12:   c = "D"
            elif p <= 15:   c = "E"
            elif p <= 18:   c = "F"
            else:           c = "G"
        else:
            q = (p - 1) / max(n, 1)
            if q < 0.10:    c = "A"
            elif q < 0.25:  c = "B"
            elif q < 0.40:  c = "C"
            elif q < 0.60:  c = "D"
            elif q < 0.78:  c = "E"
            elif q < 0.92:  c = "F"
            else:           c = "G"
        mapping[str(row["Team"])] = c
    return mapping


# ───────────────────────────────────────────────────────────────────────
# Match predictor
# ───────────────────────────────────────────────────────────────────────

class MatchPredictor:
    def __init__(self, config: Optional[PredictorConfig] = None):
        self.config = config or PredictorConfig()

    def _score_match(self, result: str, venue: str, opp_category: str,
                     gf: int, ga: int) -> float:
        tier = CATEGORY_TO_TIER.get(str(opp_category).upper()[:1], "T4")
        cfg = self.config
        if result == "W":
            return cfg.win_weights[venue][tier]
        if result == "D":
            return cfg.draw_weights[venue][tier]
        base = cfg.loss_close_weights[venue][tier]
        gd = gf - ga
        if gd <= cfg.heavy_loss_gd:
            base += cfg.loss_heavy_penalty
        return base

    def _build_scored_history(self, results_df: pd.DataFrame,
                              category_map: dict):
        """Build per-team home/away scored match histories in chronological order.

        Returns (home_history, away_history) where each is
        dict[team] -> list of {score, result, h_odds, d_odds, a_odds}.
        """
        home_hist: dict[str, list[dict]] = {}
        away_hist: dict[str, list[dict]] = {}

        for _, row in results_df.iterrows():
            home = row["Team"]
            away = row["Opponent"]
            result = row["Result"]
            gf = int(row["GF"]) if pd.notna(row["GF"]) else 0
            ga = int(row["GA"]) if pd.notna(row["GA"]) else 0
            h_odds = row.get("Home_Odds", float("nan"))
            d_odds = row.get("Draw_Odds", float("nan"))
            a_odds = row.get("Away_Odds", float("nan"))

            away_cat = category_map.get(away, "D")
            home_cat = category_map.get(home, "D")

            home_score = self._score_match(result, "Home", away_cat, gf, ga)
            home_hist.setdefault(home, []).append({
                "score": home_score, "result": result,
                "h_odds": h_odds, "d_odds": d_odds, "a_odds": a_odds,
            })

            away_result = "L" if result == "W" else ("W" if result == "L" else "D")
            away_score = self._score_match(away_result, "Away", home_cat, ga, gf)
            away_hist.setdefault(away, []).append({
                "score": away_score, "result": away_result,
                "h_odds": h_odds, "d_odds": d_odds, "a_odds": a_odds,
            })

        return home_hist, away_hist

    def _mean_form(self, history: list[dict], end_idx: int,
                   lookback: int) -> Optional[float]:
        """Mean score over history[end_idx-lookback : end_idx].
        Returns None if not enough history."""
        if end_idx < lookback:
            return None
        segment = history[end_idx - lookback:end_idx]
        return sum(m["score"] for m in segment) / lookback

    # ── Live prediction ──────────────────────────────────────────────

    def predict_fixtures(self, results_df: pd.DataFrame,
                         league_table_df: pd.DataFrame,
                         fixtures_df: pd.DataFrame) -> list[dict]:
        """Predict upcoming fixtures."""
        cat_map = infer_categories(league_table_df)
        home_hist, away_hist = self._build_scored_history(results_df, cat_map)

        cfg = self.config
        threshold = cfg.threshold
        no_bet = min(cfg.no_bet_band, threshold - 0.01)  # clamp
        lookback = cfg.lookback

        predictions = []
        predicted_teams: set[str] = set()

        for _, fix in fixtures_df.iterrows():
            home = fix["Team"]
            away = fix["Opponent"]

            if home in predicted_teams or away in predicted_teams:
                continue

            h_matches = home_hist.get(home, [])
            a_matches = away_hist.get(away, [])

            # Use ALL accumulated history up to now
            h_score = self._mean_form(h_matches, len(h_matches), lookback)
            a_score = self._mean_form(a_matches, len(a_matches), lookback)

            if h_score is None or a_score is None:
                continue

            diff = h_score - a_score

            if abs(diff) <= no_bet:
                pred_text = "No Bet"
            elif diff > threshold:
                pred_text = f"{home} Win"
            elif diff < -threshold:
                pred_text = f"{away} Win"
            else:
                pred_text = "Draw"

            h_odds = fix.get("Home_Odds", float("nan"))
            d_odds = fix.get("Draw_Odds", float("nan"))
            a_odds = fix.get("Away_Odds", float("nan"))

            predictions.append({
                "home_team": home,
                "away_team": away,
                "prediction": pred_text,
                "home_score": round(h_score, 2),
                "away_score": round(a_score, 2),
                "score_diff": round(diff, 2),
                "home_cat": cat_map.get(home, "D"),
                "away_cat": cat_map.get(away, "D"),
                "home_odds": h_odds if pd.notna(h_odds) else None,
                "draw_odds": d_odds if pd.notna(d_odds) else None,
                "away_odds": a_odds if pd.notna(a_odds) else None,
            })
            predicted_teams.add(home)
            predicted_teams.add(away)

        return predictions

    # ── Backtesting ──────────────────────────────────────────────────

    def backtest(self, results_df: pd.DataFrame,
                 league_table_df: pd.DataFrame,
                 threshold_min: int = 1, threshold_max: int = 20,
                 lookback_min: int = 3, lookback_max: int = 20) -> dict:
        """Grid search across threshold/lookback combos.

        For each completed match, simulate prediction using only prior matches.
        Track accuracy, draw stats, odds, and per-game results for weekly analysis.
        """
        cat_map = infer_categories(league_table_df)
        home_hist, away_hist = self._build_scored_history(results_df, cat_map)

        # Build index: for each row, track which home/away match number it is
        home_idx: dict[str, int] = defaultdict(int)  # team -> running count
        away_idx: dict[str, int] = defaultdict(int)
        row_home_n = []  # home match number for row i
        row_away_n = []  # away match number for row i
        for _, row in results_df.iterrows():
            h = row["Team"]
            a = row["Opponent"]
            row_home_n.append(home_idx[h])
            row_away_n.append(away_idx[a])
            home_idx[h] += 1
            away_idx[a] += 1

        accuracy = {}
        draw_stats = {}
        odds_stats = {}
        game_log = {}  # (t, lb) -> list of {correct, predicted, actual}

        for threshold in range(threshold_min, threshold_max + 1):
            accuracy[threshold] = {}
            draw_stats[threshold] = {}
            odds_stats[threshold] = {}

            for lookback in range(lookback_min, lookback_max + 1):
                correct_count = 0
                total_count = 0
                d_predicted = 0
                d_correct = 0
                odds_combined = 0.0
                correct_with_odds = 0
                games = []

                for i, (_, row) in enumerate(results_df.iterrows()):
                    home = row["Team"]
                    away = row["Opponent"]
                    hn = row_home_n[i]  # home has played hn home matches before this
                    an = row_away_n[i]  # away has played an away matches before this

                    if hn < lookback or an < lookback:
                        continue

                    h_score = self._mean_form(home_hist[home], hn, lookback)
                    a_score = self._mean_form(away_hist[away], an, lookback)

                    if h_score is None or a_score is None:
                        continue

                    diff = h_score - a_score

                    if diff > threshold:
                        predicted = "W"
                    elif diff < -threshold:
                        predicted = "L"
                    else:
                        predicted = "D"

                    actual = row["Result"]
                    is_correct = predicted == actual
                    total_count += 1
                    if is_correct:
                        correct_count += 1

                    if predicted == "D":
                        d_predicted += 1
                        if actual == "D":
                            d_correct += 1

                    if is_correct:
                        if predicted == "W":
                            odd = row.get("Home_Odds", float("nan"))
                        elif predicted == "D":
                            odd = row.get("Draw_Odds", float("nan"))
                        else:
                            odd = row.get("Away_Odds", float("nan"))
                        if pd.notna(odd):
                            odds_combined += float(odd)
                            correct_with_odds += 1

                    games.append({
                        "row": i, "correct": is_correct,
                        "predicted": predicted, "actual": actual,
                    })

                acc = (correct_count / total_count * 100) if total_count else 0.0
                accuracy[threshold][lookback] = acc
                draw_stats[threshold][lookback] = {
                    "correct": d_correct, "predicted": d_predicted,
                }
                odds_stats[threshold][lookback] = {
                    "combined": odds_combined,
                    "total": total_count,
                    "avg": (odds_combined / correct_with_odds) if correct_with_odds else 0.0,
                }
                game_log[(threshold, lookback)] = {
                    "total": total_count, "correct": correct_count,
                    "games": games,
                }

        # Find best
        best = (threshold_min, lookback_min, 0.0)
        for t, lb_dict in accuracy.items():
            for lb, acc in lb_dict.items():
                if acc > best[2]:
                    best = (t, lb, acc)

        return {
            "accuracy": accuracy,
            "draw_stats": draw_stats,
            "odds_stats": odds_stats,
            "best": best,
            "game_log": game_log,
        }

    # ── Weekly performance ───────────────────────────────────────────

    def weekly_performance(self, results_df: pd.DataFrame,
                           league_table_df: pd.DataFrame,
                           threshold_min: int = 1, threshold_max: int = 20,
                           lookback_min: int = 3, lookback_max: int = 20,
                           min_week_games: int = 3) -> list[dict]:
        """Analyse prediction accuracy per gameweek for each threshold/lookback combo.

        Groups results into gameweeks (Mon-Sun) and finds combos that nail
        entire gameweeks at 100%, 90%, 80%.
        """
        bt = self.backtest(results_df, league_table_df,
                           threshold_min, threshold_max,
                           lookback_min, lookback_max)

        # We need row dates for weekly grouping
        dates = results_df.reset_index(drop=True)
        # Try to get a date column if it exists in the original data
        # Results from our cleaner don't have Date, but the row order IS chronological
        # So we'll group by chunks of ~10 matches as approximate "gameweeks"
        # But better: group by match-day batches where multiple games share the same
        # set of teams

        summary_rows = []

        for (threshold, lookback), log in bt["game_log"].items():
            games = log["games"]
            if not games:
                summary_rows.append({
                    "threshold": threshold, "lookback": lookback,
                    "total_games": 0, "accuracy": 0.0,
                    "perfect_weeks": 0, "weeks_ge90": 0,
                    "weeks_ge80": 0, "weeks_ge70": 0,
                    "weeks_tested": 0,
                })
                continue

            # Group into approximate gameweeks of ~10 matches
            # (since we don't have dates, use sequential batches based on
            # the number of teams / 2)
            n_teams = len(league_table_df)
            games_per_week = max(n_teams // 2, 1)
            weeks = []
            for w_start in range(0, len(games), games_per_week):
                week = games[w_start:w_start + games_per_week]
                if len(week) < min_week_games:
                    continue
                w_correct = sum(1 for g in week if g["correct"])
                w_total = len(week)
                w_acc = (w_correct / w_total * 100) if w_total else 0.0
                weeks.append({"correct": w_correct, "total": w_total, "acc": w_acc})

            total_games = log["total"]
            total_correct = log["correct"]
            acc = (total_correct / total_games * 100) if total_games else 0.0

            perfect = sum(1 for w in weeks if w["acc"] >= 100.0)
            ge90 = sum(1 for w in weeks if w["acc"] >= 90.0)
            ge80 = sum(1 for w in weeks if w["acc"] >= 80.0)
            ge70 = sum(1 for w in weeks if w["acc"] >= 70.0)

            summary_rows.append({
                "threshold": threshold, "lookback": lookback,
                "total_games": total_games, "accuracy": round(acc, 2),
                "perfect_weeks": perfect, "weeks_ge90": ge90,
                "weeks_ge80": ge80, "weeks_ge70": ge70,
                "weeks_tested": len(weeks),
            })

        # Sort by perfect weeks first, then 90%+, then overall accuracy
        summary_rows.sort(key=lambda r: (
            r["perfect_weeks"], r["weeks_ge90"], r["weeks_ge80"],
            r["accuracy"], r["total_games"],
        ), reverse=True)

        return summary_rows


# ───────────────────────────────────────────────────────────────────────
# Weight tuner
# ───────────────────────────────────────────────────────────────────────

def _sample_monotonic_desc(rng: random.Random, hi_range=(5, 10),
                           min_step=0.3, max_step=1.8,
                           floor=0.5) -> list[float]:
    """Descending values with floor (wins never go negative)."""
    vals = []
    cur = rng.uniform(*hi_range)
    vals.append(round(cur, 2))
    for _ in range(len(TIERS) - 1):
        cur = cur - rng.uniform(min_step, max_step)
        cur = max(cur, floor)
        vals.append(round(cur, 2))
    return vals


def _sample_monotonic_mixed(rng: random.Random, start_range=(2, 4),
                            end_range=(-4, -1)) -> list[float]:
    """Descend from positive to negative (for loss weights)."""
    start = rng.uniform(*start_range)
    end = rng.uniform(*end_range)
    n = max(1, len(TIERS) - 1)
    vals = [round(start + (end - start) * (i / n), 2) for i in range(len(TIERS))]
    vals = [round(v + rng.uniform(-0.3, 0.3), 2) for v in vals]
    for i in range(1, len(TIERS)):
        if vals[i] > vals[i - 1] - 0.1:
            vals[i] = round(vals[i - 1] - rng.uniform(0.2, 0.8), 2)
    return vals


def random_weight_config(rng: random.Random,
                         base_cfg: PredictorConfig) -> PredictorConfig:
    """Generate random weight config for tuning."""
    cfgd = asdict(base_cfg)

    win_home = _sample_monotonic_desc(rng, hi_range=(5.5, 8.5), floor=0.5)
    win_away = [round(v + rng.uniform(0.3, 1.6), 2) for v in win_home]

    draw_home = _sample_monotonic_desc(rng, hi_range=(3.0, 6.0),
                                       min_step=0.3, max_step=1.2, floor=-1.0)
    draw_away = [round(v + rng.uniform(0.1, 1.2), 2) for v in draw_home]

    loss_home = _sample_monotonic_mixed(rng, start_range=(1.0, 3.0),
                                        end_range=(-4.5, -1.5))
    loss_away = [round(v + rng.uniform(0.2, 1.2), 2) for v in loss_home]

    cfgd["win_weights"] = {
        "Home": dict(zip(TIERS, win_home)),
        "Away": dict(zip(TIERS, win_away)),
    }
    cfgd["draw_weights"] = {
        "Home": dict(zip(TIERS, draw_home)),
        "Away": dict(zip(TIERS, draw_away)),
    }
    cfgd["loss_close_weights"] = {
        "Home": dict(zip(TIERS, loss_home)),
        "Away": dict(zip(TIERS, loss_away)),
    }
    cfgd["loss_heavy_penalty"] = round(rng.uniform(-2.5, -0.3), 2)

    return PredictorConfig(**cfgd)


def tune_weights(results_df: pd.DataFrame, league_table_df: pd.DataFrame,
                 n_candidates: int = 80,
                 lookback_min: int = 3, lookback_max: int = 20,
                 threshold_min: int = 1, threshold_max: int = 20,
                 seed: int = 42,
                 progress_callback=None) -> dict:
    """Tune weights with train/validation split to prevent overfitting.

    First 70% of matches = training, last 30% = validation.
    Ranks by blended accuracy (40% train + 60% validation).
    """
    rng = random.Random(seed)

    n_results = len(results_df)
    split_idx = int(n_results * 0.7)
    train_df = results_df.iloc[:split_idx].copy().reset_index(drop=True)
    valid_df = results_df.iloc[split_idx:].copy().reset_index(drop=True)

    base_cfg = PredictorConfig()
    leaderboard = []

    for cid in range(1, n_candidates + 1):
        cfg = random_weight_config(rng, base_cfg)
        predictor = MatchPredictor(cfg)

        # Quick backtest on training data
        train_bt = predictor.backtest(
            train_df, league_table_df,
            threshold_min=threshold_min, threshold_max=threshold_max,
            lookback_min=lookback_min, lookback_max=lookback_max,
        )

        # Find best combo on training data (with min games filter)
        best_train_acc = 0.0
        best_lb = lookback_min
        best_th = threshold_min
        best_train_games = 0

        for t, lb_dict in train_bt["accuracy"].items():
            for lb, acc in lb_dict.items():
                games = train_bt["game_log"].get((t, lb), {}).get("total", 0)
                if games < 20:
                    continue
                if acc > best_train_acc or (acc == best_train_acc and games > best_train_games):
                    best_train_acc = acc
                    best_lb = lb
                    best_th = t
                    best_train_games = games

        # Validate with best params on held-out data
        val_bt = predictor.backtest(
            valid_df, league_table_df,
            threshold_min=best_th, threshold_max=best_th,
            lookback_min=best_lb, lookback_max=best_lb,
        )
        val_acc = val_bt["accuracy"].get(best_th, {}).get(best_lb, 0.0)
        val_games = val_bt["game_log"].get((best_th, best_lb), {}).get("total", 0)

        blended = round(0.4 * best_train_acc + 0.6 * val_acc, 2) if val_games >= 10 else round(best_train_acc * 0.5, 2)

        leaderboard.append({
            "candidate_id": cid,
            "lookback": best_lb,
            "threshold": best_th,
            "train_acc": round(best_train_acc, 2),
            "train_games": best_train_games,
            "valid_acc": round(val_acc, 2),
            "valid_games": val_games,
            "blended_acc": blended,
            "config": cfg,
        })

        if progress_callback:
            progress_callback(cid, n_candidates)

    if not leaderboard:
        return {"leaderboard": pd.DataFrame(), "best_config": None}

    lb_df = pd.DataFrame([{k: v for k, v in r.items() if k != "config"}
                          for r in leaderboard])
    lb_df = lb_df.sort_values(
        ["blended_acc", "valid_acc", "train_acc", "valid_games"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)

    best_cid = int(lb_df.iloc[0]["candidate_id"])
    best_entry = next(r for r in leaderboard if r["candidate_id"] == best_cid)
    best_config = asdict(best_entry["config"])
    best_config["lookback"] = int(lb_df.iloc[0]["lookback"])
    best_config["threshold"] = float(lb_df.iloc[0]["threshold"])

    return {
        "leaderboard": lb_df,
        "best_config": best_config,
    }
