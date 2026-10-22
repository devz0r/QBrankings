import numpy as np
import pandas as pd
import pytest

from qbrank import formula as F


def play(**kw):
    """One nflverse-style play row with neutral defaults (a 5-yard completion by QB 'A')."""
    row = dict(
        play_id=1, game_id='G1', season=2026, season_type='REG', week=1, game_date='2026-09-13',
        posteam='AAA', defteam='BBB', home_team='AAA', away_team='BBB', home_score=20, away_score=10,
        qtr=1, down=1, ydstogo=10, half_seconds_remaining=1500, score_differential=0,
        play_type='pass', **{'pass': 1}, rush=0, qb_dropback=1, qb_scramble=0, qb_kneel=0, qb_spike=0,
        aborted_play=0, two_point_attempt=0, pass_attempt=1, complete_pass=1, interception=0, sack=0,
        pass_touchdown=0, rush_touchdown=0, td_team=None, fumble=0, fumble_lost=0, fumbled_1_player_id=None,
        id='A', passing_yards=5.0, rushing_yards=np.nan, yards_gained=5.0, air_yards=3.0,
        yards_after_catch=2.0, xyac_mean_yardage=2.0, epa=0.1, qb_epa=0.1, yac_epa=0.1, xyac_epa=0.1,
        penalty_type=None, penalty_yards=np.nan, cpoe=0.0, first_down=0, name='A.QB',
    )
    row.update(kw)
    return row


def frame(rows):
    return pd.DataFrame(rows)


def valued(rows, qbs=('A', 'B', 'C')):
    x = F.select_plays(frame(rows), set(qbs))
    return F.play_values(x)


def test_scale_is_centered_and_monotonic():
    assert F.cqr(0.0) == pytest.approx(50.0)
    v = np.linspace(-0.5, 0.5, 41)
    s = F.cqr(v)
    assert np.all(np.diff(s) > 0) and s.min() > 0 and s.max() < 100


def test_excludes_kneels_spikes_and_offensive_penalty_plays():
    rows = [play(play_id=1), play(play_id=2, qb_kneel=1, play_type='qb_kneel'),
            play(play_id=3, qb_spike=1, play_type='qb_spike'),
            play(play_id=4, play_type='no_play', penalty_type='Offensive Holding', epa=-1.0, qb_epa=-1.0)]
    q = valued(rows)
    assert list(q.play_id) == [1]


def test_dpi_counts_half():
    rows = [play(play_id=1, play_type='no_play', qb_dropback=0, pass_attempt=0, complete_pass=0,
                 penalty_type='Defensive Pass Interference', penalty_yards=20.0, epa=2.0, qb_epa=2.0,
                 yac_epa=np.nan, xyac_epa=np.nan)]
    x = F.select_plays(frame(rows), {'A'})
    assert x.kind.iloc[0] == 'dpi'
    assert x.pts.iloc[0] == pytest.approx(1.0)
    assert x.adj_yds.iloc[0] == pytest.approx(10.0)


def test_fumble_recovery_luck_is_removed():
    lost = play(play_id=1, sack=1, pass_attempt=0, complete_pass=0, fumble=1, fumble_lost=1,
                fumbled_1_player_id='A', epa=-5.4, qb_epa=-5.4, yards_gained=-7.0)
    kept = dict(lost, play_id=2, fumble_lost=0, epa=-1.5, qb_epa=-1.5)
    x = F.select_plays(frame([lost, kept]), {'A'})
    # actual EPA gap is 3.9; after neutralizing recovery luck the two plays differ by only 3.9 - 4.0
    assert abs(x.pts.iloc[0] - x.pts.iloc[1]) < 0.2
    # yards side charges the same expected cost to both
    assert x.adj_yds.iloc[0] == pytest.approx(x.adj_yds.iloc[1])


def test_yac_over_expected_share_applies_to_both_halves():
    rows = [play(play_id=1, epa=4.0, qb_epa=4.0, yac_epa=3.5, xyac_epa=0.5, passing_yards=60.0,
                 yards_after_catch=55.0, xyac_mean_yardage=5.0)]
    x = F.select_plays(frame(rows), {'A'})
    assert x.pts.iloc[0] == pytest.approx(4.0 - F.YAC_RECEIVER_SHARE * 3.0)
    assert x.adj_yds.iloc[0] == pytest.approx(60.0 - F.YAC_RECEIVER_SHARE * 50.0)


def test_arm_punt_interception_waiver_is_gradual():
    base = dict(complete_pass=0, interception=1, passing_yards=np.nan, yards_after_catch=np.nan,
                xyac_mean_yardage=np.nan, yac_epa=np.nan, xyac_epa=np.nan, epa=-1.5, qb_epa=-1.5)
    rows = [play(play_id=1, down=3, ydstogo=15, air_yards=30.0, **base),   # full arm punt
            play(play_id=2, down=1, ydstogo=10, air_yards=35.0, **base),   # early down: full charge
            play(play_id=3, down=3, ydstogo=10, air_yards=19.0, **base),
            play(play_id=4, down=3, ydstogo=10, air_yards=20.0, **base)]
    x = F.select_plays(frame(rows), {'A'}).set_index('play_id')
    if F.ARM_PUNT_MODE != 'smooth':
        pytest.skip('sliding scale disabled')
    assert x.adj_yds[1] == pytest.approx(0.0)
    assert x.adj_yds[2] == pytest.approx(-45.0)
    # no cliff: one extra air yard changes the charge by about a yard, not 45
    assert abs(x.adj_yds[4] - x.adj_yds[3]) < 2
    assert x.adj_yds[4] == pytest.approx(-45.0 * (1 - 0.5 * 0.5))


def test_run_heavy_gadget_qb_is_not_divided_by_a_handful_of_dropbacks():
    run = dict(play_type='run', **{'pass': 0}, rush=1, qb_dropback=0, pass_attempt=0, complete_pass=0,
               passing_yards=np.nan, rushing_yards=7.0, yards_gained=7.0, epa=0.4, qb_epa=0.4,
               yac_epa=np.nan, xyac_epa=np.nan)
    r, _, _ = F.rate_season(F.select_plays(_league([run] * 60), {'A', 'B', 'C'}))
    floor = F.MIN_DENOM_SHARE * r.loc['A', 'plays']
    assert r.loc['A', 'per_dropback'] == pytest.approx(r.loc['A', 'total'] / (floor + F.QB_PRIOR_DROPBACKS))


def test_end_of_half_heave_interception_costs_no_yards():
    base = dict(complete_pass=0, interception=1, passing_yards=np.nan, yards_after_catch=np.nan,
                xyac_mean_yardage=np.nan, yac_epa=np.nan, xyac_epa=np.nan, epa=-0.1, qb_epa=-0.1)
    heave = play(play_id=1, half_seconds_remaining=3, air_yards=50.0, **base)
    normal = play(play_id=2, half_seconds_remaining=600, air_yards=10.0, **base)
    x = F.select_plays(frame([heave, normal]), {'A'})
    assert x.adj_yds.iloc[0] == pytest.approx(0.0)
    assert x.adj_yds.iloc[1] == pytest.approx(-45.0)


def test_clutch_weight():
    rows = [play(play_id=1, qtr=4, score_differential=-7), play(play_id=2, qtr=4, score_differential=-14),
            play(play_id=3, qtr=5, score_differential=0), play(play_id=4, qtr=2, score_differential=3)]
    x = F.select_plays(frame(rows), {'A'})
    assert list(x.weight) == [1.25, 1.0, 1.25, 1.0]


def _league(extra_for_a=()):
    """Three QBs with identical plays; QB A optionally gets extra plays."""
    rows, pid = [], 0
    for qb, team, opp in (('A', 'AAA', 'BBB'), ('B', 'BBB', 'CCC'), ('C', 'CCC', 'AAA')):
        for i in range(30):
            pid += 1
            good = i % 3 == 0
            rows.append(play(play_id=pid, id=qb, posteam=team, defteam=opp, game_id=f'G{qb}',
                             passing_yards=12.0 if good else 4.0, yards_gained=12.0 if good else 4.0,
                             epa=0.8 if good else -0.2, qb_epa=0.8 if good else -0.2))
        for i in range(10):  # running back carries set the league run baseline
            pid += 1
            rows.append(play(play_id=pid, id='RB' + qb, posteam=team, defteam=opp, game_id=f'G{qb}',
                             play_type='run', **{'pass': 0}, rush=1, qb_dropback=0, pass_attempt=0,
                             complete_pass=0, passing_yards=np.nan, rushing_yards=4.0, yards_gained=4.0,
                             epa=-0.1, qb_epa=-0.1, yac_epa=np.nan, xyac_epa=np.nan))
    for kw in extra_for_a:
        pid += 1
        rows.append(play(play_id=pid, id='A', posteam='AAA', defteam='BBB', game_id='GA', **kw))
    return frame(rows)


def test_better_production_never_lowers_rating():
    td = dict(passing_yards=30.0, yards_gained=30.0, pass_touchdown=1, td_team='AAA', epa=4.0, qb_epa=4.0)
    r_plain, _, _ = F.rate_season(F.select_plays(_league([dict(epa=0.0, qb_epa=0.0)]), {'A', 'B', 'C'}))
    r_td, _, _ = F.rate_season(F.select_plays(_league([td]), {'A', 'B', 'C'}))
    assert r_td.loc['A', 'cqr'] > r_plain.loc['A', 'cqr']


def test_sack_hurts_and_designed_run_adds_without_diluting():
    sack = dict(sack=1, pass_attempt=0, complete_pass=0, passing_yards=np.nan, yards_gained=-8.0,
                epa=-1.8, qb_epa=-1.8, yac_epa=np.nan, xyac_epa=np.nan)
    neutral = dict(epa=0.0, qb_epa=0.0)
    r0, _, _ = F.rate_season(F.select_plays(_league([neutral]), {'A', 'B', 'C'}))
    r1, _, _ = F.rate_season(F.select_plays(_league([sack]), {'A', 'B', 'C'}))
    assert r1.loc['A', 'cqr'] < r0.loc['A', 'cqr']
    # a good designed run adds value but is not a dropback, so it can't dilute the passing rate
    run = dict(play_type='run', **{'pass': 0}, rush=1, qb_dropback=0, pass_attempt=0, complete_pass=0,
               passing_yards=np.nan, rushing_yards=9.0, yards_gained=9.0, epa=0.6, qb_epa=0.6,
               yac_epa=np.nan, xyac_epa=np.nan)
    r2, _, _ = F.rate_season(F.select_plays(_league([run]), {'A', 'B', 'C'}))
    assert r2.loc['A', 'dropbacks'] == r0.loc['A', 'dropbacks'] - 1
    assert r2.loc['A', 'rushing'] > 0


def test_league_average_qb_is_fifty():
    rows, pid = [], 0
    for qb, team, opp in (('A', 'AAA', 'BBB'), ('B', 'BBB', 'AAA')):
        for i in range(200):
            pid += 1
            rows.append(play(play_id=pid, id=qb, posteam=team, defteam=opp))
    r, _, _ = F.rate_season(F.select_plays(frame(rows), {'A', 'B'}))
    assert r.cqr.tolist() == pytest.approx([50.0, 50.0], abs=1e-6)


def test_talent_blends_season_history_and_prior(tmp_path):
    import json
    from qbrank import talent as T
    json.dump({'qbs': [{'id': 'A', 'value_raw': 0.2, 'denom': 600.0}, {'id': 'Y', 'value_raw': 0.0, 'denom': 500.0}]},
              open(tmp_path / '2025.json', 'w'))
    roster = pd.DataFrame({'gsis_id': ['A', 'R', 'Y'], 'rookie_year': [2016, 2026, 2024],
                           'entry_year': [2016, 2026, 2024], 'draft_number': [10, 5, 1]})
    cur = pd.DataFrame({'value_raw': [-0.1, 0.1, 0.1], 'denom': [200.0, 200.0, 200.0]}, index=['A', 'R', 'Y'])
    t = T.estimate(cur, 2026, roster, str(tmp_path))
    h = T.HISTORY_WEIGHT * (1 - 200 / T.FADE_DROPBACKS) * 600
    expect = (200 * -0.1 + h * 0.2 + T.REGRESS_DROPBACKS * T.PRIOR['vet']) / (200 + h + T.REGRESS_DROPBACKS)
    assert t.at['A', 'value'] == pytest.approx(expect)
    assert t.at['A', 'share_season'] > 0.6          # this season leads five games in
    # a first-round rookie with no history regresses toward the rookie starting point
    assert t.at['R', 'value'] == pytest.approx((200 * 0.1 + T.REGRESS_DROPBACKS * T.PRIOR['first_round_rookie']) / (200 + T.REGRESS_DROPBACKS))
    # a third-year QB gets the young-QB bump on last season's value
    hy = T.HISTORY_WEIGHT * (1 - 200 / T.FADE_DROPBACKS) * 500
    assert t.at['Y', 'value'] == pytest.approx((200 * 0.1 + hy * T.YOUNG_BONUS + T.REGRESS_DROPBACKS * T.PRIOR['vet']) / (200 + hy + T.REGRESS_DROPBACKS))
    # history fades away by a full season of dropbacks
    late = T.estimate(pd.DataFrame({'value_raw': [-0.1], 'denom': [600.0]}, index=['A']), 2026, roster, str(tmp_path))
    assert late.at['A', 'share_history'] == 0
