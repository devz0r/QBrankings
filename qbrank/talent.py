"""Best QBs right now: a talent estimate that blends this season's CQR with past seasons.

CQR answers "who has played best this season?" and uses only this season's plays. This answers "who is
the best quarterback?" - an estimate of how each QB will play from here on:

            n × V  +  0.75 × Σ 0.5^(k−1) × n_k × V_k  +  200 × μ
    T  =  ───────────────────────────────────────────────────────
            n      +  0.75 × Σ 0.5^(k−1) × n_k          +  200

  V, n      this season's CQR value per dropback (before the 100-dropback cushion) and dropbacks
  V_k, n_k  the same for k seasons ago (k = 1..3); each older season counts half as much
  μ         starting point for a QB with little history: veteran −0.07, first-round rookie −0.06,
            other rookie −0.18 (all slightly below league average, which is what such QBs turn out to be)

T goes on the same 0-100 curve as CQR. The weights were fitted on 2018-2021 (best prediction of each
QB's rest-of-season CQR from past seasons plus the first N weeks), then tested on 2022-2025, where the
estimate predicted better than CQR alone at every point of the season (higher correlation
throughout; lower error through Week 12, about equal after). No age effect improved the fit, so there is none.
"""
from __future__ import annotations

import json
import os

import pandas as pd

from .formula import cqr

DECAY = 0.5             # each older season counts half as much as the one after it
HISTORY_WEIGHT = 0.75   # a past-season dropback is worth 0.75 of a this-season dropback
REGRESS_DROPBACKS = 200
PRIOR = {'vet': -0.072, 'first_round_rookie': -0.057, 'other_rookie': -0.176}
LOOKBACK = 3
MIN_EVIDENCE = 150      # rank only QBs with this much weighted evidence (this season + history)


def past_seasons(season: int, data_dir: str) -> dict:
    """{k: DataFrame(value_raw, denom) by QB id} for the previous LOOKBACK seasons that were built."""
    out = {}
    for k in range(1, LOOKBACK + 1):
        path = os.path.join(data_dir, f'{season - k}.json')
        if not os.path.exists(path):
            continue
        rows = [q for q in json.load(open(path))['qbs'] if q.get('value_raw') is not None and q.get('denom')]
        if rows:
            out[k] = pd.DataFrame(rows).set_index('id')[['value_raw', 'denom']]
    return out


def prior_group(qb: str, season: int, roster: pd.DataFrame) -> str:
    row = roster[roster.gsis_id == qb]
    if row.empty:
        return 'vet'
    r = row.iloc[-1]
    rookie = r.get('rookie_year')
    if pd.isna(rookie):
        rookie = r.get('entry_year')
    if pd.isna(rookie) or int(rookie) < season:
        return 'vet'
    draft = r.get('draft_number')
    return 'first_round_rookie' if not pd.isna(draft) and draft <= 32 else 'other_rookie'


def estimate(current: pd.DataFrame, season: int, roster: pd.DataFrame, data_dir: str) -> pd.DataFrame:
    """`current` has value_raw and denom per QB id for this season so far."""
    past = past_seasons(season, data_dir)
    rows = []
    for qb, cur in current.iterrows():
        v, n = (0.0 if pd.isna(cur.value_raw) else float(cur.value_raw)), float(cur.denom or 0.0)
        hist_num = hist_w = 0.0
        for k, frame in past.items():
            if qb in frame.index:
                w = HISTORY_WEIGHT * DECAY ** (k - 1) * float(frame.at[qb, 'denom'])
                hist_num += w * float(frame.at[qb, 'value_raw'])
                hist_w += w
        mu = PRIOR[prior_group(qb, season, roster)]
        total = n + hist_w + REGRESS_DROPBACKS
        value = (n * v + hist_num + REGRESS_DROPBACKS * mu) / total
        rows.append({'qb': qb, 'value': value, 'evidence': n + hist_w,
                     'share_season': n / total, 'share_history': hist_w / total})
    out = pd.DataFrame(rows).set_index('qb')
    out['cqr'] = cqr(out.value)
    return out
