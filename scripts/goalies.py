from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, List

LEAGUE_AVG_SV = 0.905  # baseline for converting SV% to Elo points
MAX_ADJ_PTS = 25       # cap goalie effect (Elo points)
PTS_PER_010_SV = 10    # +10 pts for +0.010 SV% vs baseline (before shrink)


@dataclass
class GoalieProfile:
    player_id: int
    team_abbrev: str
    save_pctg: float
    games_played: int


def parse_goalie_leaders(payload: dict) -> Dict[int, GoalieProfile]:
    """Parse /v1/goalie-stats-leaders/current into goalie profiles.
    Endpoint supports categories + limit (community docs)."""
    out: Dict[int, GoalieProfile] = {}
    rows = payload.get("goalies") or payload.get("data") or payload.get("results") or []
    if isinstance(rows, dict):
        merged: List[dict] = []
        for v in rows.values():
            if isinstance(v, list):
                merged.extend(v)
        rows = merged
    for r in rows:
        pid = r.get("playerId") or r.get("id") or r.get("player_id")
        team = r.get("teamAbbrev") or r.get("team") or r.get("team_abbrev")
        sv = r.get("savePctg") or r.get("save_pctg")
        gp = r.get("gamesPlayed") or r.get("gp") or r.get("games") or 0
        if pid is None or team is None or sv is None:
            continue
        try:
            out[int(pid)] = GoalieProfile(
                player_id=int(pid),
                team_abbrev=str(team),
                save_pctg=float(sv),
                games_played=int(gp),
            )
        except Exception:
            continue
    return out


def pick_probable_goalie_id(team_abbrev: str, goalie_profiles: Dict[int, GoalieProfile]) -> Optional[int]:
    candidates = [g for g in goalie_profiles.values() if g.team_abbrev == team_abbrev]
    if not candidates:
        return None
    candidates.sort(key=lambda g: (g.games_played, g.save_pctg), reverse=True)
    return candidates[0].player_id


def pick_confirmed_starter_from_boxscore(boxscore: dict, team_side: str) -> Optional[int]:
    try:
        goalies = boxscore["playerByGameStats"][team_side]["goalies"]
    except Exception:
        return None
    for g in goalies:
        if g.get("starter") is True:
            pid = g.get("playerId")
            if pid is None:
                continue
            try:
                return int(pid)
            except Exception:
                return None
    return None


def goalie_adjustment_points(goalie: Optional[GoalieProfile]) -> float:
    if goalie is None:
        return 0.0
    shrink = min(1.0, max(0.0, goalie.games_played / 15.0))
    delta = goalie.save_pctg - LEAGUE_AVG_SV
    pts = (delta / 0.010) * PTS_PER_010_SV
    pts *= shrink
    pts = max(-MAX_ADJ_PTS, min(MAX_ADJ_PTS, pts))
    return float(pts)
