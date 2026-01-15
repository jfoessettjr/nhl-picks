import math
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True)
class EloConfig:
    base_rating: float = 1500.0
    home_ice_adv: float = 55.0  # rating points
    scale: float = 400.0

def expected_home(r_home: float, r_away: float, cfg: EloConfig) -> float:
    r_home_adj = r_home + cfg.home_ice_adv
    return 1.0 / (1.0 + 10 ** ((r_away - r_home_adj) / cfg.scale))

def mov_multiplier(goal_diff: int, r_home: float, r_away: float, cfg: EloConfig) -> float:
    # Hockey can get noisy (empty netters). Cap goal diff.
    gd = min(abs(int(goal_diff)), 3)
    rdiff = abs((r_home + cfg.home_ice_adv) - r_away)
    return math.log(gd + 1.0) * (2.2 / (0.001 * rdiff + 2.2))

def k_factor(game_date: date) -> float:
    m = game_date.month
    if m in (10, 11): return 28.0
    if m == 12: return 24.0
    if m in (1, 2): return 20.0
    if m in (3, 4): return 18.0
    return 16.0

def update_ratings(r_home: float, r_away: float, s_home: float, goal_diff: int, game_date: date, cfg: EloConfig):
    e_home = expected_home(r_home, r_away, cfg)
    k = k_factor(game_date)
    mm = mov_multiplier(goal_diff, r_home, r_away, cfg)
    delta = k * mm * (s_home - e_home)
    return (r_home + delta, r_away - delta, delta, e_home, k, mm)
