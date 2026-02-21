"""Prediction engine — faithful port of the V3 weight_up_score and
evaluation logic from the Match_prediction_testing notebooks."""

from collections import defaultdict

import pandas as pd


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def weight_up_score(team, opponent, venue, result, goals_for, goals_against,
                    goal_difference, opponent_position, home_odds, draw_odds,
                    away_odds):
    """Score a single match result based on venue and opponent strength.

    This is the V3 scoring system (latest) with separate brackets for
    position 1 and 2.
    """
    score = 0

    if opponent_position is None:
        return 0

    if result == "W":
        if venue == "Home":
            if opponent_position == 1:
                score += 7
            elif opponent_position == 2:
                score += 6
            elif 3 <= opponent_position <= 10:
                score += 5
            elif 11 <= opponent_position <= 16:
                score += 4
            elif 17 <= opponent_position <= 19:
                score += 3
            else:
                score += 1
        else:  # Away
            if opponent_position == 1:
                score += 8
            elif opponent_position == 2:
                score += 7
            elif 3 <= opponent_position <= 10:
                score += 6
            elif 11 <= opponent_position <= 16:
                score += 5
            elif 17 <= opponent_position <= 19:
                score += 4
            else:
                score += 2

    elif result == "D":
        if venue == "Home":
            if opponent_position == 1:
                score += 5
            elif opponent_position == 2:
                score += 4
            elif 3 <= opponent_position <= 10:
                score += 3
            elif 11 <= opponent_position <= 16:
                score += 2
            elif 17 <= opponent_position <= 19:
                score += 1
            else:
                score += -1
        else:  # Away
            if opponent_position == 1:
                score += 6
            elif opponent_position == 2:
                score += 5
            elif 3 <= opponent_position <= 10:
                score += 4
            elif 11 <= opponent_position <= 16:
                score += 3
            elif 17 <= opponent_position <= 19:
                score += 2
            else:
                score += 0

    else:  # Loss
        if venue == "Home":
            if opponent_position == 1:
                score += 1 if goal_difference > -2 else 0
            elif opponent_position == 2:
                score += 0 if goal_difference > -2 else -1
            elif 3 <= opponent_position <= 10:
                score += -1 if goal_difference > -2 else -2
            elif 11 <= opponent_position <= 16:
                score += -2 if goal_difference > -2 else -3
            elif 17 <= opponent_position <= 19:
                score += -3 if goal_difference > -2 else -4
            else:
                score += -5 if goal_difference > -2 else -6
        else:  # Away
            if opponent_position == 1:
                score += 2 if goal_difference > -2 else 1
            elif opponent_position == 2:
                score += 1 if goal_difference > -2 else 0
            elif 3 <= opponent_position <= 10:
                score += 0 if goal_difference > -2 else -1
            elif 11 <= opponent_position <= 16:
                score += -1 if goal_difference > -2 else -2
            elif 17 <= opponent_position <= 19:
                score += -2 if goal_difference > -2 else -3
            else:
                score += -4 if goal_difference > -2 else -5

    return score


# ---------------------------------------------------------------------------
# Match tuple helpers
# ---------------------------------------------------------------------------

def _build_match_dicts(results_df: pd.DataFrame, league_positions: dict):
    """Build home and away match tuple dicts from the clean Results sheet.

    Each tuple: (team, opponent, venue, result, gf, ga, gd,
                 opponent_position, home_odds, draw_odds, away_odds)
    """
    team_home_matches: dict[str, list[tuple]] = {}
    team_away_matches: dict[str, list[tuple]] = {}

    for _, row in results_df.iterrows():
        team = row["Team"]
        opponent = row["Opponent"]
        result = row["Result"]
        gf = row["GF"] if pd.notna(row["GF"]) else 0
        ga = row["GA"] if pd.notna(row["GA"]) else 0
        gd = gf - ga
        opp_pos = league_positions.get(opponent)
        team_pos = league_positions.get(team)
        home_odds = row.get("Home_Odds", float("nan"))
        draw_odds = row.get("Draw_Odds", float("nan"))
        away_odds = row.get("Away_Odds", float("nan"))

        home_tuple = (team, opponent, "Home", result, gf, ga, gd,
                      opp_pos, home_odds, draw_odds, away_odds)

        if team not in team_home_matches:
            team_home_matches[team] = []
        team_home_matches[team].append(home_tuple)

        # Away side: flip result and goals
        away_result = "L" if result == "W" else "W" if result == "L" else "D"
        away_tuple = (opponent, team, "Away", away_result, ga, gf, ga - gf,
                      team_pos, home_odds, draw_odds, away_odds)

        if opponent not in team_away_matches:
            team_away_matches[opponent] = []
        team_away_matches[opponent].append(away_tuple)

    return team_home_matches, team_away_matches


# ---------------------------------------------------------------------------
# Fixture prediction
# ---------------------------------------------------------------------------

def predict_fixtures(results_df: pd.DataFrame, league_table_df: pd.DataFrame,
                     fixtures_df: pd.DataFrame, threshold: int = 3,
                     lookback: int = 5) -> list[dict]:
    """Predict outcomes for upcoming fixtures.

    Returns a list of dicts with keys:
        home_team, away_team, prediction, home_score, away_score,
        score_diff, home_odds, draw_odds, away_odds
    """
    league_positions = dict(zip(league_table_df["Team"], league_table_df["Position"]))
    home_matches, away_matches = _build_match_dicts(results_df, league_positions)

    predictions = []
    predicted_teams: set[str] = set()

    for _, fixture in fixtures_df.iterrows():
        home_team = fixture["Team"]
        away_team = fixture["Opponent"]

        # Prevent duplicate predictions for the same team
        if home_team in predicted_teams or away_team in predicted_teams:
            continue

        home_hist = home_matches.get(home_team, [])[-lookback:]
        away_hist = away_matches.get(away_team, [])[-lookback:]

        if len(home_hist) < lookback or len(away_hist) < lookback:
            continue

        home_score = sum(weight_up_score(*m) for m in home_hist)
        away_score = sum(weight_up_score(*m) for m in away_hist)
        diff = home_score - away_score

        if diff > threshold:
            prediction = f"{home_team} Win"
        elif diff < -threshold:
            prediction = f"{away_team} Win"
        else:
            prediction = "Draw"

        # Get odds from the fixture row if available
        h_odds = fixture.get("Home_Odds", float("nan"))
        d_odds = fixture.get("Draw_Odds", float("nan"))
        a_odds = fixture.get("Away_Odds", float("nan"))

        predictions.append({
            "home_team": home_team,
            "away_team": away_team,
            "prediction": prediction,
            "home_score": home_score,
            "away_score": away_score,
            "score_diff": diff,
            "home_odds": h_odds if pd.notna(h_odds) else None,
            "draw_odds": d_odds if pd.notna(d_odds) else None,
            "away_odds": a_odds if pd.notna(a_odds) else None,
        })
        predicted_teams.add(home_team)
        predicted_teams.add(away_team)

    return predictions


# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------

def backtest(results_df: pd.DataFrame, league_table_df: pd.DataFrame,
             threshold_min: int = 1, threshold_max: int = 10,
             lookback_min: int = 3, lookback_max: int = 10) -> dict:
    """Run historical backtest across a grid of thresholds and lookback windows.

    Returns:
        {
            "accuracy":    {threshold: {lookback: float%}},
            "draw_stats":  {threshold: {lookback: {"correct": int, "predicted": int}}},
            "odds_stats":  {threshold: {lookback: {"combined": float, "total": int, "avg": float}}},
            "best":        (threshold, lookback, accuracy%),
        }
    """
    league_positions = dict(zip(league_table_df["Team"], league_table_df["Position"]))
    home_matches, away_matches = _build_match_dicts(results_df, league_positions)

    accuracy = defaultdict(lambda: defaultdict(float))
    draw_stats = defaultdict(lambda: defaultdict(lambda: {"correct": 0, "predicted": 0}))
    odds_stats = defaultdict(lambda: defaultdict(lambda: {"combined": 0.0, "total": 0}))

    for threshold in range(threshold_min, threshold_max + 1):
        for lookback in range(lookback_min, lookback_max + 1):
            correct_count = 0
            total_count = 0

            for team, matches in home_matches.items():
                for g in range(lookback, len(matches)):
                    prev_home = matches[g - lookback:g]
                    actual_result = matches[g][3]
                    opponent = matches[g][1]

                    if opponent not in away_matches:
                        continue
                    opp_away = away_matches[opponent]
                    if len(opp_away) < g:
                        continue
                    prev_away = opp_away[g - lookback:g] if g <= len(opp_away) else opp_away[-lookback:]
                    if len(prev_away) < lookback:
                        continue

                    home_score = sum(weight_up_score(*m) for m in prev_home)
                    away_score = sum(weight_up_score(*m) for m in prev_away)

                    if home_score - away_score > threshold:
                        predicted = "W"
                    elif away_score - home_score > threshold:
                        predicted = "L"
                    else:
                        predicted = "D"
                        draw_stats[threshold][lookback]["predicted"] += 1
                        if actual_result == "D":
                            draw_stats[threshold][lookback]["correct"] += 1

                    is_correct = predicted == actual_result
                    total_count += 1
                    if is_correct:
                        correct_count += 1
                        # Track odds of correctly predicted matches
                        match_tuple = matches[g]
                        if predicted == "W":
                            odd = match_tuple[8]  # home_odds
                        elif predicted == "D":
                            odd = match_tuple[9]  # draw_odds
                        else:
                            odd = match_tuple[10]  # away_odds
                        if pd.notna(odd):
                            odds_stats[threshold][lookback]["combined"] += odd
                    odds_stats[threshold][lookback]["total"] += 1

            acc = (correct_count / total_count * 100) if total_count > 0 else 0.0
            accuracy[threshold][lookback] = acc

    # Find best combination
    best = (1, 3, 0.0)
    for t, lb_dict in accuracy.items():
        for lb, acc in lb_dict.items():
            if acc > best[2]:
                best = (t, lb, acc)

    # Compute average odds
    for t in odds_stats:
        for lb in odds_stats[t]:
            total = odds_stats[t][lb]["total"]
            if total > 0:
                odds_stats[t][lb]["avg"] = odds_stats[t][lb]["combined"] / total
            else:
                odds_stats[t][lb]["avg"] = 0.0

    return {
        "accuracy": dict(accuracy),
        "draw_stats": dict(draw_stats),
        "odds_stats": dict(odds_stats),
        "best": best,
    }
