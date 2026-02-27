"""Poisson goal model — estimates match probabilities from historical goal data.

Calculates per-team attack/defense strength ratings relative to league averages,
then uses the Poisson distribution to generate a goal probability matrix for
each fixture. From this matrix we derive:

- P(Home Win), P(Draw), P(Away Win)
- P(Over/Under 2.5 goals)
- P(Both Teams To Score)
- Expected goals (xG) for each team
- Correct score probabilities

The model uses a configurable lookback window (number of recent matches) and
can weight recent matches more heavily via exponential decay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import factorial, exp
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# Maximum goals to model per side (0-7 covers 99.9%+ of outcomes)
MAX_GOALS = 8


@dataclass
class PoissonConfig:
    """Configuration for the Poisson model."""
    lookback: int = 0             # Matches per team to consider (0 = all season data)
    decay_rate: float = 0.0       # Exponential decay (0 = equal weight, 0.03 = moderate)
    home_advantage: float = 0.0   # Additional home xG boost (0 = learned from data)
    min_matches: int = 3          # Minimum matches required per team


def _poisson_pmf(k: int, lam: float) -> float:
    """Probability of exactly k goals given expected rate lam."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(-lam) * (lam ** k) / factorial(k)


def _build_goal_matrix(home_xg: float, away_xg: float) -> np.ndarray:
    """Build MAX_GOALS x MAX_GOALS probability matrix.

    matrix[i][j] = P(home scores i AND away scores j)
    Assumes independence between home and away goals.
    """
    matrix = np.zeros((MAX_GOALS, MAX_GOALS))
    for i in range(MAX_GOALS):
        p_home = _poisson_pmf(i, home_xg)
        for j in range(MAX_GOALS):
            matrix[i, j] = p_home * _poisson_pmf(j, away_xg)
    return matrix


class PoissonModel:
    """Poisson-based match probability model."""

    def __init__(self, config: Optional[PoissonConfig] = None):
        self.config = config or PoissonConfig()
        self._team_stats: Dict[str, dict] = {}
        self._league_avg_home_goals: float = 0.0
        self._league_avg_away_goals: float = 0.0
        self._fitted = False

    def fit(self, results_df: pd.DataFrame) -> "PoissonModel":
        """Fit the model from historical results.

        results_df must have columns: Team, Opponent, GF, GA, Result
        (as produced by cleaner.clean_results)
        """
        df = results_df.copy()
        df["GF"] = pd.to_numeric(df["GF"], errors="coerce").fillna(0)
        df["GA"] = pd.to_numeric(df["GA"], errors="coerce").fillna(0)

        cfg = self.config

        # If lookback > 0, take only the most recent N matches per team
        if cfg.lookback > 0:
            df = self._apply_lookback(df, cfg.lookback)

        n_matches = len(df)
        if n_matches == 0:
            self._fitted = False
            return self

        # League averages (each row = one match from home perspective)
        self._league_avg_home_goals = df["GF"].mean()
        self._league_avg_away_goals = df["GA"].mean()

        # Per-team attack and defense ratings
        # Attack = goals scored / league avg for that venue
        # Defense = goals conceded / league avg for that venue
        stats: Dict[str, dict] = {}

        # Home stats: GF = home attack, GA = home defense (conceded)
        home_groups = df.groupby("Team").agg(
            home_gf=("GF", "sum"),
            home_ga=("GA", "sum"),
            home_n=("GF", "count"),
        )

        # Away stats: GA = away team scored (from home perspective), GF = away conceded
        away_groups = df.groupby("Opponent").agg(
            away_gf=("GA", "sum"),   # Away team's goals = home GA
            away_ga=("GF", "sum"),   # Away team conceded = home GF
            away_n=("GA", "count"),
        )

        avg_hg = max(self._league_avg_home_goals, 0.01)
        avg_ag = max(self._league_avg_away_goals, 0.01)

        all_teams = sorted(set(home_groups.index) | set(away_groups.index))

        for team in all_teams:
            s = {
                "home_attack": 1.0, "home_defense": 1.0,
                "away_attack": 1.0, "away_defense": 1.0,
                "home_matches": 0, "away_matches": 0,
            }

            if team in home_groups.index:
                row = home_groups.loc[team]
                n = int(row["home_n"])
                if n >= 1:
                    s["home_attack"] = (row["home_gf"] / n) / avg_hg
                    s["home_defense"] = (row["home_ga"] / n) / avg_ag
                    s["home_matches"] = n

            if team in away_groups.index:
                row = away_groups.loc[team]
                n = int(row["away_n"])
                if n >= 1:
                    s["away_attack"] = (row["away_gf"] / n) / avg_ag
                    s["away_defense"] = (row["away_ga"] / n) / avg_hg
                    s["away_matches"] = n

            stats[team] = s

        self._team_stats = stats
        self._fitted = True
        return self

    def _apply_lookback(self, df: pd.DataFrame, lookback: int) -> pd.DataFrame:
        """Keep only the most recent `lookback` matches per team.

        Each row is a home match (Team = home, Opponent = away).
        For each team, we keep their most recent `lookback` appearances
        as EITHER home or away. This ensures every team has enough data
        for reliable ratings.
        """
        if "Date" in df.columns:
            df = df.sort_values("Date", na_position="first")

        # Track which rows to keep — a row is kept if EITHER team
        # still needs more matches in their lookback window
        keep = set()
        team_count: dict[str, int] = {}

        # Walk backwards from most recent
        for idx in reversed(df.index):
            home = df.at[idx, "Team"]
            away = df.at[idx, "Opponent"]

            h_count = team_count.get(home, 0)
            a_count = team_count.get(away, 0)

            # Keep this row if either team hasn't filled their quota
            if h_count < lookback or a_count < lookback:
                keep.add(idx)
                team_count[home] = h_count + 1
                team_count[away] = a_count + 1

        if not keep:
            return df

        return df.loc[sorted(keep)].reset_index(drop=True)

    def predict_match(self, home_team: str, away_team: str) -> Optional[dict]:
        """Predict a single match. Returns probability dict or None if teams unknown."""
        if not self._fitted:
            return None

        h_stats = self._team_stats.get(home_team)
        a_stats = self._team_stats.get(away_team)

        if h_stats is None or a_stats is None:
            return None

        min_m = self.config.min_matches
        if h_stats["home_matches"] < min_m or a_stats["away_matches"] < min_m:
            return None

        # Expected goals
        # Home xG = home_attack * away_defense * league_avg_home_goals
        # Away xG = away_attack * home_defense * league_avg_away_goals
        home_xg = (h_stats["home_attack"] * a_stats["away_defense"] *
                   self._league_avg_home_goals + self.config.home_advantage)
        away_xg = (a_stats["away_attack"] * h_stats["home_defense"] *
                   self._league_avg_away_goals)

        # Clamp to reasonable range
        home_xg = max(0.1, min(home_xg, 6.0))
        away_xg = max(0.1, min(away_xg, 6.0))

        # Build probability matrix
        matrix = _build_goal_matrix(home_xg, away_xg)

        # Derive probabilities
        p_home = 0.0
        p_draw = 0.0
        p_away = 0.0
        p_over_25 = 0.0
        p_btts = 0.0

        for i in range(MAX_GOALS):
            for j in range(MAX_GOALS):
                p = matrix[i, j]
                if i > j:
                    p_home += p
                elif i == j:
                    p_draw += p
                else:
                    p_away += p

                if i + j > 2:
                    p_over_25 += p

                if i >= 1 and j >= 1:
                    p_btts += p

        # Top correct scores
        correct_scores = {}
        for i in range(min(MAX_GOALS, 5)):
            for j in range(min(MAX_GOALS, 5)):
                if matrix[i, j] >= 0.01:  # Only include >= 1%
                    correct_scores[f"{i}-{j}"] = round(matrix[i, j] * 100, 1)

        # Sort by probability descending
        correct_scores = dict(sorted(correct_scores.items(),
                                      key=lambda x: x[1], reverse=True)[:8])

        return {
            "home_team": home_team,
            "away_team": away_team,
            "home_xg": round(home_xg, 2),
            "away_xg": round(away_xg, 2),
            "p_home": round(p_home, 4),
            "p_draw": round(p_draw, 4),
            "p_away": round(p_away, 4),
            "p_over_25": round(p_over_25, 4),
            "p_under_25": round(1 - p_over_25, 4),
            "p_btts_yes": round(p_btts, 4),
            "p_btts_no": round(1 - p_btts, 4),
            "correct_scores": correct_scores,
            "matrix": matrix,
        }

    def predict_fixtures(self, results_df: pd.DataFrame,
                         fixtures_df: pd.DataFrame) -> list[dict]:
        """Predict all upcoming fixtures.

        Handles both column conventions:
        - Team/Opponent (cleaned format)
        - HomeTeam/AwayTeam (raw format)

        If team names from odds API don't match the model's trained names,
        attempts fuzzy matching via the odds_provider._match_team function.
        """
        self.fit(results_df)
        predictions = []

        # Determine column names
        if "Team" in fixtures_df.columns:
            home_col, away_col = "Team", "Opponent"
        elif "HomeTeam" in fixtures_df.columns:
            home_col, away_col = "HomeTeam", "AwayTeam"
        else:
            return predictions

        # All team names the model knows about
        known_teams = list(self._team_stats.keys())

        for _, fix in fixtures_df.iterrows():
            home = fix[home_col]
            away = fix[away_col]

            pred = self.predict_match(home, away)

            # If direct match fails, try fuzzy matching against known teams
            if pred is None and known_teams:
                try:
                    from core.odds_provider import _match_team
                    mapped_home = _match_team(home, known_teams) or home
                    mapped_away = _match_team(away, known_teams) or away
                    if mapped_home != home or mapped_away != away:
                        pred = self.predict_match(mapped_home, mapped_away)
                except ImportError:
                    pass

            if pred is None:
                continue

            # Add fixture metadata
            fix_date = fix.get("Date", None)
            if pd.notna(fix_date):
                try:
                    pred["date"] = pd.Timestamp(fix_date)
                except Exception:
                    pred["date"] = None
            else:
                pred["date"] = None

            # Add odds from fixture data (1X2)
            for src, dst in [("Home_Odds", "b365_home"),
                             ("Draw_Odds", "b365_draw"),
                             ("Away_Odds", "b365_away"),
                             ("Max_Home_Odds", "max_home"),
                             ("Max_Draw_Odds", "max_draw"),
                             ("Max_Away_Odds", "max_away"),
                             ("Over_25_Odds", "over_25_odds"),
                             ("Under_25_Odds", "under_25_odds"),
                             ("BTTS_Yes_Odds", "btts_yes_odds"),
                             ("BTTS_No_Odds", "btts_no_odds")]:
                val = fix.get(src, float("nan"))
                pred[dst] = float(val) if pd.notna(val) and val > 0 else None

            predictions.append(pred)

        return predictions

    def backtest(self, results_df: pd.DataFrame,
                 train_frac: float = 0.7) -> dict:
        """Backtest the model on historical data.

        Splits results into train/test by time, fits on train,
        evaluates on test matches.
        """
        df = results_df.copy()
        if "Date" in df.columns:
            df = df.sort_values("Date", na_position="first")

        n = len(df)
        split = int(n * train_frac)
        train = df.iloc[:split]
        test = df.iloc[split:]

        # Fit on training data
        self.fit(train)

        # Evaluate on test data
        correct = 0
        total = 0
        predictions = []

        for _, row in test.iterrows():
            home = row["Team"]
            away = row["Opponent"]
            actual_result = row["Result"]  # W, D, L (from home perspective)

            pred = self.predict_match(home, away)
            if pred is None:
                continue

            # Model's prediction
            probs = {"H": pred["p_home"], "D": pred["p_draw"], "A": pred["p_away"]}
            model_pred = max(probs, key=probs.get)

            # Convert actual to H/D/A
            actual = {"W": "H", "D": "D", "L": "A"}.get(actual_result, "D")

            is_correct = model_pred == actual
            if is_correct:
                correct += 1
            total += 1

            predictions.append({
                "home": home, "away": away,
                "predicted": model_pred, "actual": actual,
                "correct": is_correct,
                "p_home": pred["p_home"],
                "p_draw": pred["p_draw"],
                "p_away": pred["p_away"],
                "confidence": max(probs.values()),
            })

        accuracy = correct / total * 100 if total > 0 else 0

        return {
            "accuracy": round(accuracy, 1),
            "correct": correct,
            "total": total,
            "predictions": predictions,
        }

    def get_team_ratings(self) -> list[dict]:
        """Return team ratings sorted by overall attack strength."""
        if not self._fitted:
            return []

        ratings = []
        for team, s in self._team_stats.items():
            overall_attack = (s["home_attack"] + s["away_attack"]) / 2
            overall_defense = (s["home_defense"] + s["away_defense"]) / 2
            ratings.append({
                "team": team,
                "home_attack": round(s["home_attack"], 3),
                "home_defense": round(s["home_defense"], 3),
                "away_attack": round(s["away_attack"], 3),
                "away_defense": round(s["away_defense"], 3),
                "overall_attack": round(overall_attack, 3),
                "overall_defense": round(overall_defense, 3),
                "home_matches": s["home_matches"],
                "away_matches": s["away_matches"],
                "rating": round(overall_attack / max(overall_defense, 0.01), 3),
            })

        return sorted(ratings, key=lambda x: x["rating"], reverse=True)
