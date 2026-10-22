"""Live check: how the frozen formula performs on the current season, which it never saw during design.

Each weekly build compares CQR with EPA per play, ANY/A and passer rating on the season so far:
  * split-half: a QB's rating in odd weeks vs. even weeks
  * early vs. late: the first half of the weeks played vs. the second half (does it predict what comes next?)
Samples are small early in the season, so these numbers are noisy until late in the year.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import formula as F
from .stats import box

METRICS = {'cqr': 'CQR', 'epa': 'EPA per play', 'anya': 'ANY/A', 'rating': 'Passer rating'}
MIN_PLAYS = 60   # per half


def _metrics(x: pd.DataFrame) -> pd.DataFrame:
    q = F.play_values(x)
    q = F.apply_defense(q, F.defense_adjustments(q))
    r = F.rate(q, prior=0.0)
    b = box(q)
    return pd.DataFrame({'cqr': r.per_dropback, 'plays': r.plays, 'rating': b.rating, 'anya': b.anya,
                         'epa': q.groupby('qb').epa.mean()})


def _pair(a: pd.DataFrame, b: pd.DataFrame):
    j = a.join(b, lsuffix='1', rsuffix='2', how='inner')
    j = j[(j.plays1 >= MIN_PLAYS) & (j.plays2 >= MIN_PLAYS)]
    out = {}
    for k in METRICS:
        m = j[k + '1'].notna() & j[k + '2'].notna()
        out[k] = round(float(np.corrcoef(j[k + '1'][m], j[k + '2'][m])[0, 1]), 3) if m.sum() > 5 else None
    return out, len(j)


def live_check(x: pd.DataFrame, weeks: list[int]) -> dict | None:
    if len(weeks) < 4:
        return None
    split, n_split = _pair(_metrics(x[x.week % 2 == 1]), _metrics(x[x.week % 2 == 0]))
    cut = weeks[len(weeks) // 2 - 1]
    early, n_early = _pair(_metrics(x[x.week <= cut]), _metrics(x[x.week > cut]))
    return {'version': F.FORMULA_VERSION, 'weeks': len(weeks), 'early_through_week': cut,
            'qbs_split': n_split, 'qbs_early_late': n_early,
            'metrics': [{'key': k, 'label': v, 'split_half': split[k], 'early_vs_late': early[k]}
                        for k, v in METRICS.items()]}
