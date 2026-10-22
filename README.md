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
       (no INT charge on end-of-half heaves; on 3rd/4th down the charge is scaled down for deep
        "arm punts": waived × ramp(yards to go, 5→15) × ramp(air yards, 10→30). EPA still charges
        what those plays actually cost.)
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
| Arm-punt interceptions | A deep pick on 3rd-and-15 is roughly a punt; EPA prices it that way, so the yards side scales its charge down smoothly instead of double-charging it. (A sliding scale replaced an all-or-nothing cutoff that swung a play's value by 3.3 points over one air yard; it tested the same.) |
| Designed runs against an average NFL run | Credits dual threats for what their runs add over a normal run play, without penalizing pocket passers. |
| 1.25× late and close | A judgment call the data only mildly supports: it improved the 2016-2020 fit and the link to winning on 2021-2025, and cost a little week-to-week consistency. CQR is an average, so fewer crunch-time snaps never lowers a score. |
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
| **CQR v1.1** | 0.554 | 0.391 | 0.758 |
| EPA per play | 0.529 (n.s.) | 0.392 (n.s.) | 0.770 (n.s.) |
| ESPN Total QBR | 0.589 (n.s.) | 0.352 (n.s.) | 0.700 (CQR ahead, narrowly) |
| ANY/A | 0.484 (CQR ahead) | 0.339 (n.s.) | 0.709 (CQR ahead) |
| Passer rating | 0.348 (CQR ahead) | 0.315 (n.s.) | 0.653 (CQR ahead) |

n.s. = no significant difference detected, which is not the same as proven equal. Intervals come from a
paired bootstrap that resamples whole quarterbacks 1,000 times, so a QB who appears in several seasons
counts as one unit.

Caveat: the weights were fitted on 2016-2020 only, but earlier versions of CQR had been looked at on all of
2016-2025 while the overall design took shape, so 2021-2025 is not perfectly untouched. The clean test is
the live check below.

Split-half compares a QB's rating in odd weeks with the same QB's rating in even weeks; year to year
compares consecutive seasons; the last column correlates with the team's win rate in that QB's starts.
Honest summary: CQR beats passer rating and ANY/A, shows no significant difference from raw EPA, and tracks winning
a little better than Total QBR. Its edge is completeness and transparency, not a leap in accuracy. The
original 50/50 formula scored the same on these seasons (0.553 / 0.390 / 0.766), so tuning changed little.

### Live check (2026 onward)

CQR v1.1 was frozen on Oct 22, 2026 (`FORMULA_VERSION` in `qbrank/formula.py`). Every weekly build re-scores
it against EPA per play, ANY/A and passer rating on the current season (odd vs. even weeks, and the first
half of the weeks played vs. the rest) and shows the result on the site. Weeks 1-6 of 2026 were visible
while the formula was built; from Week 7 on, the evidence is fully independent. Early-season samples are
small, so expect these numbers to bounce around until late in the year. The plan is to leave the formula
alone unless this check shows a real problem.

### Eye test (2016-2025)

* The AP MVP ranked in CQR's top three in 8 of 9 seasons (2016-2024), and first or second in 7. Tom Brady in
  2017 was 3rd, 0.2 behind Carson Wentz and 1.1 behind Drew Brees. Lamar Jackson in 2023 was 5th, behind
  Purdy, Prescott, Allen and Tagovailoa, who were more efficient per play.
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
