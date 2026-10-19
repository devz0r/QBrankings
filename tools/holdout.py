"""Out-of-sample test: tune CQR's weights on 2016-2020, freeze them, score 2021-2025 with paired bootstrap CIs.

    python tools/holdout.py CACHE_DIR tune OUT.json POINTS_WEIGHT   # one slice of the tuning grid
    python tools/holdout.py CACHE_DIR test '<frozen config json>' OUT.json

Objective (fixed before running): mean of split-half, year-to-year and win correlations on 2016-2020,
minus the clear-cut-pair violation rate.
"""
import sys, json, itertools, numpy as np, pandas as pd
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))
from qbrank import formula as F
from qbrank import validate as V
from qbrank.build import qb_ids, sanity_check, _ratings
from qbrank.data import load_pbp, load_roster
from qbrank.stats import box
CACHE = sys.argv[1]
MODE = sys.argv[2]           # 'tune' or 'test'
DEFAULT = dict(POINTS_WEIGHT=0.5, CLUTCH_WEIGHT=1.25, YAC_RECEIVER_SHARE=0.25, DPI_SHARE=0.5, ARM_PUNT_FREE=False)
qbr_week, qbr_season = V._qbr(CACHE)
RAW = {}
def raw(season):
    if season not in RAW:
        pbp = load_pbp(season, CACHE, max_age_hours=1e9); reg = pbp[pbp.season_type == 'REG']
        roster = load_roster(season, CACHE, max_age_hours=1e9)
        RAW[season] = (reg, qb_ids(reg, roster))
    return RAW[season]

def season_frames(season, cfg):
    for k, v in cfg.items(): setattr(F, k, v)
    reg, ids = raw(season)
    x = F.select_plays(reg, ids)
    m = V._metrics(x)
    m['qbr'] = qbr_season[qbr_season.season == season].drop_duplicates('gsis').set_index('gsis').qbr_total.reindex(m.index)
    halves = []
    for parity in (1, 0):
        h = V._metrics(x[x.week % 2 == parity])
        wk = qbr_week[(qbr_week.season == season) & (qbr_week.game_week % 2 == parity)].dropna(subset=['gsis'])
        h['qbr'] = wk.groupby('gsis').apply(lambda s: np.average(s.qbr_total, weights=s.qb_plays.clip(lower=1)), include_groups=False).reindex(h.index)
        halves.append(h)
    j = halves[0].join(halves[1], lsuffix='1', rsuffix='2', how='inner')
    j = j[(j.plays1 >= V.MIN_HALF_PLAYS) & (j.plays2 >= V.MIN_HALF_PLAYS)]
    games = reg.drop_duplicates('game_id')[['game_id', 'home_team', 'away_team', 'home_score', 'away_score']]
    full = m[m.plays >= V.MIN_PLAYS].join(V._team_win_pct(x[x.is_qb], games).rename('win'))
    r, q, _ = _ratings(x, reg)
    sc = sanity_check(r, box(q))
    return j, full, sc

def evaluate(seasons, cfg, keys=('cqr',)):
    per = {'split': [], 'yoy': [], 'win': []}; frames = []; pairs = viol = 0; prev = None
    for s in seasons:
        j, full, sc = season_frames(s, cfg)
        pairs += sc['pairs']; viol += len(sc['out_of_order'])
        y = prev.join(full, lsuffix='0', rsuffix='1', how='inner') if prev is not None else None
        frames.append((j, full, y)); prev = full
    return frames, pairs, viol

def stats(frames, k, idx=None):
    sp, yy, wn = [], [], []
    for i, (j, full, y) in enumerate(frames):
        jj, ff = (j, full) if idx is None else (j.iloc[idx[i][0]], full.iloc[idx[i][1]])
        sp.append(V._corr(jj[k + '1'], jj[k + '2'])); wn.append(V._corr(ff[k], ff.win))
        if y is not None:
            yv = y if idx is None else y.iloc[idx[i][2]]
            yy.append(V._corr(yv[k + '0'], yv[k + '1']))
    return np.nanmean(sp), np.nanmean(yy), np.nanmean(wn)

if MODE == 'tune':
    grid = dict(POINTS_WEIGHT=[float(sys.argv[4])], CLUTCH_WEIGHT=[1.0, 1.25], YAC_RECEIVER_SHARE=[0.0, 0.25, 0.5],
                DPI_SHARE=[0.5, 1.0], ARM_PUNT_FREE=[False, True])
    out = []
    for combo in itertools.product(*grid.values()):
        cfg = dict(zip(grid, combo))
        frames, pairs, viol = evaluate(range(2016, 2021), cfg)
        s, y, w = stats(frames, 'cqr')
        obj = (s + y + w) / 3 - viol / max(pairs, 1)
        out.append({**cfg, 'split': round(s, 4), 'yoy': round(y, 4), 'win': round(w, 4), 'viol': viol, 'pairs': pairs, 'obj': round(obj, 4)})
        print(json.dumps(out[-1]), flush=True)
    json.dump(out, open(sys.argv[3], 'w'), indent=1)
else:
    cfg = json.loads(sys.argv[3])
    rng = np.random.default_rng(7)
    res = {}
    for name, c in (('chosen', cfg), ('original', DEFAULT)):
        frames, pairs, viol = evaluate(range(2020, 2026), c)   # 2020 only serves as the 'previous season' for 2021 YoY
        frames = frames[1:]
        res[name] = (frames, pairs, viol)
    # recompute pairs/viol for 2021-2025 only
    for name, c in (('chosen', cfg), ('original', DEFAULT)):
        _, p, v = evaluate(range(2021, 2026), c); res[name] = (res[name][0], p, v)
    keys = ['cqr', 'epa', 'anya', 'rating', 'qbr']
    report = {}
    for name in res:
        frames, p, v = res[name]
        point = {k: stats(frames, k) for k in keys}
        boots = []
        for b in range(1000):
            idx = [(rng.integers(0, len(j), len(j)), rng.integers(0, len(f), len(f)), rng.integers(0, len(y), len(y)) if y is not None else None) for j, f, y in frames]
            boots.append({k: stats(frames, k, idx) for k in keys})
        rep = {'pairs': p, 'out_of_order': v, 'point': {k: [round(x, 3) for x in point[k]] for k in keys}, 'diff_ci': {}}
        for k in keys[1:]:
            d = np.array([[bb['cqr'][i] - bb[k][i] for i in range(3)] for bb in boots])
            rep['diff_ci'][k] = [[round(float(np.nanpercentile(d[:, i], 2.5)), 3), round(float(np.nanpercentile(d[:, i], 97.5)), 3)] for i in range(3)]
        report[name] = rep
        print(name, json.dumps(rep), flush=True)
    json.dump(report, open(sys.argv[4], 'w'), indent=1)
