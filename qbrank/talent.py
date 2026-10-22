"""Best QBs right now: a power ranking that leans on this season and steadies it with last season.

CQR answers "who has played best this season?" and uses only this season's plays. This answers "who is
the best quarterback right now?":

          n × V  +  h × n₁ × (V₁ + y)  +  50 × μ
    T  =  ─────────────────────────────────────        h = 0.2 × max(0, 1 − n ÷ 600)
          n      +  h × n₁              +  50

  V, n    this season's CQR value per dropback (before the 100-dropback cushion) and dropbacks
  V₁, n₁  the same for last season
  h       how much a last-season dropback counts: 0.2 of a this-season dropback at the start of the year,
          fading to nothing by 600 dropbacks (about a full season)
  y       +0.06 for QBs in their 2nd-4th seasons, who on average improve on their previous year
  μ       starting point for a QB with no history: veteran −0.08, first-round rookie −0.06, other rookie −0.19

For a regular starter about five games in, this season is roughly 60% of the rating. Tested on 2022-2025
(seasons not used for fitting), it predicts each QB's rest-of-season CQR about as well as a version that
leans on three past seasons, better from midseason on, and much better than CQR alone at every week.
"""
from __future__ import annotations

import json
import os

import pandas as pd

from .formula import cqr

HISTORY_WEIGHT = 0.2      # a last-season dropback counts 0.2 of a this-season dropback ...
FADE_DROPBACKS = 600.0    # ... fading linearly to zero by this many dropbacks this season
REGRESS_DROPBACKS = 50
YOUNG_BONUS = 0.06        # added to last season's value for QBs in their 2nd-4th seasons
PRIOR = {'vet': -0.083, 'first_round_rookie': -0.060, 'other_rookie': -0.187}
LOOKBACK = 1
MIN_EVIDENCE = 150        # rank only QBs with this much weighted evidence (this season + last season)


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


def _roster_row(qb: str, roster: pd.DataFrame):
    row = roster[roster.gsis_id == qb]
    return None if row.empty else row.iloc[-1]


def rookie_year(r):
    if r is None:
        return None
    y = r.get('rookie_year')
    if pd.isna(y):
        y = r.get('entry_year')
    return None if pd.isna(y) else int(y)


def prior_group(qb: str, season: int, roster: pd.DataFrame) -> str:
    r = _roster_row(qb, roster)
    ry = rookie_year(r)
    if ry is None or ry < season:
        return 'vet'
    draft = r.get('draft_number')
    return 'first_round_rookie' if not pd.isna(draft) and draft <= 32 else 'other_rookie'


def is_young(qb: str, season: int, roster: pd.DataFrame) -> bool:
    ry = rookie_year(_roster_row(qb, roster))
    return ry is not None and 1 <= season - ry <= 3


def estimate(current: pd.DataFrame, season: int, roster: pd.DataFrame, data_dir: str) -> pd.DataFrame:
    """`current` has value_raw and denom per QB id for this season so far."""
    past = past_seasons(season, data_dir).get(1)
    rows = []
    for qb, cur in current.iterrows():
        v, n = (0.0 if pd.isna(cur.value_raw) else float(cur.value_raw)), float(cur.denom or 0.0)
        hist_num = hist_w = 0.0
        if past is not None and qb in past.index:
            h = HISTORY_WEIGHT * max(0.0, 1 - n / FADE_DROPBACKS)
            hist_w = h * float(past.at[qb, 'denom'])
            bonus = YOUNG_BONUS if is_young(qb, season, roster) else 0.0
            hist_num = hist_w * (float(past.at[qb, 'value_raw']) + bonus)
        mu = PRIOR[prior_group(qb, season, roster)]
        total = n + hist_w + REGRESS_DROPBACKS
        value = (n * v + hist_num + REGRESS_DROPBACKS * mu) / total
        # evidence counts last season at full weight, so ranking eligibility doesn't fade with the history weight
        evidence = n + (float(past.at[qb, 'denom']) if past is not None and qb in past.index else 0.0)
        rows.append({'qb': qb, 'value': value, 'evidence': evidence,
                     'share_season': n / total, 'share_history': hist_w / total})
    out = pd.DataFrame(rows).set_index('qb')
    out['cqr'] = cqr(out.value)
    return out
