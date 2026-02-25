"""Generate a clean, readable HTML report from backtest results.

Translates the wall of numbers into plain English with colour-coded tables.
Designed to be opened in a browser or saved as a standalone file.
"""

from __future__ import annotations
from datetime import datetime
from typing import Optional

import pandas as pd

from core.predictor import MatchPredictor, PredictorConfig
from core.leagues import season_display


def _css() -> str:
    return """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
           background: #0f0f14; color: #e0e0e0; padding: 32px; max-width: 960px; margin: 0 auto; }
    h1 { color: #cba6f7; margin-bottom: 4px; font-size: 1.6em; }
    h2 { color: #89b4fa; margin: 28px 0 12px 0; font-size: 1.2em;
         border-bottom: 1px solid #333; padding-bottom: 6px; }
    h3 { color: #a6adc8; margin: 16px 0 8px 0; font-size: 1.05em; }
    .subtitle { color: #888; margin-bottom: 20px; font-size: 0.9em; }
    .card { background: #1a1a24; border-radius: 8px; padding: 16px 20px;
            margin: 12px 0; border-left: 3px solid #444; }
    .card.good { border-left-color: #22c55e; }
    .card.warn { border-left-color: #f59e0b; }
    .card.bad { border-left-color: #ef4444; }
    .card.info { border-left-color: #89b4fa; }
    .card.hero { border-left-color: #cba6f7; background: #1f1a2e; }
    .card p { margin: 4px 0; line-height: 1.5; }
    .label { color: #888; font-size: 0.85em; }
    .big { font-size: 1.3em; font-weight: 600; }
    .green { color: #22c55e; }
    .red { color: #ef4444; }
    .amber { color: #f59e0b; }
    .purple { color: #cba6f7; }
    table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 0.88em; }
    th { background: #22222e; color: #a6adc8; padding: 8px 10px; text-align: left;
         font-weight: 600; font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.5px; }
    td { padding: 6px 10px; border-bottom: 1px solid #2a2a36; }
    tr:hover { background: #1e1e2e; }
    .r { text-align: right; }
    .c { text-align: center; }
    .profitable { color: #22c55e; font-weight: 600; }
    .losing { color: #ef4444; }
    .neutral { color: #888; }
    .tick { color: #22c55e; }
    .cross { color: #ef4444; }
    .prediction-row { background: #1a1a24; }
    .prediction-row:nth-child(even) { background: #1e1e28; }
    .pred-home { color: #22c55e; }
    .pred-away { color: #89b4fa; }
    .pred-draw { color: #f59e0b; }
    .footer { color: #555; font-size: 0.8em; margin-top: 32px; padding-top: 12px;
              border-top: 1px solid #2a2a36; }
    .rec-box { display: inline-block; background: #2a1a3a; padding: 6px 14px;
               border-radius: 6px; margin: 4px 0; font-weight: 600; color: #cba6f7; }
    """


def generate_report(
    backtest_result: dict,
    predictor: MatchPredictor,
    league_name: str = "Premier League",
    results_df: Optional[pd.DataFrame] = None,
    fixtures_df: Optional[pd.DataFrame] = None,
    table_df: Optional[pd.DataFrame] = None,
) -> str:
    """Generate a complete HTML report from backtest results.

    backtest_result: output from backtest_multi_season() or backtest()
    predictor: the MatchPredictor instance used (carries the config/weights)
    results_df/fixtures_df/table_df: current season data for predictions
    """
    is_multi = backtest_result.get("_multi_season", False)
    seasons = backtest_result.get("seasons", [])
    n_seasons = len(seasons) if seasons else 1
    best_t, best_lb, best_acc = backtest_result["best"]
    best_roi = backtest_result.get("best_roi", (0, 0, -999))
    config = predictor.config

    lines = [f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{league_name} — Backtest Report</title>
<style>{_css()}</style></head><body>
<h1>📊 {league_name} — Backtest Report</h1>
<p class="subtitle">Generated {datetime.now().strftime('%d %b %Y %H:%M')} · 
{n_seasons} season{"s" if n_seasons > 1 else ""} · Default weights</p>
"""]

    # ════════════════════════════════════════════════════════════════
    # 1. RECOMMENDATION
    # ════════════════════════════════════════════════════════════════
    lines.append('<h2>🎯 Recommended Settings</h2>')

    if is_multi:
        wf = predictor.walk_forward_analysis(backtest_result)
        if "recommendations" in wf:
            rec_acc = wf["recommendations"]["accuracy"]
            rec_roi = wf["recommendations"]["roi"]
            rt, rlb = rec_acc["combo"]

            lines.append(f"""
<div class="card hero">
<p class="label">Walk-forward analysis picked this combo — trained on past seasons,
tested out-of-sample on seasons it hadn't seen:</p>
<p><span class="rec-box">Threshold = {rt} &nbsp;·&nbsp; Lookback = {rlb}</span></p>
<p>Trained on: {' + '.join(rec_acc['train_seasons'])}</p>
<p>Training accuracy: {rec_acc['train_value']:.1f}%</p>
</div>""")

            lines.append("""
<div class="card info">
<p><strong>What these numbers mean:</strong></p>
<p><strong>Threshold</strong> = how big the score difference needs to be before predicting
a home/away win (instead of a draw). Lower = more decisive predictions, higher = more draws.</p>
<p><strong>Lookback</strong> = how many recent home/away matches to look at for each team's form.</p>
</div>""")
        else:
            rt, rlb = best_t, best_lb
            lines.append(f"""
<div class="card hero">
<p><span class="rec-box">Threshold = {rt} &nbsp;·&nbsp; Lookback = {rlb}</span></p>
<p>Best accuracy across all seasons: {best_acc:.1f}%</p>
</div>""")
    else:
        rt, rlb = best_t, best_lb
        roi_t, roi_lb, roi_pct = best_roi

        # Get bets count for each
        acc_roi_data = backtest_result.get("roi_stats", {}).get(rt, {}).get(rlb, {})
        roi_roi_data = backtest_result.get("roi_stats", {}).get(roi_t, {}).get(roi_lb, {})
        acc_bets = acc_roi_data.get("stakes", 0)
        acc_roi_pct = acc_roi_data.get("roi_pct", 0)
        roi_bets = roi_roi_data.get("stakes", 0)
        roi_acc = backtest_result.get("accuracy", {}).get(roi_t, {}).get(roi_lb, 0)

        lines.append(f"""
<div class="card hero">
<p class="label">Best combos this season:</p>
<p><strong>Best Accuracy:</strong>
<span class="rec-box">T = {rt} &nbsp;·&nbsp; LB = {rlb}</span>
&nbsp; {best_acc:.1f}% accurate &nbsp;·&nbsp; {acc_roi_pct:+.1f}% ROI &nbsp;·&nbsp; {acc_bets} bets</p>
<p><strong>Best ROI:</strong>
<span class="rec-box">T = {roi_t} &nbsp;·&nbsp; LB = {roi_lb}</span>
&nbsp; {roi_acc:.1f}% accurate &nbsp;·&nbsp; {roi_pct:+.1f}% ROI &nbsp;·&nbsp; {roi_bets} bets</p>
</div>

<div class="card info">
<p><strong>Which should I use?</strong></p>
<p><strong>Best Accuracy</strong> = more correct predictions overall. Better for accumulators where every leg matters.</p>
<p><strong>Best ROI</strong> = more profit per £ staked. The wins pay better even if there are fewer of them. Better for singles/doubles.</p>
<p><strong>Threshold</strong> = how big the score difference needs to be before predicting
a home/away win (instead of a draw). Lower = more decisive predictions, higher = more draws.</p>
<p><strong>Lookback</strong> = how many recent home/away matches to look at for each team's form.</p>
</div>""")

    # ════════════════════════════════════════════════════════════════
    # 2. WHICH FOLD SIZES ACTUALLY MAKE MONEY?
    # ════════════════════════════════════════════════════════════════
    lines.append('<h2>💰 Which Bet Types Make Money?</h2>')
    lines.append("""<div class="card info">
<p><strong>How to read this:</strong> "Singles" = individual bets on each match.
"Doubles" = pairs of matches that both need to win. "Trebles" = groups of 3, etc.
Higher folds = bigger payouts but much harder to hit.</p>
</div>""")

    strat = (predictor.betting_strategy_multi(backtest_result, rt, rlb)
             if is_multi else
             predictor.betting_strategy_analysis(
                 results_df, table_df, rt, rlb,
                 backtest_result=backtest_result))

    fs = strat.get("fold_summary", {})
    if fs:
        lines.append("""<table>
<tr><th>Bet Type</th><th class="r">Total Bets</th><th class="r">Staked</th>
<th class="r">Returned</th><th class="r">P&L</th><th class="r">ROI</th>
<th class="r">Best Hit</th><th class="c">Verdict</th></tr>""")

        for k in sorted(fs.keys()):
            f = fs[k]
            profit = f["profit"]
            roi = f["roi_pct"]
            cls = "profitable" if profit > 0 else "losing"
            if profit > 0:
                verdict = '<span class="tick">✓ Profitable</span>'
            elif roi > -20:
                verdict = '<span class="amber">⚠ Marginal</span>'
            else:
                verdict = '<span class="cross">✗ Losing</span>'

            lines.append(f"""<tr>
<td><strong>{f['name']}</strong></td>
<td class="r">{f['total_lines']:,}</td>
<td class="r">£{f['staked']:,.0f}</td>
<td class="r">£{f['returned']:,.0f}</td>
<td class="r {cls}">£{profit:+,.0f}</td>
<td class="r {cls}">{roi:+.1f}%</td>
<td class="r">£{f['best_payout']:,.0f}</td>
<td class="c">{verdict}</td></tr>""")

        lines.append("</table>")

    # Summary card
    profitable_folds = [k for k in sorted(fs.keys()) if fs[k]["profit"] > 0]
    if profitable_folds:
        names = [fs[k]["name"] for k in profitable_folds]
        best_fold = max(profitable_folds, key=lambda k: fs[k]["roi_pct"])
        bf = fs[best_fold]
        lines.append(f"""
<div class="card good">
<p><strong>Bottom line:</strong> {', '.join(names)} are profitable over {n_seasons} seasons at these settings.</p>
<p>Best ROI: <strong>{bf['name']}</strong> at {bf['roi_pct']:+.1f}% 
(£{bf['profit']:+,.0f} profit on £{bf['staked']:,.0f} staked)</p>
</div>""")
    else:
        lines.append("""<div class="card bad">
<p><strong>No fold sizes are profitable at this combo.</strong> Try different settings or use the weight tuner.</p>
</div>""")

    # ════════════════════════════════════════════════════════════════
    # 3. SEASON-BY-SEASON CONSISTENCY
    # ════════════════════════════════════════════════════════════════
    if is_multi and len(seasons) > 1:
        lines.append('<h2>📅 Season-by-Season Consistency</h2>')
        lines.append("""<div class="card info">
<p>The key question: does this work <em>consistently</em>, or did one freak season
make everything look good? Green = profit, red = loss.</p>
</div>""")

        # Do trebles per-season (the sweet spot)
        for fold_name, fold_k in [("Singles", 1), ("Doubles", 2), ("Trebles", 3), ("4-Folds", 4)]:
            lines.append(f'<h3>{fold_name}</h3>')
            lines.append("""<table>
<tr><th>Season</th><th class="r">Staked</th><th class="r">Returned</th>
<th class="r">P&L</th><th class="r">ROI</th><th class="c">Result</th></tr>""")

            total_p = 0
            n_profitable = 0
            for s in seasons:
                sc = backtest_result["_per_season"][s]
                s_strat = predictor.betting_strategy_analysis(
                    sc["results_df"], sc["table_df"], rt, rlb,
                    backtest_result=sc["bt"])
                fd = s_strat["fold_summary"].get(fold_k, {})
                if not fd:
                    continue
                p = fd.get("profit", 0)
                r = fd.get("roi_pct", 0)
                total_p += p
                cls = "profitable" if p > 0 else "losing"
                icon = '<span class="tick">✓</span>' if p > 0 else '<span class="cross">✗</span>'
                if p > 0:
                    n_profitable += 1

                lines.append(f"""<tr>
<td>{season_display(s)}</td>
<td class="r">£{fd['staked']:,.0f}</td>
<td class="r">£{fd['returned']:,.0f}</td>
<td class="r {cls}">£{p:+,.0f}</td>
<td class="r {cls}">{r:+.1f}%</td>
<td class="c">{icon}</td></tr>""")

            cls = "profitable" if total_p > 0 else "losing"
            lines.append(f"""<tr style="border-top: 2px solid #444; font-weight: 600;">
<td>TOTAL</td><td></td><td></td>
<td class="r {cls}">£{total_p:+,.0f}</td><td></td>
<td class="c">{n_profitable}/{len(seasons)} seasons</td></tr></table>""")

    # ════════════════════════════════════════════════════════════════
    # 4. WALK-FORWARD DETAIL
    # ════════════════════════════════════════════════════════════════
    if is_multi and "recommendations" in (wf if 'wf' in dir() else {}):
        lines.append('<h2>🔬 Walk-Forward Validation</h2>')
        lines.append("""<div class="card info">
<p><strong>How this works:</strong> For each test season, we train on earlier seasons to find
the "best" combo, then test it on the season it's never seen. This is the honest measure
of whether historical patterns actually predict the future.</p>
</div>""")

        summary = wf.get("summary", {})
        if summary:
            lines.append("""<table>
<tr><th>Training Window</th><th class="r">Avg OOS Accuracy</th>
<th class="r">Avg OOS ROI</th><th class="r">Tests</th><th>Most Picked Combo</th></tr>""")

            best_ws = wf.get("best_ws_acc", 1)
            for ws in sorted(summary.keys()):
                s = summary[ws]
                top = s["combo_frequency"][0] if s["combo_frequency"] else None
                combo_str = f"T={top[0][0]} LB={top[0][1]}" if top else "N/A"
                freq = f"({top[1]}/{s['n_tests']})" if top else ""
                marker = " ⭐" if ws == best_ws else ""
                acc_cls = "profitable" if s["avg_test_acc"] > 42 else "neutral"
                roi_cls = "profitable" if s["avg_test_roi"] > 0 else "losing"

                label = f"{ws} season{'s' if ws > 1 else ''}"
                lines.append(f"""<tr>
<td>{label}{marker}</td>
<td class="r {acc_cls}">{s['avg_test_acc']:.1f}%</td>
<td class="r {roi_cls}">{s['avg_test_roi']:+.1f}%</td>
<td class="r">{s['n_tests']}</td>
<td>{combo_str} {freq}</td></tr>""")

            lines.append("</table>")

    # ════════════════════════════════════════════════════════════════
    # 5. NEXT FIXTURES
    # ════════════════════════════════════════════════════════════════
    if fixtures_df is not None and not fixtures_df.empty and results_df is not None:
        lines.append('<h2>⚽ Next Fixtures Predictions</h2>')
        lines.append(f"""<div class="card info">
<p>Using Threshold={rt}, Lookback={rlb} with current season data.</p>
</div>""")

        cfg = PredictorConfig(
            lookback=rlb, threshold=rt,
            win_weights=config.win_weights,
            draw_weights=config.draw_weights,
            loss_close_weights=config.loss_close_weights,
            loss_heavy_penalty=config.loss_heavy_penalty,
            heavy_loss_gd=config.heavy_loss_gd,
            big_win_bonus=config.big_win_bonus,
            big_win_gd=config.big_win_gd,
        )
        pred = MatchPredictor(cfg)
        preds = pred.predict_fixtures(results_df, table_df, fixtures_df)

        if preds:
            lines.append("""<table>
<tr><th>Home</th><th class="c">Cat</th><th>Away</th><th class="c">Cat</th>
<th>Prediction</th><th class="r">Odds</th><th class="r">Implied %</th>
<th class="r">Score Diff</th></tr>""")

            acca_odds = 1.0
            acca_legs = 0
            for p in preds:
                pt = p["prediction"]
                if "Win" in pt and pt.startswith(p["home_team"]):
                    cls = "pred-home"
                elif "Win" in pt:
                    cls = "pred-away"
                elif pt == "Draw":
                    cls = "pred-draw"
                else:
                    cls = "neutral"

                odds_str = f'{p["pred_odds"]:.2f}' if p.get("pred_odds") else "-"
                impl_str = f'{p["implied_prob"]:.0f}%' if p.get("implied_prob") else "-"

                if p.get("pred_odds") and "No Bet" not in pt:
                    acca_odds *= p["pred_odds"]
                    acca_legs += 1

                lines.append(f"""<tr class="prediction-row">
<td><strong>{p['home_team']}</strong></td>
<td class="c">{p.get('home_cat','')}</td>
<td><strong>{p['away_team']}</strong></td>
<td class="c">{p.get('away_cat','')}</td>
<td class="{cls}"><strong>{pt}</strong></td>
<td class="r">{odds_str}</td>
<td class="r">{impl_str}</td>
<td class="r">{p['score_diff']:+.2f}</td></tr>""")

            lines.append("</table>")

            if acca_legs > 0:
                lines.append(f"""
<div class="card hero">
<p class="big">Full {acca_legs}-leg accumulator: {acca_odds:,.1f}/1</p>
<p>£1 returns £{acca_odds:,.2f} · £5 returns £{acca_odds * 5:,.2f} · 
£10 returns £{acca_odds * 10:,.2f}</p>
</div>""")

        else:
            lines.append('<div class="card warn"><p>No predictions — teams may not have enough matches yet.</p></div>')

    # ════════════════════════════════════════════════════════════════
    # 6. HOW TO ACTUALLY BET
    # ════════════════════════════════════════════════════════════════
    lines.append('<h2>🧠 How to Actually Use This</h2>')

    lines.append("""
<div class="card good">
<p><strong>The sensible strategy:</strong></p>
<p>1. Use the predictions for the next gameweek as your selection pool</p>
<p>2. Place <strong>trebles and 4-folds</strong> from those selections — these have the 
best balance of hit rate vs payout</p>
<p>3. Keep stakes small per line (£0.10–£0.50) — you're covering many combinations</p>
<p>4. Optionally add a full accumulator at pennies as a lottery ticket</p>
<p>5. <strong>Never chase losses.</strong> Bad weeks are normal. The edge plays out over months, not days.</p>
</div>

<div class="card warn">
<p><strong>Important caveats:</strong></p>
<p>• Past performance doesn't guarantee future results — this is a form model, not a crystal ball</p>
<p>• The system predicts the most likely outcome, not certain outcomes</p>
<p>• 45% accuracy sounds low but beats the ~33% you'd get from random guessing across 3 outcomes</p>
<p>• One great season in the backtest can make aggregate numbers look better than reality</p>
<p>• Always check the season-by-season consistency, not just the totals</p>
</div>""")

    # Footer
    lines.append(f"""
<p class="footer">Report generated by Football Predictor · 
{n_seasons} season{"s" if n_seasons > 1 else ""} of {league_name} data · 
T={rt} LB={rlb} · {datetime.now().strftime('%d %b %Y %H:%M')}</p>
</body></html>""")

    return "\n".join(lines)
