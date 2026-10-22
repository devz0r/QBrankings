"""Fit and test the best-QB (talent) weights in qbrank/talent.py.

    python tools/talent_fit.py dataset CACHE_DIR ds.pkl     # rest-of-season targets, 2016-2025
    python tools/talent_fit.py fit ds.pkl fit.pkl           # grid search on 2018-2021, test on 2022-2025

The model predicts each QB's rest-of-season CQR value per dropback from the first N weeks plus past seasons.
"""
import sys
MODE = sys.argv.pop(1)
if MODE == 'dataset':
    import sys, pickle, numpy as np, pandas as pd
    sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))
    from qbrank import formula as F
    from qbrank.build import qb_ids
    from qbrank.data import load_pbp, load_roster
    CACHE = sys.argv[1]
    seasons = {}; rows = []; meta = {}
    def rated(x):
        r, _, _ = F.rate_season(x)
        q = F.play_values(x); q = F.apply_defense(q, F.defense_adjustments(q))
        r0 = F.rate(q, prior=0.0)
        return r0[['per_dropback', 'denom', 'dropbacks', 'plays']].rename(columns={'per_dropback': 'v', 'denom': 'n'})
    for y in range(2016, 2026):
        pbp = load_pbp(y, CACHE, max_age_hours=1e9); reg = pbp[pbp.season_type == 'REG']
        ro = load_roster(y, CACHE, max_age_hours=1e9)
        for _, r in ro.dropna(subset=['gsis_id']).drop_duplicates('gsis_id', keep='last').iterrows():
            meta.setdefault(r.gsis_id, {}).update(name=r.full_name, birth=r.birth_date, draft=r.draft_number, rookie=r.rookie_year if not pd.isna(r.rookie_year) else r.entry_year)
        x = F.select_plays(reg, qb_ids(reg, ro))
        seasons[y] = rated(x)
        for N in (0, 2, 4, 6, 8, 10, 12, 14):
            now = rated(x[x.week <= N]) if N else None
            rest = rated(x[x.week > N])
            for qb, rr in rest.iterrows():
                if rr.n < 50 or rr.dropbacks < 0.5 * rr.plays: continue
                v_now, n_now = (now.v.get(qb, np.nan), now.n.get(qb, 0.0)) if now is not None else (np.nan, 0.0)
                rows.append(dict(season=y, qb=qb, N=N, v_now=v_now if n_now > 0 else 0.0, n_now=n_now, v_rest=rr.v, n_rest=rr.n))
        print(y, len(rows), flush=True)
    pickle.dump((seasons, pd.DataFrame(rows), meta), open(sys.argv[2], 'wb'))
else:
    import sys, pickle, itertools, numpy as np, pandas as pd
    seasons, ds, meta = pickle.load(open(sys.argv[1], 'rb'))
    def hist(qb, y, d):
        num = den = 0.0
        for k in range(1, 4):                      # up to three previous seasons
            s = seasons.get(y - k)
            if s is None or qb not in s.index: continue
            r = s.loc[qb]
            if r.dropbacks < 0.5 * r.plays or r.n <= 0: continue
            w = d ** (k - 1) * r.n
            num += w * r.v; den += w
        return (num / den if den else 0.0), den
    def group(qb, y):
        m = meta.get(qb, {}); rk = m.get('rookie')
        if rk is not None and not pd.isna(rk) and int(rk) >= y:
            return 'r1' if (not pd.isna(m.get('draft')) and m.get('draft') <= 32) else 'rx'
        return 'vet'
    def age(qb, y):
        b = meta.get(qb, {}).get('birth')
        try:
            v = (pd.Timestamp(f'{y}-09-01') - pd.Timestamp(b)).days / 365.25
            return 28.0 if pd.isna(v) else v
        except Exception: return 28.0
    ds = ds.copy()
    ds['g'] = [group(q, y) for q, y in zip(ds.qb, ds.season)]
    ds['age'] = [age(q, y) for q, y in zip(ds.qb, ds.season)]
    G = ['r1', 'rx', 'vet']
    def predict(df, d, h, m, a, mu=None):
        H, W = zip(*[hist(q, y, d) for q, y in zip(df.qb, df.season)])
        H = np.array(H) - a * np.maximum(0, df.age.values - 33); W = np.array(W) * h
        den = df.n_now.values + W + m
        A = (df.n_now.values * df.v_now.values + W * H) / den; B = m / den
        if mu is None:   # closed-form weighted least squares for each group's prior mean
            mu = {}
            for g in G:
                k = (df.g == g).values; wt = df.n_rest.values[k]
                mu[g] = float(np.sum(wt * B[k] * (df.v_rest.values[k] - A[k])) / max(np.sum(wt * B[k] ** 2), 1e-9))
        return A + B * df.g.map(mu).values, mu
    def score(df, p):
        w = df.n_rest.values; e = df.v_rest.values - p
        return float(np.sqrt(np.sum(w * e * e) / w.sum())), float(np.corrcoef(p, df.v_rest)[0, 1])
    tune = ds[ds.season.between(2018, 2021)]; test = ds[ds.season.between(2022, 2025)]
    best = None
    for d, h, m, a in itertools.product([0.3, 0.5, 0.7, 0.85, 1.0], [0.25, 0.5, 0.75, 1.0, 1.5], [50, 100, 200, 400, 800], [0.0, 0.01, 0.02, 0.04]):
        p, mu = predict(tune, d, h, m, a)
        rmse = score(tune, p)[0]
        if best is None or rmse < best[0]: best = (rmse, d, h, m, a, mu)
    print('best on 2018-2021:', best)
    _, d, h, m, a, mu = best
    p_model, _ = predict(test, d, h, m, a, mu)
    p_cqr = test.n_now * test.v_now / (test.n_now + 100)
    H1 = np.array([hist(q, y, 0.0001)[0] if hist(q, y, 0.0001)[1] else 0.0 for q, y in zip(test.qb, test.season)])
    out = []
    for N in sorted(test.N.unique()):
        k = (test.N == N).values; t = test[k]
        row = {'N': N, 'n': int(k.sum()), 'model': score(t, p_model[k]), 'cqr_only': score(t, p_cqr.values[k]) if N else None, 'last_season_only': score(t, H1[k])}
        out.append(row); print(row)
    pickle.dump({'params': dict(decay=d, hist_weight=h, regress=m, age_slope=a, mu=mu), 'test': out}, open(sys.argv[2], 'wb'))
