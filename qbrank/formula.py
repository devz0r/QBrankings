"""CQR - Complete Quarterback Rating.

This module *is* the formula. Every constant is defined here and every step
below matches the methodology page on the site.

Overview
--------
1. Collect every play a quarterback is responsible for: dropbacks (passes,
   sacks, scrambles, botched snaps, pass interference drawn) and designed runs
   (including sneaks and two-point tries). Kneels, spikes and plays wiped out
   by a penalty (other than defensive pass interference) are ignored.
2. Value each play two ways and average them:
     * Points:  expected points added (EPA) with three fixes - receivers keep
       25% of the yards-after-catch they earned beyond expectation, fumbles
       are charged at their average cost (recovering your own fumble is luck),
       and drawn pass interference counts half.
     * Yards:   adjusted yards, an all-plays version of ANY/A - passing and
       rushing yards, minus sack yards, +20 per TD, -45 per interception
       (not on end-of-half heaves), -45 per expected lost fumble.
       Nine adjusted yards = one point.
   Each play is compared with the league average for the same kind of play
   (an average dropback, or an average NFL run in the same situation).
3. Plays in the 4th quarter or overtime of one-score games count 1.25x.
4. Subtract the quality of the defenses faced (each defense's average value
   allowed to other teams' quarterbacks, regressed toward average).
5. Divide by dropbacks plus 100 "phantom" league-average dropbacks, so a QB's
   rating has to be earned over a real sample. Designed runs add value on top
   of the per-dropback rate instead of diluting it.
6. Map to 0-100 with a logistic curve: 50 is exactly league average.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants (calibrated on 2016-2025 regular seasons; see README)
# ---------------------------------------------------------------------------
YAC_RECEIVER_SHARE = 0.25   # share of YAC-over-expected credited to the receiver, not the QB
DPI_SHARE = 0.5             # defensive pass interference drawn counts half
CLUTCH_WEIGHT = 1.25        # 4th quarter / OT with the score within 8 points
CLUTCH_MARGIN = 8
POINTS_WEIGHT = 0.5         # blend: half points (EPA), half adjusted yards
YARDS_PER_POINT = 9.0       # converts adjusted yards to points
TD_BONUS_YARDS = 20.0
INT_COST_YARDS = 45.0
FUMBLE_COST_YARDS = 45.0
FUMBLE_SWING_POINTS = 4.0   # EPA swing between a lost and a recovered fumble
# league rate at which each kind of QB fumble is lost (2016-2025)
FUMBLE_LOST_RATE = {'sack': 0.52, 'dropback': 0.19, 'run': 0.41, 'snap': 0.26}
SHORT_YARDAGE = 2           # designed runs with <= 2 yards to go use the short-yardage baseline
HEAVE_SECONDS = 8           # end-of-half heave: <= 8 s left in the half ...
HEAVE_AIR_YARDS = 30        # ... thrown 30+ yards; an interception there costs no yards
DEFENSE_PRIOR_DROPBACKS = 800.0
QB_PRIOR_DROPBACKS = 100.0
GAME_PRIOR_DROPBACKS = 10.0  # lighter prior for single-game scores
SCALE = 0.085               # logistic scale: CQR = 100 / (1 + exp(-value / SCALE))
QUALIFY_DROPBACKS_PER_TEAM_GAME = 14

PBP_COLUMNS = [
    'play_id', 'game_id', 'season', 'season_type', 'week', 'game_date', 'posteam', 'defteam',
    'home_team', 'away_team', 'home_score', 'away_score', 'qtr', 'down', 'ydstogo',
    'half_seconds_remaining', 'score_differential', 'play_type', 'pass', 'rush', 'qb_dropback',
    'qb_scramble', 'qb_kneel', 'qb_spike', 'aborted_play', 'two_point_attempt', 'pass_attempt',
    'complete_pass', 'interception', 'sack', 'pass_touchdown', 'rush_touchdown', 'td_team',
    'fumble', 'fumble_lost', 'fumbled_1_player_id', 'id', 'passing_yards', 'rushing_yards',
    'yards_gained', 'air_yards', 'yards_after_catch', 'xyac_mean_yardage', 'epa', 'qb_epa',
    'yac_epa', 'xyac_epa', 'penalty_type', 'penalty_yards', 'cpoe', 'first_down', 'name',
]


def cqr(value):
    """Map value-above-average per dropback onto the 0-100 CQR scale."""
    return 100.0 / (1.0 + np.exp(-np.asarray(value, dtype=float) / SCALE))


def _flag(df, col):
    return df[col].fillna(0).astype(float) == 1


def select_plays(pbp: pd.DataFrame, qb_ids) -> pd.DataFrame:
    """Return QB plays plus all league designed runs (needed for the run baseline).

    `pbp` is nflverse play-by-play for one season type. Adds derived columns;
    `is_qb` marks the plays that belong to a quarterback.
    """
    d = pbp
    live = (d.play_type.isin(['pass', 'run']) & (_flag(d, 'pass') | _flag(d, 'rush'))
            & ~_flag(d, 'qb_kneel') & ~_flag(d, 'qb_spike') & d.epa.notna())
    dpi = ((d.play_type == 'no_play') & _flag(d, 'pass')
           & (d.penalty_type == 'Defensive Pass Interference') & d.epa.notna())
    qb_play = (live | dpi) & d['id'].isin(qb_ids)
    league_run = (live & (d.play_type == 'run') & ~_flag(d, 'qb_scramble')
                  & ~_flag(d, 'aborted_play') & ~_flag(d, 'two_point_attempt'))
    x = d.loc[qb_play | league_run].copy()
    x['is_qb'] = qb_play.loc[x.index].values
    x['qb'] = x['id']
    x['two_pt'] = _flag(x, 'two_point_attempt')
    is_dpi = dpi.loc[x.index].values
    x['kind'] = np.select(
        [is_dpi, _flag(x, 'sack'), _flag(x, 'qb_scramble'), _flag(x, 'qb_dropback'), _flag(x, 'aborted_play')],
        ['dpi', 'sack', 'scramble', 'pass', 'snap'], 'run')
    x['cat'] = np.where(x.kind == 'run', 'run', 'dropback')
    x['short'] = x.ydstogo.fillna(10) <= SHORT_YARDAGE

    # --- points side ---
    base = x.qb_epa.where(x.qb_epa.notna(), x.epa)
    yac_ok = _flag(x, 'complete_pass') & x.xyac_epa.notna() & x.yac_epa.notna() & ~_flag(x, 'fumble')
    x['yac_over_exp_pts'] = (x.yac_epa - x.xyac_epa).where(yac_ok, 0.0)
    own_fumble = _flag(x, 'fumble') & (x.fumbled_1_player_id == x['id'])
    fumble_kind = np.select([_flag(x, 'sack'), _flag(x, 'qb_dropback'), _flag(x, 'aborted_play')],
                            ['sack', 'dropback', 'snap'], 'run')
    p_lost = np.where(own_fumble, pd.Series(fumble_kind).map(FUMBLE_LOST_RATE).values, 0.0)
    lost = _flag(x, 'fumble_lost').values
    x['fumble_luck_pts'] = np.where(own_fumble, (lost - p_lost) * FUMBLE_SWING_POINTS, 0.0)
    x['exp_fumbles_lost'] = p_lost
    x['own_fumble'] = own_fumble
    pts = base - YAC_RECEIVER_SHARE * x.yac_over_exp_pts + x.fumble_luck_pts
    x['pts'] = np.where(is_dpi, pts * DPI_SHARE, pts)

    # --- yards side ---
    attempt = (x.kind == 'pass') & _flag(x, 'pass_attempt')
    complete = attempt & _flag(x, 'complete_pass')
    yac_y_ok = complete & x.xyac_mean_yardage.notna() & x.yards_after_catch.notna()
    yac_over_exp_y = np.where(yac_y_ok, x.yards_after_catch.fillna(0) - x.xyac_mean_yardage.fillna(0), 0.0)
    pass_yds = np.where(complete, x.passing_yards.fillna(0), 0.0)
    rush_yds = np.where(x.kind.isin(['run', 'scramble', 'snap']), x.rushing_yards.fillna(0), 0.0)
    sack_yds = np.where(x.kind == 'sack', x.yards_gained.fillna(0), 0.0)  # negative
    dpi_yds = np.where(x.kind == 'dpi', x.penalty_yards.fillna(0) * DPI_SHARE, 0.0)
    td = ((_flag(x, 'pass_touchdown') | _flag(x, 'rush_touchdown')) & (x.td_team == x.posteam) & ~x.two_pt)
    intercepted = _flag(x, 'interception')
    heave = intercepted & (x.half_seconds_remaining <= HEAVE_SECONDS) & (x.air_yards.fillna(0) >= HEAVE_AIR_YARDS)
    adj = (pass_yds - YAC_RECEIVER_SHARE * yac_over_exp_y + rush_yds + sack_yds + dpi_yds
           + TD_BONUS_YARDS * td - INT_COST_YARDS * (intercepted & ~heave) - FUMBLE_COST_YARDS * p_lost)
    # two-point tries: +/-10 yards so the yards side agrees with the points side
    x['adj_yds'] = np.where(x.two_pt, np.where(base > 0, 10.0, -10.0), adj)
    x['td'] = td
    x['heave'] = heave

    x['weight'] = np.where((x.qtr >= 4) & (x.score_differential.abs() <= CLUTCH_MARGIN), CLUTCH_WEIGHT, 1.0)
    x['dropback'] = (x.cat == 'dropback')
    return x


def baselines(x: pd.DataFrame) -> dict:
    """League-average points and adjusted yards for each kind of play."""
    qb_db = x.is_qb & x.dropback & ~x.two_pt
    runs = (x.cat == 'run') & ~x.two_pt
    avg = lambda m: (float(x.pts[m].mean()), float(x.adj_yds[m].mean())) if m.any() else None
    every_run = avg(runs) or (0.0, 0.0)
    out = {'dropback': avg(qb_db) or (0.0, 0.0)}
    for short in (False, True):
        # tiny samples (opening weekend) fall back to the all-runs average
        r = runs & (x.short == short)
        out['run_short' if short else 'run'] = avg(r) if r.sum() >= 30 else every_run
    return out


def play_values(x: pd.DataFrame, base: dict | None = None) -> pd.DataFrame:
    """QB plays with `value`: points above an average play of the same kind."""
    base = base or baselines(x)
    q = x[x.is_qb].copy()
    key = np.where(q.dropback, 'dropback', np.where(q.short, 'run_short', 'run'))
    bp = pd.Series(key).map({k: v[0] for k, v in base.items()}).values
    by = pd.Series(key).map({k: v[1] for k, v in base.items()}).values
    bp = np.where(q.two_pt, 0.0, bp)
    by = np.where(q.two_pt, 0.0, by)
    q['value'] = (POINTS_WEIGHT * (q.pts - bp)
                  + (1 - POINTS_WEIGHT) * (q.adj_yds - by) / YARDS_PER_POINT)
    q['w_value'] = q.weight * q.value
    q['w_dropback'] = np.where(q.dropback, q.weight, 0.0)
    return q


def defense_adjustments(q: pd.DataFrame) -> pd.DataFrame:
    """Per (defense, offense) pair: the defense's value allowed to *other* offenses' QBs,
    per weighted dropback, regressed toward league average (0)."""
    by_def = q.groupby('defteam')[['w_value', 'w_dropback']].sum()
    pair = q.groupby(['defteam', 'posteam'])[['w_value', 'w_dropback']].sum().reset_index()
    tot = by_def.reindex(pair.defteam).values
    pair['def_adj'] = ((tot[:, 0] - pair.w_value.values)
                       / (tot[:, 1] - pair.w_dropback.values + DEFENSE_PRIOR_DROPBACKS))
    return pair[['defteam', 'posteam', 'def_adj']]


def apply_defense(q: pd.DataFrame, pairs: pd.DataFrame) -> pd.DataFrame:
    q = q.drop(columns=[c for c in ('def_adj',) if c in q]).merge(pairs, on=['defteam', 'posteam'], how='left')
    q['def_adj'] = q.def_adj.fillna(0.0)
    q['schedule'] = -q.w_dropback * q.def_adj   # credit for facing good defenses
    return q


COMPONENTS = {'passing': ('pass', 'dpi'), 'rushing': ('run', 'scramble'), 'sacks': ('sack', 'snap')}


def rate(q: pd.DataFrame, prior: float = QB_PRIOR_DROPBACKS, by=('qb',)) -> pd.DataFrame:
    """Aggregate valued, defense-adjusted plays into ratings."""
    by = list(by)
    g = q.groupby(by)
    out = g.agg(plays=('value', 'size'), dropbacks=('dropback', 'sum'), w_dropbacks=('w_dropback', 'sum'),
                value=('w_value', 'sum'), schedule=('schedule', 'sum'), games=('game_id', 'nunique'))
    for name, kinds in COMPONENTS.items():
        out[name] = q[q.kind.isin(kinds)].groupby(by).w_value.sum().reindex(out.index).fillna(0.0)
    out['total'] = out.value + out.schedule
    out['per_dropback'] = (out.total / (out.w_dropbacks + prior)).replace([np.inf, -np.inf], np.nan)
    out['cqr'] = cqr(out.per_dropback)
    return out


def rate_season(x: pd.DataFrame):
    """Full pipeline on selected plays: returns (ratings, valued plays, defense pairs)."""
    q = play_values(x)
    pairs = defense_adjustments(q)
    q = apply_defense(q, pairs)
    return rate(q), q, pairs
