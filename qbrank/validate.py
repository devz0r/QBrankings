"""Back-test CQR against other quarterback metrics (writes site/data/validation.json).

    python -m qbrank.validate --first 2016 --last 2025

For every season it measures
  * split-half reliability - rating from odd weeks vs. even weeks (same QB, same season),
  * year-to-year correlation - this season vs. next season,
  * correlation with the team's win percentage in the QB's starts,
and it counts "clear-cut pairs" (QB A at least as good as QB B in passer rating, ANY/A, rushing
yards per game, TDs per game and turnovers per game) that CQR ranks the wrong way round.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd

from . import formula as F
from .build import SITE_DATA, qb_ids, sanity_check, _ratings
from .data import RELEASES, _download, load_pbp, load_roster
from .stats import box

MIN_PLAYS = 300        # season sample for year-to-year / win correlations
MIN_HALF_PLAYS = 150   # per half for split-half reliability
AP_MVP = {2016: 'Matt Ryan', 2017: 'Tom Brady', 2018: 'Patrick Mahomes', 2019: 'Lamar Jackson',
          2020: 'Aaron Rodgers', 2021: 'Aaron Rodgers', 2022: 'Patrick Mahomes', 2023: 'Lamar Jackson',
          2024: 'Josh Allen'}
METRICS = {'cqr': 'CQR', 'rating': 'Passer rating', 'anya': 'ANY/A', 'epa': 'EPA per play', 'qbr': 'ESPN Total QBR'}


def _metrics(x):
    """Per-QB values of each metric (CQR without its small-sample prior, for a fair comparison)."""
    q = F.play_values(x)
    q = F.apply_defense(q, F.defense_adjustments(q))
    r = F.rate(q, prior=0.0)
    b = box(q)
    return pd.DataFrame({'cqr': r.per_dropback, 'plays': r.plays, 'rating': b.rating, 'anya': b.anya,
                         'epa': q.groupby('qb').epa.mean()})


def _team_win_pct(q, games):
    pg = q.groupby(['game_id', 'posteam', 'qb']).size().rename('n').reset_index()
    pg = pg[pg.n >= 0.5 * pg.groupby(['game_id', 'posteam']).n.transform('sum')].merge(games, on='game_id')
    margin = np.where(pg.posteam == pg.home_team, pg.home_score - pg.away_score, pg.away_score - pg.home_score)
    pg['win'] = np.where(margin > 0, 1.0, np.where(margin == 0, 0.5, 0.0))
    return pg.groupby('qb').win.mean()


def _corr(a, b):
    m = a.notna() & b.notna()
    return float(np.corrcoef(a[m], b[m])[0, 1]) if m.sum() > 5 else np.nan


def _qbr(cache):
    path = _download(RELEASES + '/espn_data/qbr_week_level.csv', os.path.join(cache, 'qbr_week_level.csv'), 24)
    wk = pd.read_csv(path)
    path = _download(RELEASES + '/espn_data/qbr_season_level.csv', os.path.join(cache, 'qbr_season_level.csv'), 24)
    ss = pd.read_csv(path)
    path = _download(RELEASES + '/players/players.csv', os.path.join(cache, 'players.csv'), 24)
    pl = pd.read_csv(path, low_memory=False, usecols=['gsis_id', 'espn_id']).dropna()
    to_gsis = pl.assign(espn_id=pl.espn_id.astype(float).astype(int).astype(str)).set_index('espn_id').gsis_id
    for t in (wk, ss):
        t['gsis'] = t.player_id.astype(str).map(to_gsis)
    return wk[wk.season_type == 'Regular'], ss[ss.season_type == 'Regular']


def run(first, last, cache='.cache', out_dir=SITE_DATA):
    qbr_week, qbr_season = _qbr(cache)
    split = {k: [] for k in METRICS}
    yoy = {k: [] for k in METRICS}
    win = {k: [] for k in METRICS}
    seasons, pairs, misses, prev = [], 0, [], None
    for season in range(first, last + 1):
        pbp = load_pbp(season, cache, max_age_hours=24 * 365)
        reg = pbp[pbp.season_type == 'REG']
        roster = load_roster(season, cache, max_age_hours=24 * 365)
        names = roster.dropna(subset=['gsis_id']).drop_duplicates('gsis_id', keep='last').set_index('gsis_id').full_name
        x = F.select_plays(reg, qb_ids(reg, roster))
        m = _metrics(x)
        m['qbr'] = qbr_season[qbr_season.season == season].drop_duplicates('gsis').set_index('gsis').qbr_total.reindex(m.index)
        halves = []
        for parity in (1, 0):
            h = _metrics(x[x.week % 2 == parity])
            wk = qbr_week[(qbr_week.season == season) & (qbr_week.game_week % 2 == parity)].dropna(subset=['gsis'])
            h['qbr'] = wk.groupby('gsis').apply(
                lambda s: np.average(s.qbr_total, weights=s.qb_plays.clip(lower=1)), include_groups=False).reindex(h.index)
            halves.append(h)
        j = halves[0].join(halves[1], lsuffix='1', rsuffix='2', how='inner')
        j = j[(j.plays1 >= MIN_HALF_PLAYS) & (j.plays2 >= MIN_HALF_PLAYS)]
        games = reg.drop_duplicates('game_id')[['game_id', 'home_team', 'away_team', 'home_score', 'away_score']]
        q_all = x[x.is_qb]
        wins = _team_win_pct(q_all, games)
        full = m[m.plays >= MIN_PLAYS]
        for k in METRICS:
            split[k].append(_corr(j[k + '1'], j[k + '2']))
            win[k].append(_corr(full[k], wins.reindex(full.index)))
            if prev is not None:
                jj = prev.join(full, lsuffix='0', rsuffix='1', how='inner')
                yoy[k].append(_corr(jj[k + '0'], jj[k + '1']))
        prev = full

        r, q, _ = _ratings(x, reg)
        audit = sanity_check(r, box(q))
        pairs += audit['pairs']
        misses += [{'season': season, 'better_box': names.get(a['better_box'], a['better_box']),
                    'ranked_higher': names.get(a['ranked_higher'], a['ranked_higher']), 'gap': a['gap']}
                   for a in audit['out_of_order']]
        top = r[r.qualified].sort_values('cqr', ascending=False).head(5)
        mvp = AP_MVP.get(season)
        ranked = r[r.qualified].sort_values('cqr', ascending=False)
        mvp_rank = next((i + 1 for i, qb in enumerate(ranked.index) if names.get(qb) == mvp), None)
        seasons.append({'season': season, 'top': [{'name': names.get(i, i), 'team': t.team, 'cqr': round(float(t.cqr), 1)}
                                                  for i, t in top.iterrows()],
                        'mvp': mvp, 'mvp_rank': mvp_rank})
        print(f'{season}: #1 {seasons[-1]["top"][0]["name"]}, MVP rank {mvp_rank}')

    result = {
        'seasons_tested': [first, last],
        'metrics': [{'key': k, 'label': v, 'split_half': round(float(np.nanmean(split[k])), 3),
                     'year_to_year': round(float(np.nanmean(yoy[k])), 3),
                     'win_pct': round(float(np.nanmean(win[k])), 3)} for k, v in METRICS.items()],
        'sanity_check': {'pairs': pairs, 'out_of_order': misses},
        'seasons': seasons,
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'validation.json'), 'w') as fh:
        json.dump(result, fh, indent=1)
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--first', type=int, default=2016)
    ap.add_argument('--last', type=int, default=2025)
    ap.add_argument('--cache', default='.cache')
    ap.add_argument('--out', default=SITE_DATA)
    args = ap.parse_args(argv)
    res = run(args.first, args.last, args.cache, args.out)
    for m in res['metrics']:
        print(f"{m['label']:<16} split-half {m['split_half']:.3f}  year-to-year {m['year_to_year']:.3f}  win% {m['win_pct']:.3f}")
    sc = res['sanity_check']
    print(f"clear-cut pairs: {sc['pairs']}, out of order: {len(sc['out_of_order'])}")


if __name__ == '__main__':
    main()
