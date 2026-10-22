# CQR: Complete Quarterback Rating

One number for everything a quarterback does: passing, running, sacks, turnovers, crunch time and the
defenses faced. 50 is exactly league average; 90+ is an MVP-level season.

The site in `site/` shows live rankings for the current NFL season, every season back to 2016, the formula
and its track record. A GitHub Actions workflow rebuilds it on Monday, Tuesday and Friday mornings during
the season, so Sunday, Monday-night and Thursday-night games are always in.

## The formula

Every play a quarterback is responsible for gets a value **A**, measured against an average play of the
same kind:

```
A    = ⅓ × (EPA* − avg) + ⅔ × (AY − avg) ÷ 9

EPA* = EPA
       + 4 × (lost − p)      on the QB's own fumbles
       × ½                   on pass interference drawn

AY   = pass yds + rush yds − sack yds + 20 × TD − 45 × INT − 45 × p per fumble
       (no INT charge on end-of-half heaves or on 3rd/4th-and-10+ throws of 20+ air yards,
        which work like punts; EPA still charges what they actually cost)
```

* **avg** is the league average for a dropback, or for an NFL run in the same situation (short yardage or
  not) when the play is a designed QB run.
* **p** is how often that kind of fumble is lost league-wide (strip-sack 52%, designed run 41%, botched
  snap 26%, other dropback 19%).
* **EPA** is nflfastR's expected points added; **AY** is an all-plays version of ANY/A. Nine adjusted yards
  equal one point, which gives the two parts equal spread before weighting.

Then:

```
              Σ w×A − Σ w×D
V  = ──────────────────────────────     w = 1.25 in the 4th quarter / OT within 8 points, else 1
     max(dropbacks, ¾ × plays) + 100    D = rating of the defense faced (per dropback)

CQR = 100 ÷ (1 + e^(−V ÷ 0.085))
```

* **D** is each defense's average A allowed to *other* teams' quarterbacks, regressed toward average with
  an 800-dropback prior.
* **+100** gives every QB 100 dropbacks of league-average play, so one hot game can't make a backup No. 1.
  It is not negligible: at 300 dropbacks it pulls a rating 25% of the way toward average, about 14% over
  a full season.
* Designed runs add to the numerator, and only count in the denominator once they push it below ¾ of all
  plays, so a dual threat's running adds value instead of diluting the passing rate.
* Qualified QBs have at least 14 dropbacks per team game (the NFL's passer-rating bar). Players who drop
  back on fewer than half their snaps (gadget QBs such as Taysom Hill) aren't listed.

Counted plays: pass attempts, sacks, scrambles, designed runs (including sneaks), botched snaps,
two-point tries and drawn defensive pass interference. Ignored: kneel-downs, spikes and plays wiped out by
any other penalty. Regular season only.

What CQR measures is **opponent-adjusted quarterback production**. It removes recovery luck, teammates'
penalties and schedule, but pass protection, drops, receivers and play design still show up in it, as they
do in every public QB stat.

The code is the spec: [`qbrank/formula.py`](qbrank/formula.py).

## Why each piece is there

| Piece | Why |
|---|---|
| Expected points (EPA) | Knows that 4 yards on 3rd-and-3 beats 9 yards on 3rd-and-12, and what a turnover or sack does to the drive. |
| Adjusted yards (AY) | Keeps the rating anchored to production fans can see, and is steadier than EPA. ⅓ / ⅔ was the best blend on 2016-2020. |
| Fumbles at their average cost | Putting the ball on the ground is the QB's fault; who recovers it is close to a coin flip. |
| Arm-punt interceptions | A deep pick on 3rd-and-15 is roughly a punt; EPA prices it that way and the yards side no longer double-charges it. |
| Designed runs against an average NFL run | Credits dual threats for what their runs add over a normal run play, without penalizing pocket passers. |
| 1.25× late and close | Crunch time matters, but a handful of snaps shouldn't decide a season. Kept because it tested slightly better than 1.0. |
| Defense adjustment | 300 yards against the best pass defense isn't 300 yards against the worst. |
| 100-dropback cushion | Small samples are noisy; this keeps a backup's great half from topping the list. |

Tested and left out: discounting garbage time (less stable, fixed nothing), giving receivers part of the
yards after catch (no gain on 2016-2020), counting drawn pass interference in full, and rewarding volume
(per-game value agreed less with the eye test than the per-dropback rate).

## Track record

### Out of sample (the fair test)

Weights were chosen on 2016-2020 only by a rule fixed in advance (`tools/holdout.py`), then frozen and
scored on 2021-2025. Paired bootstrap 95% intervals on the difference (CQR minus the other rating):

| Rating | Split-half | Year to year | Correlation with win % |
|---|---|---|---|
| **CQR** | 0.555 | 0.389 | 0.756 |
| EPA per play | 0.529 (tie) | 0.392 (tie) | 0.770 (tie) |
| ESPN Total QBR | 0.589 (tie) | 0.352 (tie) | 0.700 (CQR ahead) |
| ANY/A | 0.484 (CQR ahead) | 0.339 (tie) | 0.709 (CQR ahead) |
| Passer rating | 0.348 (CQR ahead) | 0.315 (tie) | 0.653 (CQR ahead) |

Split-half compares a QB's rating in odd weeks with the same QB's rating in even weeks; year to year
compares consecutive seasons; the last column correlates with the team's win rate in that QB's starts.
Honest summary: CQR beats passer rating and ANY/A, is statistically tied with raw EPA, and tracks winning
a little better than Total QBR. Its edge is completeness and transparency, not a leap in accuracy. The
original 50/50 formula scored the same on these seasons (0.553 / 0.390 / 0.766), so tuning changed little.

### Eye test (2016-2025)

* The AP MVP ranked first or second in CQR in 8 of 9 seasons (2016-2024). The exception is Lamar Jackson in
  2023 (6th, essentially tied with Jared Goff and C.J. Stroud; Purdy, Prescott, Allen and Tagovailoa were
  more efficient per play).
* **Clear-cut pairs:** two qualified QBs in the same season where one is at least as good in passer rating,
  ANY/A, rushing yards per game, TDs per game, giveaways per game and sack rate. There were 852 of them;
  CQR orders 850 correctly. The exceptions: Burrow over Trubisky in 2020 (Trubisky's numbers came against
  soft defenses) and Garoppolo over Cousins in 2021 (near-identical box scores; Garoppolo averaged 8.7
  yards per attempt to Cousins' 7.6).
* Best seasons since 2016: Lamar Jackson 2024 (97.2), Lamar Jackson 2019 (96.8), Brock Purdy 2023 (95.6),
  Patrick Mahomes 2018 (95.3), Matt Ryan 2016 (94.5).

Reproduce with `python -m qbrank.validate` and `tools/holdout.py`.

## Best QBs right now (power ranking)

CQR answers "who has played best this season?" and only uses this season's plays. The site's second view,
**Best QBs right now**, leans on this season and steadies it with last season
([`qbrank/talent.py`](qbrank/talent.py)):

```
          n × V  +  h × n₁ × (V₁ + y)  +  50 × μ
    T  =  ─────────────────────────────────────        h = 0.2 × max(0, 1 − n ÷ 600)
          n      +  h × n₁              +  50          then the same 0-100 curve as CQR
```

* **V, n**: this season's CQR value per dropback (before the 100-dropback cushion) and its dropbacks.
* **V₁, n₁**: the same for last season. A last-season dropback counts 0.2 of a this-season dropback at the
  start of the year and fades to nothing by 600 dropbacks, so about five games in, this season is roughly
  60% of a regular starter's rating.
* **y**: +0.06 for QBs in their 2nd-4th seasons, who on average improve on their previous year.
* **μ**: the starting point for anyone with no history: veterans −0.08, first-round rookies −0.06, other
  rookies −0.19.

Tested on 2022-2025, seasons not used for fitting (`tools/talent_fit.py`), against a version that leaned on
three past seasons. Correlation with each QB's rest-of-season CQR:

| After week | This version | Three-season version | CQR alone |
|---|---|---|---|
| 2 | 0.47 | 0.46 | 0.25 |
| 6 | 0.50 | 0.51 | 0.36 |
| 10 | 0.51 | 0.49 | 0.40 |
| 14 | 0.47 | 0.45 | 0.40 |

Leaning on more history looked better on the seasons used for fitting but not on unseen ones, so the
simpler, current-season-first version costs essentially nothing. Wins, Pro Bowls, PFF grades and
reputation are deliberately left out: they can't be checked against outcomes or mostly measure the team.

## Running it

```bash
pip install -r requirements.txt
python -m qbrank.build              # current season -> site/data/<season>.json
python -m qbrank.build --all        # every season since 2016
python -m qbrank.validate           # back-test -> site/data/validation.json
python tools/holdout.py .cache tune tune_0.33.json 0.33   # out-of-sample test; see the script's docstring
python -m pytest -q
python -m http.server -d site 8000  # then open http://localhost:8000
```

Data comes from [nflverse](https://github.com/nflverse/nflverse-data) (play-by-play with the nflfastR
expected points model, plus rosters) and is cached in `.cache/`.

## Weekly updates and hosting

`.github/workflows/update-rankings.yml` runs on Monday, Tuesday and Friday at 13:17 UTC from September
through February. It tests the formula, rebuilds the current season, commits the new data and deploys
`site/` to GitHub Pages. Run it any time from the Actions tab ("Run workflow"); tick "Rebuild every season"
after changing the formula.

One-time setup: **Settings → Pages → Build and deployment → Source: GitHub Actions**. The site then lives at
`https://<user>.github.io/QBrankings/`.
