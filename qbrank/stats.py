"""Traditional box-score stats (shown next to CQR for context)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _f(s):
    return s.fillna(0).astype(float) == 1


def box(q: pd.DataFrame, by=('qb',)) -> pd.DataFrame:
    """Box-score totals from valued QB plays. Rushing excludes kneel-downs and botched snaps."""
    by = list(by)
    own_td = q.td_team == q.posteam
    att = (q.kind == 'pass') & _f(q.pass_attempt) & ~q.two_pt
    run = q.kind.isin(['run', 'scramble']) & ~q.two_pt
    t = q[by].copy()
    t['att'] = att
    t['cmp'] = att & _f(q.complete_pass)
    t['pass_yds'] = np.where(att, q.passing_yards.fillna(0), 0)
    t['pass_td'] = att & _f(q.pass_touchdown) & own_td
    t['ints'] = att & _f(q.interception)
    t['sacks'] = q.kind == 'sack'
    t['sack_yds'] = np.where(q.kind == 'sack', -q.yards_gained.fillna(0), 0)
    t['rush_att'] = run
    t['rush_yds'] = np.where(run, q.rushing_yards.fillna(0), 0)
    t['rush_td'] = run & _f(q.rush_touchdown) & own_td
    t['fumbles'] = q.own_fumble
    t['fumbles_lost'] = q.own_fumble & _f(q.fumble_lost)
    t['cpoe_sum'] = np.where(att & q.cpoe.notna(), q.cpoe.fillna(0), 0)
    t['cpoe_n'] = att & q.cpoe.notna()
    b = t.groupby(by).sum(numeric_only=False)
    b = b.astype(float)
    a = b.att.where(b.att > 0)
    clip = lambda s: s.clip(0, 2.375)
    rating = (clip((b.cmp / a - 0.3) * 5) + clip((b.pass_yds / a - 3) * 0.25)
              + clip(b.pass_td / a * 20) + clip(2.375 - b.ints / a * 25)) / 6 * 100
    b['rating'] = rating
    b['anya'] = (b.pass_yds + 20 * b.pass_td - 45 * b.ints - b.sack_yds) / (b.att + b.sacks).where(lambda s: s > 0)
    b['cmp_pct'] = b.cmp / a * 100
    b['ypa'] = b.pass_yds / a
    b['cpoe'] = b.cpoe_sum / b.cpoe_n.where(b.cpoe_n > 0)
    return b.drop(columns=['cpoe_sum', 'cpoe_n'])
