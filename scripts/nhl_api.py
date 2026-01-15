from __future__ import annotations
import time
import requests
from datetime import date, timedelta
from typing import List, Optional, Tuple, Dict, Any, Set

BASE = "https://api-web.nhle.com/v1"
_SESSION = requests.Session()

def _get(url: str, params: Optional[dict] = None, max_retries: int = 6) -> dict:
    backoff = 0.75
    for attempt in range(max_retries):
        r = _SESSION.get(url, params=params, timeout=30)
        if r.status_code == 429:
            ra = r.headers.get("Retry-After")
            sleep_s = float(ra) if ra and ra.replace(".","",1).isdigit() else backoff
            time.sleep(min(10.0, sleep_s))
            backoff = min(10.0, backoff * 1.8)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Too many retries")

def get_schedule_for_date(day: date) -> List[dict]:
    data = _get(f"{BASE}/schedule/{day.isoformat()}")
    games: List[dict] = []
    for d in data.get("gameWeek", []) or []:
        if d.get("date") == day.isoformat():
            games.extend(d.get("games", []) or [])
    return games

def get_score_for_date(day: date) -> List[dict]:
    data = _get(f"{BASE}/score/{day.isoformat()}")
    games = data.get("games", [])
    return games if isinstance(games, list) else []

def get_games_range_weekly(start: date, end: date) -> List[dict]:
    # Use weekly schedule payloads to minimize calls.
    out: List[dict] = []
    seen: Set[int] = set()
    cur = start
    safety = 0
    while cur <= end and safety < 200:
        safety += 1
        payload = _get(f"{BASE}/schedule/{cur.isoformat()}")
        week_days = payload.get("gameWeek", []) or []
        if not week_days:
            cur += timedelta(days=7)
            continue

        dates = [d.get("date") for d in week_days if d.get("date")]
        dates = [ds for ds in dates if isinstance(ds, str) and len(ds) >= 10]
        max_day = max(date.fromisoformat(ds[:10]) for ds in dates)

        for gday in week_days:
            ds = gday.get("date")
            if not ds:
                continue
            d = date.fromisoformat(ds[:10])
            if d < start or d > end:
                continue
            for g in (gday.get("games", []) or []):
                gid = g.get("id") or g.get("gamePk")
                if gid is None:
                    continue
                try:
                    gid_int = int(gid)
                except Exception:
                    continue
                if gid_int in seen:
                    continue
                seen.add(gid_int)
                out.append(g)

        cur = max_day + timedelta(days=1)
        time.sleep(0.15)
    return out

def parse_game_basic(game: dict) -> dict:
    home = game.get("homeTeam", {}) or {}
    away = game.get("awayTeam", {}) or {}

    gid = game.get("id") or game.get("gamePk")
    gdate = (
        game.get("gameDate")
        or game.get("gameDateUTC")
        or game.get("date")
        or game.get("startTimeUTC")
        or game.get("startTime")
    )
    if isinstance(gdate, str):
        gdate = gdate[:10]
    else:
        gdate = None

    status = (game.get("gameState") or game.get("status") or game.get("detailedState") or "").strip()

    return {
        "gamePk": gid,
        "date": gdate,
        "status": status,
        "home_team_id": int(home.get("id")) if home.get("id") is not None else None,
        "home_team_name": home.get("name") or home.get("placeName", {}).get("default") or home.get("commonName", {}).get("default"),
        "away_team_id": int(away.get("id")) if away.get("id") is not None else None,
        "away_team_name": away.get("name") or away.get("placeName", {}).get("default") or away.get("commonName", {}).get("default"),
        "home_score": home.get("score"),
        "away_score": away.get("score"),
    }

def is_final(game: dict) -> bool:
    state = (game.get("gameState") or game.get("status") or game.get("detailedState") or "").upper()
    return state in ("FINAL", "OFF", "GAME OVER") or "FINAL" in state

def final_kind(game: dict) -> str:
    # Some payloads provide "periodDescriptor" / "gameOutcome" but not always.
    # We'll keep it simple: assume regulation unless hints exist.
    outcome = (game.get("gameOutcome") or {}).get("lastPeriodType")
    if isinstance(outcome, str):
        outcome = outcome.upper()
        if "SO" in outcome: return "SO"
        if "OT" in outcome: return "OT"
    # Another hint sometimes: gameState == "OFF" but has "overtime" markers; ignore for now.
    return "REG"

def get_final_score(game: dict) -> Optional[Tuple[int, int]]:
    home = game.get("homeTeam", {}) or {}
    away = game.get("awayTeam", {}) or {}
    h = home.get("score")
    a = away.get("score")
    if h is None or a is None:
        return None
    try:
        return int(h), int(a)
    except Exception:
        return None


# --- Goalie helpers (free endpoints) ---
def get_goalie_stats_current(session=None, categories="savePctg,gamesPlayed", limit=-1):
    """Fetch current goalie stats leaders. limit=-1 requests all results."""
    s = session or _session()
    url = f"{BASE_URL}/goalie-stats-leaders/current"
    params = {"categories": categories, "limit": str(limit)}
    return _get_json(url, params=params, session=s)

def get_boxscore(game_id, session=None):
    """Fetch gamecenter boxscore (includes goalie 'starter' flags once available)."""
    s = session or _session()
    url = f"{BASE_URL}/gamecenter/{game_id}/boxscore"
    return _get_json(url, session=s)
