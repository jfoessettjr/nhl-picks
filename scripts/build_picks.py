from __future__ import annotations


import json
from datetime import date, datetime, timedelta
from pathlib import Path
from dateutil.tz import tzutc

from elo import EloConfig, expected_home, update_ratings
import nhl_api
from cache import load_json, save_json

CFG = EloConfig()

# ---------------------------
# Accuracy+ knobs
# ---------------------------

# Rest / fatigue (rating points)
FATIGUE_PENALTY_B2B = 15.0
FATIGUE_PENALTY_1REST = 5.0

# Form points clamp
FORM_POINTS_MAX = 40.0

# Opponent-adjusted form residual scaling
RESIDUAL_TO_POINTS = 150.0
GD_TO_POINTS = 6.0

# Recency weights for last-10 (oldest -> newest)
RECENCY_WEIGHTS = [0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0]

# Team-specific home advantage learning
H_HOME_BASE = 55.0
H_HOME_MIN = 25.0
H_HOME_MAX = 85.0
H_HOME_LEARN_RATE = 160.0   # points per unit residual
H_HOME_K = 18.0             # smoothing strength

# Goalie recent-start tuning
GOALIE_RECENT_STARTS = 5
GOALIE_LOOKBACK_DAYS = 35  # max days to search for recent starts
GOALIE_MAX_NEW_BOXSCORES_PER_RUN = 120

# Probability shrink
PROB_SHRINK = 0.85

# Rate-limit safety on first run
MAX_REBUILD_DAYS = 180

STATE_PATH = Path("docs/data/state.json")
BOX_CACHE_PATH = Path("docs/data/boxscore_cache.json")

PICKS_PATH = Path("docs/data/picks.json")

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

def prob_shrink(p: float) -> float:
    return 0.5 + (p - 0.5) * PROB_SHRINK

def season_from_date(d: date) -> str:
    if d.month >= 9:
        start_year = d.year
    else:
        start_year = d.year - 1
    return f"{start_year}{start_year+1}"

def season_start_guess(season: str) -> date:
    return date(int(season[:4]), 10, 1)

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"seasons": {}}

def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")

def s_home_from_outcome(home_won: bool, kind: str) -> float:
    if not home_won:
        if kind == "SO": return 1.0 - 0.75
        if kind == "OT": return 1.0 - 0.85
        return 0.0
    if kind == "SO": return 0.75
    if kind == "OT": return 0.85
    return 1.0

def get_team_home_adv(team_id: int, home_model: dict) -> float:
    s = home_model.get(str(team_id), {"res_sum": 0.0, "n": 0})
    res_sum = float(s.get("res_sum", 0.0))
    n = int(s.get("n", 0))
    avg = (res_sum / n) if n > 0 else 0.0
    strength = (n / (n + H_HOME_K)) if n > 0 else 0.0
    learned = H_HOME_BASE + (avg * H_HOME_LEARN_RATE) * strength
    return clamp(learned, H_HOME_MIN, H_HOME_MAX)

def update_home_model(team_id: int, residual_home: float, home_model: dict) -> None:
    s = home_model.get(str(team_id), {"res_sum": 0.0, "n": 0})
    s["res_sum"] = float(s.get("res_sum", 0.0)) + float(residual_home)
    s["n"] = int(s.get("n", 0)) + 1
    home_model[str(team_id)] = s

def rebuild_ratings_to(target: date, state: dict, session):
    season = season_from_date(target)
    seasons = state["seasons"]
    sstate = seasons.get(season)

    if not sstate:
        sstate = {"last_built": None, "ratings": {}, "home_model": {}}
        seasons[season] = sstate

    ratings = {int(k): float(v) for k, v in (sstate.get("ratings") or {}).items()}
    home_model = sstate.get("home_model") or {}

    if sstate.get("last_built"):
        start = date.fromisoformat(sstate["last_built"]) + timedelta(days=1)
    else:
        season_start = season_start_guess(season)
        start = max(season_start, target - timedelta(days=MAX_REBUILD_DAYS))

    if start > target:
        return ratings, "cached", {}, home_model

    log_start = target - timedelta(days=60)
    per_team_logs: dict[int, list[dict]] = {}

    updates = 0
    games = nhl_api.get_games_range_weekly(start, target, session=session)
    for g in games:
            if not nhl_api.is_final(g):
                continue
            basic = nhl_api.parse_game_basic(g)
            if not basic.get("date"):
                continue
            score = nhl_api.get_final_score(g)
            if not score:
                continue

            home_goals, away_goals = score
            gd = abs(home_goals - away_goals)
            if gd == 0:
                continue

            home_id = basic["home_team_id"]
            away_id = basic["away_team_id"]
            if home_id is None or away_id is None:
                continue

            if home_id not in ratings: ratings[home_id] = CFG.base_rating
            if away_id not in ratings: ratings[away_id] = CFG.base_rating

            r_home_pre = ratings[home_id]
            r_away_pre = ratings[away_id]

            # Team-specific home advantage for expectation + Elo update
            h_team = get_team_home_adv(home_id, home_model)
            cfg_game = EloConfig(base_rating=CFG.base_rating, home_ice_adv=h_team, scale=CFG.scale)

            e_home = expected_home(r_home_pre, r_away_pre, cfg_game)

            home_won = home_goals > away_goals
            kind = nhl_api.final_kind(g)
            s_home = s_home_from_outcome(home_won, kind)

            residual_home = s_home - e_home
            residual_away = -residual_home

            update_home_model(home_id, residual_home, home_model)

            game_day = date.fromisoformat(basic["date"])
            if game_day >= log_start:
                per_team_logs.setdefault(home_id, []).append({
                    "date": game_day.isoformat(),
                    "is_home": True,
                    "residual": float(residual_home),
                    "gd": int(home_goals - away_goals),
                })
                per_team_logs.setdefault(away_id, []).append({
                    "date": game_day.isoformat(),
                    "is_home": False,
                    "residual": float(residual_away),
                    "gd": int(away_goals - home_goals),
                })

            new_home, new_away, *_ = update_ratings(
                r_home_pre, r_away_pre, s_home, gd, game_day, cfg_game
            )
            ratings[home_id] = new_home
            ratings[away_id] = new_away
            updates += 1

    sstate["ratings"] = {str(k): float(v) for k, v in ratings.items()}
    sstate["last_built"] = target.isoformat()
    sstate["home_model"] = home_model
    save_state(state)

    return ratings, f"updated {updates} finals", per_team_logs, home_model

def weighted_avg(vals: list[float], weights: list[float]) -> float:
    if not vals:
        return 0.0
    w = weights[-len(vals):]
    num = sum(v * wi for v, wi in zip(vals, w))
    den = sum(wi for wi in w)
    return num / den if den else 0.0

def compute_form_and_rest(today: date, logs: dict[int, list[dict]]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for tid, games in logs.items():
        games_sorted = sorted(games, key=lambda x: x["date"])
        last10_all = games_sorted[-10:]
        if not last10_all:
            continue

        last_played = date.fromisoformat(last10_all[-1]["date"])
        rest_days = (today - last_played).days - 1

        res_all = [g["residual"] for g in last10_all]
        gd_all = [g["gd"] for g in last10_all]
        res_avg = weighted_avg(res_all, RECENCY_WEIGHTS)
        gd_avg = weighted_avg(gd_all, RECENCY_WEIGHTS)

        home_games = [g for g in last10_all if g["is_home"]]
        away_games = [g for g in last10_all if not g["is_home"]]

        def wavg_games(gs):
            if not gs:
                return (0.0, 0.0, 0)
            res = [g["residual"] for g in gs]
            gd = [g["gd"] for g in gs]
            w = RECENCY_WEIGHTS[-len(gs):]
            return (weighted_avg(res, w), weighted_avg(gd, w), len(gs))

        res_home, gd_home, n_home = wavg_games(home_games)
        res_away, gd_away, n_away = wavg_games(away_games)

        out[tid] = {
            "rest_days": int(rest_days),
            "all": {"n": len(last10_all), "res_avg": float(res_avg), "gd_avg": float(gd_avg)},
            "home": {"n": n_home, "res_avg": float(res_home), "gd_avg": float(gd_home)},
            "away": {"n": n_away, "res_avg": float(res_away), "gd_avg": float(gd_away)},
        }
    return out

def fatigue_points(rest_days: int | None) -> float:
    if rest_days is None:
        return 0.0
    if rest_days <= 0: return -FATIGUE_PENALTY_B2B
    if rest_days == 1: return -FATIGUE_PENALTY_1REST
    return 0.0

def form_points(form: dict | None, is_home: bool) -> float:
    if not form:
        return 0.0
    key = "home" if is_home else "away"
    split = form.get(key, {})
    overall = form.get("all", {})
    use_split = split.get("n", 0) >= 5

    res = split["res_avg"] if use_split else overall.get("res_avg", 0.0)
    gd = split["gd_avg"] if use_split else overall.get("gd_avg", 0.0)

    pts = (res * RESIDUAL_TO_POINTS) + (gd * GD_TO_POINTS)
    return clamp(pts, -FORM_POINTS_MAX, FORM_POINTS_MAX)

def why_breakdown_homeprob(r_home: float, r_away: float, form_h: float, form_a: float, fat_h: float, fat_a: float, h_team: float):
    cfg0 = EloConfig(base_rating=CFG.base_rating, home_ice_adv=0.0, scale=CFG.scale)
    cfgH = EloConfig(base_rating=CFG.base_rating, home_ice_adv=h_team, scale=CFG.scale)

    p_base = prob_shrink(expected_home(r_home, r_away, cfg0))
    p_homeice = prob_shrink(expected_home(r_home, r_away, cfgH))
    p_form = prob_shrink(expected_home(r_home + form_h, r_away + form_a, cfgH))
    p_final = prob_shrink(expected_home(r_home + form_h + fat_h, r_away + form_a + fat_a, cfgH))

    return {
        "base": p_base,
        "home_ice_pp": (p_homeice - p_base) * 100.0,
        "form_pp": (p_form - p_homeice) * 100.0,
        "fatigue_pp": (p_final - p_form) * 100.0,
        "final": p_final,
    }

def top3_for_date(day: date, ratings: dict[int,float], form: dict[int,dict], home_model: dict) -> list[dict]:
    games = nhl_api.get_schedule_for_date(day)
    picks: list[dict] = []
    for g in games:
        basic = nhl_api.parse_game_basic(g)
        home_id = basic["home_team_id"]
        away_id = basic["away_team_id"]
        if home_id is None or away_id is None:
            continue

        home_rt = float(ratings.get(home_id, CFG.base_rating))
        away_rt = float(ratings.get(away_id, CFG.base_rating))

        h_team = get_team_home_adv(home_id, home_model)
        cfg_game = EloConfig(base_rating=CFG.base_rating, home_ice_adv=h_team, scale=CFG.scale)

        fh = form.get(home_id)
        fa = form.get(away_id)

        form_home = form_points(fh, is_home=True)
        form_away = form_points(fa, is_home=False)

        fat_home = fatigue_points(fh["rest_days"]) if fh else 0.0
        fat_away = fatigue_points(fa["rest_days"]) if fa else 0.0

        p_home = prob_shrink(expected_home(home_rt + form_home + fat_home, away_rt + form_away + fat_away, cfg_game))
        p_away = 1.0 - p_home

        why_home = why_breakdown_homeprob(home_rt, away_rt, form_home, form_away, fat_home, fat_away, h_team)

        if p_home >= p_away:
            pick_name = basic["home_team_name"]
            win_prob = p_home
            why_pick = why_home
            factors = f"HomeAdv {h_team:.0f} + wOppAdj form {form_home:+.0f}/{form_away:+.0f} + Rest {fat_home:+.0f}/{fat_away:+.0f}"
        else:
            pick_name = basic["away_team_name"]
            win_prob = p_away
            why_pick = {
                "base": 1.0 - why_home["base"],
                "home_ice_pp": -why_home["home_ice_pp"],
                "form_pp": -why_home["form_pp"],
                "fatigue_pp": -why_home["fatigue_pp"],
                "final": 1.0 - why_home["final"],
            }
            factors = f"Road pick vs HomeAdv {h_team:.0f} + wOppAdj form {form_away:+.0f}/{form_home:+.0f} + Rest {fat_away:+.0f}/{fat_home:+.0f}"

        picks.append({
            "gamePk": basic["gamePk"],
            "home_name": basic["home_team_name"],
            "away_name": basic["away_team_name"],
            "home_elo": home_rt,
            "away_elo": away_rt,
            "pick_name": pick_name,
            "win_prob": win_prob,
            "factors": factors,
            "why": why_pick,
            "form_home": f"{form_home:+.0f}",
            "form_away": f"{form_away:+.0f}",
            "fat_home": f"{fat_home:+.0f}",
            "fat_away": f"{fat_away:+.0f}",
            "home_adv": float(h_team),
        })

    picks.sort(key=lambda x: x["win_prob"], reverse=True)
    return picks[:3]

def goalie_recent_sv(goalie_id: int, team_id: int, today: date, box_cache: dict, session) -> tuple[float|None, int, int]:
    """Return (sv%, starts_found, new_fetches_used).

    Uses cached boxscores and fetches as needed. We search backwards up to GOALIE_LOOKBACK_DAYS using the
    daily score feed to find games involving `team_id`, then inspect each game's boxscore to see if
    `goalie_id` started (or played >= ~30 minutes if starter flag is missing) and accumulate saves/shots.
    """
    starts = 0
    shots_total = 0
    saves_total = 0

    # Helper to fetch boxscore with cache + per-run cap
    def get_box(game_id: int):
        key = str(game_id)
        if key in box_cache:
            return box_cache[key]
        if box_cache.get("_new_fetches", 0) >= GOALIE_MAX_NEW_BOXSCORES_PER_RUN:
            return None
        try:
            box = nhl_api.get_boxscore(game_id, session=session)
            box_cache[key] = box
            box_cache["_new_fetches"] = box_cache.get("_new_fetches", 0) + 1
            return box
        except Exception:
            return None

    d = today - timedelta(days=1)
    earliest = today - timedelta(days=GOALIE_LOOKBACK_DAYS)

    while d >= earliest and starts < GOALIE_RECENT_STARTS:
        games = nhl_api.get_score_for_date(d)
        for g in games:
            basic = nhl_api.parse_game_basic(g)
            if basic.get("home_team_id") != team_id and basic.get("away_team_id") != team_id:
                continue

            game_id = basic.get("gamePk") or g.get("id") or g.get("gamePk")
            if game_id is None:
                continue
            try:
                game_id = int(game_id)
            except Exception:
                continue

            box = get_box(game_id)
            if not box:
                continue

            team_side = "homeTeam" if basic.get("home_team_id") == team_id else "awayTeam"

            try:
                goalies = box["playerByGameStats"][team_side]["goalies"]
            except Exception:
                continue

            # Find this goalie line
            for gl in goalies:
                pid = gl.get("playerId")
                if pid is None:
                    continue
                try:
                    pid = int(pid)
                except Exception:
                    continue
                if pid != goalie_id:
                    continue

                starter = gl.get("starter")
                toi = gl.get("toi") or gl.get("timeOnIce")  # "59:32"
                shots_against = gl.get("shotsAgainst") or gl.get("shots") or gl.get("shotsAgainstTotal")
                goals_against = gl.get("goalsAgainst") or gl.get("goals") or gl.get("goalsAgainstTotal")

                if shots_against is None or goals_against is None:
                    continue
                try:
                    sa = int(shots_against)
                    ga = int(goals_against)
                except Exception:
                    continue
                if sa <= 0:
                    continue

                # Only count starts
                if starter is False:
                    continue
                if starter is None and toi:
                    try:
                        mm, ss = str(toi).split(":")
                        minutes = int(mm) + int(ss) / 60.0
                        if minutes < 30.0:
                            continue
                    except Exception:
                        pass

                saves = sa - ga
                shots_total += sa
                saves_total += saves
                starts += 1
                break

            if starts >= GOALIE_RECENT_STARTS:
                break

        d -= timedelta(days=1)

    if starts == 0 or shots_total <= 0:
        return (None, starts, int(box_cache.get("_new_fetches", 0)))
    return (saves_total / shots_total, starts, int(box_cache.get("_new_fetches", 0)))


def goalie_points_from_recent(goalie, recent_sv: float|None, recent_starts: int) -> float:
(goalie, recent_sv: float|None, recent_starts: int) -> float:
    """Blend season profile with recent starts. If recent available, it dominates with a shrink.
    We use baseline LEAGUE_AVG_SV from goalies.py and reuse its conversion style.
    """
    if recent_sv is None:
        return goalie_adjustment_points(goalie)
    # Recent shrink ramps in over first 3 starts
    shrink = min(1.0, max(0.0, recent_starts / 3.0))
    # Convert SV to points similarly: +10 pts per +0.010 SV%
    from goalies import LEAGUE_AVG_SV, MAX_ADJ_PTS, PTS_PER_010_SV
    delta = recent_sv - LEAGUE_AVG_SV
    pts = (delta / 0.010) * PTS_PER_010_SV
    pts *= shrink
    pts = max(-MAX_ADJ_PTS, min(MAX_ADJ_PTS, pts))
    return float(pts)

FALLBACK_TO_PREVIOUS_PICKS = True
def main():n = nhl_api._session()

    # --- Goalie stats (season-to-date) ---
    goalie_profiles = {}
    try:
        goalie_payload = nhl_api.get_goalie_stats_current(session=session)
        goalie_profiles = parse_goalie_leaders(goalie_payload)
    except Exception:
        goalie_profiles = {}


    today = date.today()
    dates = [today + timedelta(days=i) for i in range(0, 8)]

    ratings_day = today - timedelta(days=1)
    state = load_state()
    box_cache = load_json(BOX_CACHE_PATH, {})
    # reset per-run fetch counter
    box_cache["_new_fetches"] = 0

    try:
        ratings, build_note, logs, home_model = rebuild_ratings_to(ratings_day, state, session)
    except RuntimeError as e:
        if FALLBACK_TO_PREVIOUS_PICKS and PICKS_PATH.exists():
            print(f"WARN: rebuild failed ({e}); keeping previous picks.json")
            return
        raise

    form = compute_form_and_rest(today, logs)

    by_date = {}
    for d in dates:
        picks = top3_for_date(d, ratings, form, home_model)
        by_date[d.isoformat()] = {"picks": picks, "build_note": build_note}

    payload = {
        "generated_at": datetime.now(tzutc()).isoformat().replace("+00:00", "Z"),
        "dates": [d.isoformat() for d in dates],
        "by_date": by_date,
        "notes": {
            "prob_shrink": PROB_SHRINK,
            "max_rebuild_days": MAX_REBUILD_DAYS,
            "form": "opponent-adjusted residuals (last 10) with recency weights; home/away splits when n>=5",
            "home_adv": "team-specific learned home advantage from season home residuals (smoothed + bounded)",
            "home_adv_bounds": [H_HOME_MIN, H_HOME_MAX],
        }
    }

    PICKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PICKS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # persist boxscore cache (remove ephemeral counter)
    if "_new_fetches" in box_cache:
        box_cache.pop("_new_fetches", None)
    save_json(BOX_CACHE_PATH, box_cache)

    print(f"Wrote {PICKS_PATH} with {len(dates)} days")

if __name__ == "__main__":
    main()
