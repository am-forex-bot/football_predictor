# Football Predictor GUI - Implementation Plan

## Overview

Convert the existing Jupyter notebook-based football prediction system into a polished PyQt6 desktop application with multi-league support, automatic data management, and a dark modern UI.

---

## Architecture

```
football_predictor/
├── main.py                      # Entry point
├── requirements.txt             # PyQt6, pandas, requests, openpyxl, beautifulsoup4
├── core/
│   ├── __init__.py
│   ├── leagues.py               # League/country definitions & URL configs
│   ├── downloader.py            # Downloads from football-data.co.uk + fbref.com
│   ├── cleaner.py               # Data transformation (CSV → clean Excel)
│   ├── predictor.py             # weight_up_score + prediction engine + backtester
│   └── data_manager.py          # File lifecycle, staleness tracking, cleanup
├── gui/
│   ├── __init__.py
│   ├── main_window.py           # Main window with tab navigation
│   ├── download_tab.py          # League selection & data download
│   ├── prediction_tab.py        # Predict upcoming fixtures
│   ├── backtest_tab.py          # Historical accuracy testing
│   └── styles.py                # Dark modern theme (QSS stylesheet)
└── data/                        # Working directory for downloaded/processed files
```

---

## Step 1: League Configuration (`core/leagues.py`)

Define all supported countries and leagues with their data source identifiers.

**Countries & Leagues:**

| Country | League | football-data.co.uk code | fbref comp ID | fbref slug |
|---------|--------|--------------------------|---------------|------------|
| England | Premier League | E0 | 9 | Premier-League-Stats |
| England | Championship | E1 | 10 | Championship-Stats |
| England | League One | E2 | 15 | League-One-Stats |
| England | League Two | E3 | 16 | League-Two-Stats |
| Germany | Bundesliga | D1 | 20 | Bundesliga-Stats |
| Germany | 2. Bundesliga | D2 | 33 | 2-Bundesliga-Stats |
| Spain | La Liga | SP1 | 12 | La-Liga-Stats |
| Spain | Segunda Division | SP2 | 17 | Segunda-Division-Stats |
| Italy | Serie A | I1 | 11 | Serie-A-Stats |
| Italy | Serie B | I2 | 18 | Serie-B-Stats |
| France | Ligue 1 | F1 | 13 | Ligue-1-Stats |
| France | Ligue 2 | F2 | 60 | Ligue-2-Stats |

**Season code**: Auto-detected from current date. Feb 2026 → season "2526" (Aug start).

**URL patterns:**
- Results CSV: `https://www.football-data.co.uk/mmz4281/{season}/{code}.csv`
- Fixtures CSV: `https://www.football-data.co.uk/fixtures.csv` (all leagues, filter by Div column)
- League table: Calculated from results data (no external dependency) OR scraped from fbref as fallback

**Bug fix from existing code**: The original Untitled.ipynb maps E0→Championship and E1→Premier League. This is backwards. E0 = Premier League, E1 = Championship. Will be fixed.

---

## Step 2: Data Downloader (`core/downloader.py`)

Handles all network requests to football-data.co.uk (and optionally fbref.com).

**Capabilities:**
1. **Download season results CSV** - Full season CSV with match results + odds
2. **Download fixtures** - From football-data.co.uk/fixtures.csv, filtered to the selected league's `Div` code
3. **Session management** - User-Agent rotation, retry with exponential backoff (matching existing anti-blocking pattern)
4. **Signals** - Emits Qt signals for progress updates (download started, progress %, completed, error)

**Key implementation details:**
- Uses `QThread` workers so downloads don't freeze the GUI
- Returns raw CSV text/DataFrame to the cleaner module
- Retry logic: up to 5 attempts with exponential backoff (2^attempt seconds)
- Random delay between requests (3-7s) when making multiple requests to same host

---

## Step 3: Data Cleaner (`core/cleaner.py`)

Transforms raw football-data.co.uk CSV data into the clean format used by the prediction engine.

**Input**: Raw CSV from football-data.co.uk with 120 columns.

**Column mapping** (from CSV column indices):
- 3: HomeTeam → "Team"
- 4: AwayTeam → "Opponent"
- 5: FTHG → "GF" (Goals For)
- 6: FTAG → "GA" (Goals Against)
- 7: FTR → "Result" (H→W, A→L, D stays as D)
- 24: B365H → "Home_Odds"
- 25: B365D → "Draw_Odds"
- 26: B365A → "Away_Odds"

**Output sheets in Excel workbook:**

1. **"Results" sheet** - Completed matches only (FTR is not NaN):
   | Team | Opponent | GF | GA | Result | Home_Odds | Draw_Odds | Away_Odds |

2. **"Fixtures" sheet** - Upcoming matches (FTR is NaN, teams exist):
   | Team | Opponent |

3. **"League Table" sheet** - Calculated from results:
   | Position | Team | P | W | D | L | GF | GA | GD | Pts |
   - Each CSV row generates 2 entries: one for HomeTeam, one for AwayTeam
   - Sorted by: Points desc → GD desc → GF desc
   - Position assigned 1 through N

**Append mode**: When re-downloading mid-season, only add new results (by Date comparison) rather than replacing everything. League table is always recalculated from full results.

---

## Step 4: Prediction Engine (`core/predictor.py`)

Port of the latest `weight_up_score` function from `Match_prediction_testing/Untitled.ipynb`.

### 4a. `weight_up_score(team, opponent, venue, result, goals_for, goals_against, goal_difference, opponent_position, home_odds, draw_odds, away_odds)`

Uses the V3 scoring system (most recent from the codebase):

**WIN scoring:**
| Venue | Opp Position | Score |
|-------|-------------|-------|
| Home | 1st | +7 |
| Home | 2nd | +6 |
| Home | 3-10 | +5 |
| Home | 11-16 | +4 |
| Home | 17-19 | +3 |
| Home | 20+ | +1 |
| Away | 1st | +8 |
| Away | 2nd | +7 |
| Away | 3-10 | +6 |
| Away | 11-16 | +5 |
| Away | 17-19 | +4 |
| Away | 20+ | +2 |

**DRAW scoring:**
| Venue | Opp Position | Score |
|-------|-------------|-------|
| Home | 1st | +5 |
| Home | 2nd | +4 |
| Home | 3-10 | +3 |
| Home | 11-16 | +2 |
| Home | 17-19 | +1 |
| Home | 20+ | -1 |
| Away | 1st | +6 |
| Away | 2nd | +5 |
| Away | 3-10 | +4 |
| Away | 11-16 | +3 |
| Away | 17-19 | +2 |
| Away | 20+ | 0 |

**LOSS scoring** (includes goal difference threshold at -2):
| Venue | Opp Position | GD > -2 | GD <= -2 |
|-------|-------------|---------|----------|
| Home | 1st | +1 | 0 |
| Home | 2nd | 0 | -1 |
| Home | 3-10 | -1 | -2 |
| Home | 11-16 | -2 | -3 |
| Home | 17-19 | -3 | -4 |
| Home | 20+ | -5 | -6 |
| Away | 1st | +2 | +1 |
| Away | 2nd | +1 | 0 |
| Away | 3-10 | 0 | -1 |
| Away | 11-16 | -1 | -2 |
| Away | 17-19 | -2 | -3 |
| Away | 20+ | -4 | -5 |

### 4b. `predict_fixtures(results_df, league_positions, fixtures_df, threshold, lookback)`

For each fixture (home_team vs away_team):
1. Get last N home matches for home_team
2. Get last N away matches for away_team
3. Sum weighted scores for each
4. If home_score - away_score > threshold → Home Win
5. If away_score - home_score > threshold → Away Win
6. Otherwise → Draw
7. Prevent duplicate team predictions (once a team appears, skip further fixtures with that team)

### 4c. `backtest(results_df, league_positions, threshold_range, lookback_range)`

Test all combinations of thresholds (1-10) and lookback windows (3-10+).
Returns accuracy matrix, draw stats, and combined odds data.
Same logic as `evaluate_predictions()` from existing code.

---

## Step 5: Data Manager (`core/data_manager.py`)

Manages the lifecycle of downloaded data files.

**Responsibilities:**
1. **Track downloads** - JSON metadata file recording: league, download timestamp, file paths
2. **Staleness detection** - Flag data older than 7 days as stale
3. **Cleanup** - Delete stale Excel files, clear data directory
4. **Available data** - List which leagues have current data ready for prediction
5. **Append support** - Detect existing data and enable incremental update mode

**Cleanup workflow** (triggered after predictions/bets):
- "Clean All" → wipes entire data/ directory
- "Clean Stale" → removes files older than configured threshold
- League table files always replaced on re-download (positions change weekly)
- Results/fixtures can be appended to

---

## Step 6: GUI Main Window (`gui/main_window.py`)

**Layout:**
- Fixed-size or resizable window (~1000x700)
- Tab bar at top: **Download** | **Predict** | **Backtest**
- Status bar at bottom with last-action message
- Application icon and title: "Football Predictor"

---

## Step 7: Download Tab (`gui/download_tab.py`)

**Layout (top to bottom):**

1. **League Selection Group**
   - Country dropdown: England, Germany, Spain, Italy, France
   - League dropdown: Filtered by country (4 for England, 2 for others)
   - Season display: Auto-detected (e.g., "2025-26")

2. **Action Buttons (row)**
   - "Download Results & Fixtures" → downloads season CSV + fixtures CSV, processes both
   - "Download All" → downloads all leagues at once
   - Progress bar below buttons

3. **Log Panel**
   - Scrollable text area showing download progress, errors, success messages
   - Color-coded: green for success, red for errors, yellow for warnings

4. **Data Status Table**
   - Shows all leagues with: League name, Last downloaded, Results count, Fixtures count, Status (Fresh/Stale)
   - "Clean Up" button per row or "Clean All" button

---

## Step 8: Prediction Tab (`gui/prediction_tab.py`)

**Layout:**

1. **Configuration Group**
   - League dropdown (populated from downloaded data only)
   - Threshold spinner: 1-10 (default: 3)
   - Lookback spinner: 3-14 (default: 5)
   - "Run Predictions" button

2. **Predictions Table**
   - Columns: Home Team | Away Team | Prediction | Home Odds | Draw Odds | Away Odds | Score Diff
   - Color-coded rows: green for Home Win, blue for Away Win, grey for Draw
   - Sortable columns

3. **Summary Panel**
   - Total predictions made
   - Breakdown: X home wins, Y away wins, Z draws
   - Combined odds of all predicted outcomes

---

## Step 9: Backtest Tab (`gui/backtest_tab.py`)

**Layout:**

1. **Configuration Group**
   - League dropdown (from downloaded data)
   - Threshold range: min/max spinners (default 1-10)
   - Lookback range: min/max spinners (default 3-10)
   - "Run Backtest" button

2. **Accuracy Heatmap Table**
   - Rows: Threshold values (1-10)
   - Columns: Lookback values (3-10)
   - Cells: Accuracy % with color gradient (red→yellow→green)
   - Highlight best combination

3. **Detailed Stats Panel**
   - Draw prediction accuracy
   - Combined odds per threshold/lookback
   - Average odds per prediction window
   - Total predictions per combination

---

## Step 10: Dark Modern Theme (`gui/styles.py`)

QSS stylesheet for the entire application:

- **Background**: Dark grey (#1e1e2e)
- **Cards/panels**: Slightly lighter (#2a2a3a)
- **Accent**: Blue-purple (#7c3aed) for buttons, selections
- **Text**: Light grey (#e0e0e0), white for headers
- **Success**: Green (#22c55e)
- **Error**: Red (#ef4444)
- **Warning**: Amber (#f59e0b)
- **Tables**: Alternating row colors, hover highlight
- **Buttons**: Rounded, gradient, hover effects
- **Dropdowns**: Styled to match dark theme
- **Fonts**: System default sans-serif, slightly larger (11pt body, 14pt headers)

---

## Implementation Order

1. `core/leagues.py` - League config (no dependencies)
2. `core/downloader.py` - Network layer
3. `core/cleaner.py` - Data transformation
4. `core/predictor.py` - Prediction engine (port from notebooks)
5. `core/data_manager.py` - File management
6. `gui/styles.py` - Theme (standalone)
7. `gui/main_window.py` - Shell window
8. `gui/download_tab.py` - Download functionality
9. `gui/prediction_tab.py` - Prediction UI
10. `gui/backtest_tab.py` - Backtesting UI
11. `main.py` - Wire everything together
12. `requirements.txt` - Dependencies

---

## Dependencies

```
PyQt6>=6.6.0
pandas>=2.0.0
requests>=2.31.0
openpyxl>=3.1.0
beautifulsoup4>=4.12.0
```

---

## Known Issues to Fix from Existing Code

1. **E0/E1 swap bug** - Original code maps E0→Championship, E1→Premier League. Fixed: E0=Premier League, E1=Championship.
2. **Hardcoded Windows paths** - All `C:\Users\Mesto\...` paths replaced with relative `data/` directory.
3. **Position 20+ edge case** - Some leagues have 18 teams (Bundesliga), others 20+. The weight_up_score position brackets need to adapt to league size (20 for PL/Championship/Ligue 1, 18 for Bundesliga, etc.). Will use bottom-2 instead of hardcoded 20.
4. **Missing fixtures handling** - Original code requires manual Fixtures sheet. Now automated from football-data.co.uk fixtures.csv.
5. **Column index fragility** - Original code uses iloc[:, 3:8] and iloc[:, 24:27]. Will use column names (HomeTeam, AwayTeam, FTHG, FTAG, FTR, B365H, B365D, B365A) for robustness.
