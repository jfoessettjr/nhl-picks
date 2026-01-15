# NHL Picks (Top 3) — Flask + Free NHL API + Elo

A free, deployable NHL game predictor that returns the **Top 3 most confident winners** for a selected date.

## What you get
- ✅ Flask web app (mobile-friendly)
- ✅ Date picker (defaults to today)
- ✅ Elo model with:
  - Home-ice advantage
  - Margin of Victory (MOV) multiplier
  - Season ramp K-factor (higher early season, lower later)
- ✅ SQLite storage for team info + rating snapshots

## Repo structure
```
nhl-picks/
  app.py
  db.py
  elo.py
  nhl_api.py
  requirements.txt
  Procfile
  runtime.txt
  templates/
    index.html
  static/
    style.css
```

## Elo model (math)

### Win probability
Let:
- `R_home` = home team rating
- `R_away` = away team rating
- `H` = home-ice advantage (rating points; default 55)
- `R_home_adj = R_home + H`

Expected home win probability:
```
E_home = 1 / (1 + 10^((R_away - R_home_adj)/400))
E_away = 1 - E_home
```

### Outcome
Use `S_home`:
- `S_home = 1` if home wins
- `S_home = 0` if home loses  
(Overtime/shootout still counts as win/loss; you can refine later.)

### Margin of Victory (MOV) multiplier
Let `gd = abs(home_goals - away_goals)` and `rdiff = abs(R_home_adj - R_away)`.

A common, stable multiplier:
```
mov_mult = ln(gd + 1) * (2.2 / (0.001*rdiff + 2.2))
```

Notes:
- Larger goal differential → larger updates
- Bigger rating mismatch → smaller updates (prevents runaway)

### Rating update
Let `K` be the K-factor for that game date (see next section).

```
delta = K * mov_mult * (S_home - E_home)

R_home_new = R_home + delta
R_away_new = R_away - delta
```

### Season ramp K-factor (simple version)
Higher in early season, lower later. Default:
- Oct–Nov: K=28
- Dec: K=24
- Jan–Feb: K=20
- Mar–Apr: K=18
- Playoffs (optional): K=16

You can change the mapping in `elo.py`.

## Run locally (Codespaces)
```bash
pip install -r requirements.txt
python app.py
```

Visit: `http://127.0.0.1:5000`

## Deploy (free)
- Render / Fly.io / Railway free tiers can run this.
- Uses `Procfile` and `runtime.txt` as helpful defaults.

## Next upgrades (optional)
- Back-to-back fatigue adjustment
- Goalie confirmed vs projected
- True neutral site handling (rare in NHL regular season)
- More persistent caching of per-date builds
