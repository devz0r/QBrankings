"""Build the rankings JSON the website reads.

    python -m qbrank.build                 # current season
    python -m qbrank.build --season 2024   # one season
    python -m qbrank.build --all           # 2016 through the current season
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os

import numpy as np
import pandas as pd

from . import formula as F
from .data import load_pbp, load_roster
from .stats import box
from . import talent as T
from .live import live_check

FIRST_SEASON = 2016
MIN_DROPBACK_SHARE = 0.5
SITE_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'site', 'data')


def current_season(today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    return today.year if today.month >= 9 else today.year - 1


def qb_ids(reg: pd.DataFrame, roster: pd.DataFrame) -> set:
    """Roster QBs, plus anyone with 20+ dropbacks (covers roster gaps and emergency QBs)."""
    ids = set(roster.loc[roster.position == 'QB', 'gsis_id'].dropna())
    db = reg[(reg.qb_dropback.fillna(0) == 1) & reg['id'].notna()].groupby('id').size()
    return ids | set(db[db >= 20].index)


def _round(v, nd=1):
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return None
    return round(float(v), nd)


def _score(v):
    """CQR for display: one decimal, kept inside (0, 100) so 99.96 doesn't print as 100.0."""
    v = _round(v)
    return None if v is None else min(99.9, max(0.1, v))


def _team_games(reg: pd.DataFrame) -> pd.Series:
    g = reg[['game_id', 'home_team', 'away_team']].drop_duplicates('game_id')
    return pd.concat([g.home_team, g.away_team]).value_counts()


def _rank(r: pd.DataFrame) -> pd.Series:
    order = r[r.qualified].sort_values('cqr', ascending=False)
    return pd.Series(np.arange(1, len(order) + 1), index=order.index).reindex(r.index)


def _ratings(x: pd.DataFrame, reg: pd.DataFrame):
    """Rate selected plays; adds team, qualification and rank."""
    r, q, pairs = F.rate_season(x)
    last = q.sort_values(['week', 'game_id']).groupby('qb').posteam.last()
    r['team'] = last.reindex(r.index)
    tg = _team_games(reg)
    r['team_games'] = r.team.map(tg).fillna(r.games)
    r['qualified'] = r.dropbacks >= F.QUALIFY_DROPBACKS_PER_TEAM_GAME * r.team_games
    r['rank'] = _rank(r)
    return r, q, pairs


def _box_dict(b: pd.Series) -> dict:
    ints = ['att', 'cmp', 'pass_yds', 'pass_td', 'ints', 'sacks', 'sack_yds', 'rush_att', 'rush_yds', 'rush_td',
            'fumbles', 'fumbles_lost']
    d = {k: int(b[k]) for k in ints}
    d.update(rating=_round(b.rating), anya=_round(b.anya, 2), cmp_pct=_round(b.cmp_pct), ypa=_round(b.ypa, 2),
             cpoe=_round(b.cpoe))
    return d


SANITY_HIGHER = ('rating', 'anya', 'rush_yds_g', 'td_g')
SANITY_LOWER = ('giveaways_g', 'sack_rate')


def sanity_check(r: pd.DataFrame, sbox: pd.DataFrame) -> dict:
    """Find clear-cut pairs: QB A is at least as good as QB B in passer rating, ANY/A, rushing
    yards per game, total TDs per game, giveaways (INT + fumbles) per game and sack rate.
    CQR should rank A higher; anything else is reported."""
    q = r[r.qualified].join(sbox, rsuffix='_box')
    q = q.assign(rush_yds_g=q.rush_yds / q.games, td_g=(q.pass_td + q.rush_td) / q.games,
                 giveaways_g=(q.ints + q.fumbles) / q.games,
                 sack_rate=q.sacks_box / (q.att + q.sacks_box)).dropna(subset=list(SANITY_HIGHER))
    hi = q[list(SANITY_HIGHER)].values
    lo = q[list(SANITY_LOWER)].values
    ids, score = list(q.index), q.cqr.values
    pairs, out_of_order = 0, []
    for i in range(len(ids)):
        dom = (hi[i] >= hi).all(axis=1) & (lo[i] <= lo).all(axis=1)
        dom[i] = False
        for j in np.where(dom)[0]:
            pairs += 1
            if score[i] < score[j]:
                out_of_order.append({'better_box': ids[i], 'ranked_higher': ids[j], 'gap': _round(score[j] - score[i])})
    return {'pairs': pairs, 'out_of_order': out_of_order}


def _game_rows(qb, q, games_meta, gscore, gbox):
    rows = []
    for gid in q.loc[q.qb == qb].sort_values('week').game_id.unique():
        m = games_meta.loc[gid]
        team = q.loc[(q.qb == qb) & (q.game_id == gid), 'posteam'].iloc[0]
        home = team == m.home_team
        pf, pa = (m.home_score, m.away_score) if home else (m.away_score, m.home_score)
        res = 'W' if pf > pa else ('L' if pf < pa else 'T')
        s = gscore.loc[(qb, gid)]
        b = gbox.loc[(qb, gid)]
        rows.append({'week': int(m.week), 'team': team, 'opp': m.away_team if home else m.home_team, 'home': bool(home),
                     'result': f'{res} {int(pf)}-{int(pa)}', 'cqr': _score(s.cqr), 'dropbacks': int(s.dropbacks),
                     'value': _round(s.total, 1), **_box_dict(b)})
    return rows


def build_season(season: int, cache_dir: str = '.cache', out_dir: str = SITE_DATA) -> dict:
    pbp = load_pbp(season, cache_dir)
    reg = pbp[(pbp.season_type == 'REG') & pbp.week.notna()].copy()
    if reg.empty:
        raise ValueError(f'no regular-season plays for {season} yet')
    roster = load_roster(season, cache_dir)
    names = roster.dropna(subset=['gsis_id']).drop_duplicates('gsis_id', keep='last').set_index('gsis_id').full_name
    ids = qb_ids(reg, roster)
    x = F.select_plays(reg, ids)
    weeks = sorted(int(w) for w in reg.week.unique())

    r, q, pairs = _ratings(x, reg)
    q['name'] = q['name'].astype(str)
    short_names = q.groupby('qb')['name'].agg(lambda s: s.mode().iloc[0])

    # season-to-date ratings as of each week
    history = {}
    prev_rank = {}
    for w in weeks:
        rw, _, _ = _ratings(x[x.week <= w], reg[reg.week <= w])
        for qb, row in rw.iterrows():
            history.setdefault(qb, []).append({'week': w, 'cqr': _score(row.cqr),
                                               'rank': None if pd.isna(row['rank']) else int(row['rank'])})
        if len(weeks) > 1 and w == weeks[-2]:
            prev_rank = rw['rank'].dropna().astype(int).to_dict()

    cur = pd.DataFrame({'value_raw': (r.total / r.denom).where(r.denom > 0), 'denom': r.denom})
    tal = T.estimate(cur, season, roster, out_dir)

    gscore = F.rate(q, prior=F.GAME_PRIOR_DROPBACKS, by=('qb', 'game_id'))
    gbox = box(q, by=('qb', 'game_id'))
    sbox = box(q)
    meta = reg.drop_duplicates('game_id').set_index('game_id')[['week', 'home_team', 'away_team', 'home_score', 'away_score']]

    qbs = []
    for qb, row in r.sort_values('cqr', ascending=False).iterrows():
        # QB rankings are for quarterbacks by usage: skip gadget players who mostly run (e.g. Taysom Hill)
        if row.plays < 10 or row.dropbacks < MIN_DROPBACK_SHARE * row.plays:
            continue
        games = int(row.games)
        teams = list(dict.fromkeys(q.loc[q.qb == qb].sort_values('week').posteam))
        qbs.append({
            'id': qb,
            'name': names.get(qb) or short_names.get(qb, qb),
            'team': row.team,
            'teams': teams,
            'rank': None if pd.isna(row['rank']) else int(row['rank']),
            'prev_rank': prev_rank.get(qb),
            'qualified': bool(row.qualified),
            'cqr': _score(row.cqr),
            'per_dropback': _round(row.per_dropback, 3),
            'value_raw': _round(row.total / row.denom, 4) if row.denom > 0 else None,
            'denom': _round(row.denom, 1),
            'talent': {'cqr': _score(tal.at[qb, 'cqr']), 'rank': None,
                       'evidence': _round(tal.at[qb, 'evidence'], 0),
                       'share_season': _round(tal.at[qb, 'share_season'], 3),
                       'share_history': _round(tal.at[qb, 'share_history'], 3)},
            'games': games,
            'dropbacks': int(row.dropbacks),
            'plays': int(row.plays),
            'pts_per_game': _round(row.total / games, 2),
            'components': {k: _round(row[k] / games, 2) for k in ('passing', 'rushing', 'sacks', 'schedule')},
            'box': _box_dict(sbox.loc[qb]),
            'history': history.get(qb, []),
            'games_log': _game_rows(qb, q, meta, gscore, gbox),
        })

    ranked = sorted((e for e in qbs if e['talent']['evidence'] >= T.MIN_EVIDENCE), key=lambda e: -e['talent']['cqr'])
    for i, entry in enumerate(ranked, 1):
        entry['talent']['rank'] = i

    base = F.baselines(x)
    audit = sanity_check(r, sbox)
    payload = {
        'season': season,
        'season_type': 'REG',
        'through_week': weeks[-1],
        'weeks': weeks,
        'last_game_date': str(reg.game_date.max()),
        'games_played': int(reg.game_id.nunique()),
        'generated_at': dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        'qualify_dropbacks_per_team_game': F.QUALIFY_DROPBACKS_PER_TEAM_GAME,
        'baselines': {k: {'points': round(v[0], 3), 'adj_yards': round(v[1], 2)} for k, v in base.items()},
        'sanity_check': audit,
        'formula_version': F.FORMULA_VERSION,
        'live_check': live_check(x, weeks),
        'qbs': qbs,
    }
    _write_if_changed(os.path.join(out_dir, f'{season}.json'), payload)
    return payload


def _write_if_changed(path: str, payload: dict):
    """Write JSON unless only the timestamp would change (keeps the scheduled job from committing no-op updates)."""
    try:
        with open(path) as fh:
            old = json.load(fh)
        if {k: v for k, v in old.items() if k != 'generated_at'} == {k: v for k, v in payload.items() if k != 'generated_at'}:
            payload['generated_at'] = old.get('generated_at', payload['generated_at'])
            return False
    except (OSError, ValueError):
        pass
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w') as fh:
        json.dump(payload, fh, separators=(',', ':'))
    return True


def write_index(out_dir: str = SITE_DATA, current: int | None = None):
    seasons = sorted(int(f[:4]) for f in os.listdir(out_dir) if f[:4].isdigit() and f.endswith('.json'))
    current = current if current in seasons else max(seasons)
    with open(os.path.join(out_dir, f'{current}.json')) as fh:
        cur = json.load(fh)
    idx = {'current': current, 'seasons': seasons[::-1], 'through_week': cur['through_week'],
           'generated_at': cur['generated_at']}
    with open(os.path.join(out_dir, 'index.json'), 'w') as fh:
        json.dump(idx, fh, indent=1)
        fh.write('\n')
    return idx


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--season', type=int, help='season to build (default: current)')
    ap.add_argument('--all', action='store_true', help=f'build every season from {FIRST_SEASON}')
    ap.add_argument('--cache', default='.cache')
    ap.add_argument('--out', default=SITE_DATA)
    args = ap.parse_args(argv)
    season = args.season or current_season()
    seasons = range(FIRST_SEASON, season + 1) if args.all else [season]
    built = None
    for s in seasons:
        try:
            p = build_season(s, args.cache, args.out)
            built = s
            print(f'{s}: through week {p["through_week"]}, {len(p["qbs"])} QBs')
        except (FileNotFoundError, ValueError) as err:
            # e.g. early September before the new season's first game
            print(f'{s}: skipped ({err})')
    idx = write_index(args.out, built)
    print(f'index: current={idx["current"]} seasons={idx["seasons"][0]}..{idx["seasons"][-1]}')


if __name__ == '__main__':
    main()
