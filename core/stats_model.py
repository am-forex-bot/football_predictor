"""Simple Poisson-based models for match statistics: corners, shots, cards.

Uses team-level home/away averages from historical data, then applies
Poisson distribution to calculate over/under probabilities for each stat.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import exp, factorial
from typing import Optional

import pandas as pd


@dataclass
class StatLine:
    """A single stat prediction with over/under probabilities."""
    name: str           # e.g. "Total Corners"
    expected: float     # Expected value (lambda for Poisson)
    over_85: float      # P(> 8.5)  — typical corners line
    over_95: float
    over_105: float
    over_115: float


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return exp(-lam) * (lam ** k) / factorial(k)


def _p_over(line: float, lam: float, max_val: int = 30) -> float:
    """P(X > line) where X ~ Poisson(lam)."""
    threshold = int(line)  # e.g. 8.5 → P(X >= 9)
    p_under = sum(_poisson_pmf(k, lam) for k in range(threshold + 1))
    return 1.0 - p_under


def _fair_odds(prob: float) -> Optional[float]:
    """Convert probability to fair decimal odds."""
    if prob <= 0:
        return None
    return round(1.0 / prob, 2)


class StatsModel:
    """Predict match statistics (corners, shots, cards) using team averages + Poisson."""

    def __init__(self, min_matches: int = 3):
        self._min_matches = min_matches
        self._team_stats: dict[str, dict] = {}
        self._league_avgs: dict[str, float] = {}

    def fit(self, results_df: pd.DataFrame) -> None:
        """Calculate per-team home/away averages for available stats."""
        self._team_stats.clear()
        self._league_avgs.clear()

        # Stat columns: (results_col_home, results_col_away, stat_key)
        stat_defs = [
            ("Home_Corners", "Away_Corners", "corners"),
            ("Home_Shots", "Away_Shots", "shots"),
            ("Home_SOT", "Away_SOT", "sot"),
            ("Home_Yellows", "Away_Yellows", "yellows"),
        ]

        # Check which stats are actually available
        available = []
        for h_col, a_col, key in stat_defs:
            if h_col in results_df.columns and results_df[h_col].notna().sum() > 0:
                available.append((h_col, a_col, key))

        if not available:
            return

        for _, row in results_df.iterrows():
            home = row.get("Team", "")
            away = row.get("Opponent", "")
            if not home or not away:
                continue

            for team in (home, away):
                if team not in self._team_stats:
                    self._team_stats[team] = {}

            for h_col, a_col, key in available:
                h_val = row.get(h_col)
                a_val = row.get(a_col)
                if pd.isna(h_val) or pd.isna(a_val):
                    continue

                h_val = float(h_val)
                a_val = float(a_val)

                # Home team's home stats
                ts = self._team_stats[home]
                ts.setdefault(f"{key}_home_for", []).append(h_val)
                ts.setdefault(f"{key}_home_against", []).append(a_val)

                # Away team's away stats
                ts_a = self._team_stats[away]
                ts_a.setdefault(f"{key}_away_for", []).append(a_val)
                ts_a.setdefault(f"{key}_away_against", []).append(h_val)

        # League averages
        for h_col, a_col, key in available:
            h_vals = results_df[h_col].dropna()
            a_vals = results_df[a_col].dropna()
            if len(h_vals) > 0:
                self._league_avgs[f"{key}_home"] = h_vals.mean()
                self._league_avgs[f"{key}_away"] = a_vals.mean()

    def predict_match(self, home_team: str, away_team: str) -> Optional[dict]:
        """Predict stat lines for a match.

        Returns dict with predictions for each available stat, or None if
        insufficient data for both teams.
        """
        h_stats = self._team_stats.get(home_team)
        a_stats = self._team_stats.get(away_team)
        if not h_stats or not a_stats:
            return None

        result = {
            "home_team": home_team,
            "away_team": away_team,
        }

        for key, label, lines in [
            ("corners", "Corners", [8.5, 9.5, 10.5, 11.5]),
            ("shots", "Shots", [20.5, 22.5, 24.5, 26.5]),
            ("sot", "Shots on Target", [7.5, 8.5, 9.5, 10.5]),
            ("yellows", "Cards", [2.5, 3.5, 4.5, 5.5]),
        ]:
            home_avg_key = f"{key}_home"
            away_avg_key = f"{key}_away"

            if home_avg_key not in self._league_avgs:
                continue

            league_home = self._league_avgs[home_avg_key]
            league_away = self._league_avgs[away_avg_key]

            # Home team's home attacking strength for this stat
            h_for = h_stats.get(f"{key}_home_for", [])
            a_for = a_stats.get(f"{key}_away_for", [])

            if len(h_for) < self._min_matches or len(a_for) < self._min_matches:
                continue

            h_for_avg = sum(h_for) / len(h_for)
            a_for_avg = sum(a_for) / len(a_for)

            # Expected: team's average adjusted by league context
            # Home team stat = their home avg
            # Away team stat = their away avg
            home_expected = h_for_avg
            away_expected = a_for_avg
            total_expected = home_expected + away_expected

            # Over/under probabilities for total
            probs = {}
            for line in lines:
                p_over = _p_over(line, total_expected)
                probs[f"over_{line}"] = round(p_over, 4)
                probs[f"under_{line}"] = round(1 - p_over, 4)

            # Home/away individual over/under at midpoint line
            mid_line = lines[1]  # Second line as mid
            home_mid = round(mid_line * home_expected / total_expected, 1) if total_expected > 0 else mid_line / 2
            away_mid = round(mid_line * away_expected / total_expected, 1) if total_expected > 0 else mid_line / 2

            result[key] = {
                "label": label,
                "home_expected": round(home_expected, 1),
                "away_expected": round(away_expected, 1),
                "total_expected": round(total_expected, 1),
                "lines": probs,
                "home_lines": {
                    f"home_over_{home_mid}": round(_p_over(home_mid, home_expected), 4),
                    f"home_under_{home_mid}": round(1 - _p_over(home_mid, home_expected), 4),
                },
                "away_lines": {
                    f"away_over_{away_mid}": round(_p_over(away_mid, away_expected), 4),
                    f"away_under_{away_mid}": round(1 - _p_over(away_mid, away_expected), 4),
                },
            }

        return result if len(result) > 2 else None
