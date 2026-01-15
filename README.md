# NHL Picks — GitHub Pages (today + next 7 days)

This repo deploys to **GitHub Pages** (static hosting).  
A **GitHub Action** runs daily to generate `docs/data/picks.json`, which the site reads.

## How to deploy on GitHub Pages
1. Push this repo to GitHub (branch: `main`)
2. In GitHub: **Settings → Pages**
3. Source: **Deploy from a branch**
4. Branch: `main`
5. Folder: `/docs`
6. Save — your site will be live at: `https://<user>.github.io/<repo>/`

## How it works
- `scripts/build_picks.py`:
  - rebuilds Elo ratings up through **yesterday**
  - computes picks for **today + next 7 days**
  - writes `docs/data/picks.json`
  - stores incremental state in `docs/data/state.json` (keeps API calls low)

- `docs/` is the static site:
  - `index.html`, `style.css`, `app.js`

## Run locally
```bash
pip install -r requirements.txt
python scripts/build_picks.py
# then open docs/index.html (or serve docs/ with any static server)
```

## Accuracy upgrades (enabled)
- **Opponent-adjusted form (last 10)** using **Elo residuals** (actual - expected) computed with pregame ratings.
- **Home/Away split form** when there are at least **5** games in that split.
- **Rest-based fatigue** (B2B and 1-rest penalties).
- **OT/SO down-weighting** in Elo updates.
- **MOV cap** (goal diff capped at 3).
- **Probability shrink** (reduces overconfidence; improves ranking stability).

Notes:
- Form/rest is derived during the same rebuild pass, avoiding extra API requests.

- **Recency-weighted opponent-adjusted form** (residual weights 0.1..1.0)
- **Team-specific home advantage** (learned per team, bounded 25–85)


## Goalie-aware adjustment

Uses free NHL endpoints to add a goalie factor:
- `gamecenter/{gameId}/boxscore` includes goalies with a `starter` flag (when available).
- Falls back to the goalie with the most games played for that team from `goalie-stats-leaders/current`.
- Converts season save% vs a baseline into an Elo-point adjustment (capped) and shows it in the "why" breakdown.


### Goalie recent-start upgrade
This version optionally replaces the season SV% proxy with **recent-start SV%** (last 5 starts, lookback up to 35 days). It caches boxscores in `docs/data/boxscore_cache.json` and limits new boxscore fetches per run.

- **Goalie workload penalty** (starter on B2B / 2-in-3 from cached recent starts)
- **Regulation-prob ranking** (rank picks by regulation win probability; display reg vs full)
